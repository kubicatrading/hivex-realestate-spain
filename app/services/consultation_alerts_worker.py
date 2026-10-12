"""
Servicio Cron / Worker de Alertas Diarias para Consultas Activas (HIVEX).
Recorre periódicamente las búsquedas y alertas activas (is_active == True),
descubre nuevas oportunidades en el catálogo y portales inmobiliarios
que no hayan sido entregadas previamente al usuario, y las notifica directamente
al grupo de Telegram (hasta un máximo de 20 oportunidades por día).
"""

import asyncio
import json
import html
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.db.models import SavedConsultation, Opportunity
from app.engine.advisor_engine import advisor_engine, normalize_prompt_fingerprint

logger = logging.getLogger(__name__)

class ConsultationAlertsWorker:
    def __init__(self):
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        self.interval_seconds = 3600  # Escaneo cada 1 hora para comprobar alertas pendientes

    async def run_daily_scan(
        self,
        db: Optional[Session] = None,
        force: bool = False,
        max_cards_per_consultation: int = 20
    ) -> Dict[str, Any]:
        """
        Escanea todas las búsquedas activas y entrega las nuevas oportunidades a Telegram.
        """
        from app.services.telegram_advisor_bot import telegram_advisor_bot

        close_db_when_done = False
        if db is None:
            db = SessionLocal()
            close_db_when_done = True

        report = {
            "scanned_consultations": 0,
            "alerts_triggered": 0,
            "new_opportunities_delivered": 0,
            "details": []
        }

        try:
            # Seleccionar consultas activas que tengan chat de Telegram asociado
            active_consultations = db.query(SavedConsultation).filter(
                SavedConsultation.is_active == True,
                SavedConsultation.telegram_chat_id.isnot(None),
                SavedConsultation.telegram_chat_id != ""
            ).order_by(SavedConsultation.id.desc()).all()

            report["scanned_consultations"] = len(active_consultations)
            logger.info(f"[Alerts Worker] Iniciando escaneo diario sobre {len(active_consultations)} búsquedas activas.")

            # Catálogo actual
            all_opps = advisor_engine.get_live_catalog_opportunities(db=db)
            opps_by_id = {str(o.get("id")).strip().upper(): o for o in all_opps}

            for c in active_consultations:
                try:
                    # Si no es forzado, verificar que no se haya alertado hoy (últimas 20 horas)
                    if not force and c.last_alert_at:
                        hours_since_last = (datetime.utcnow() - c.last_alert_at).total_seconds() / 3600.0
                        if hours_since_last < 20.0:
                            continue

                    # IDs ya entregados previamente
                    already_delivered = set()
                    if c.matched_opportunity_ids_json:
                        try:
                            raw_ids = json.loads(c.matched_opportunity_ids_json)
                            already_delivered = {str(x).strip().upper() for x in raw_ids if x}
                        except Exception:
                            already_delivered = set()

                    # Criterios de la consulta
                    criteria = {}
                    if c.criteria_json:
                        try:
                            criteria = json.loads(c.criteria_json)
                        except Exception:
                            pass
                    if not criteria:
                        criteria = advisor_engine._parse_query_intent_heuristics(c.description)

                    # 1. Buscar en catálogo actual
                    matching = advisor_engine.filter_opportunities(all_opps, criteria)
                    new_opps = [o for o in matching if str(o.get("id")).strip().upper() not in already_delivered]

                    # 2. Si no hay suficientes nuevas en catálogo, intentar sincronización proactiva de portales
                    if len(new_opps) < max_cards_per_consultation:
                        try:
                            # Sincronización proactiva externa sin superar el límite
                            await advisor_engine.sync_portal_opportunities_on_demand(
                                criteria,
                                prompt_text=c.description,
                                target_count=max_cards_per_consultation,
                                db=db
                            )
                            # Re-evaluar catálogo
                            all_opps = advisor_engine.get_live_catalog_opportunities(db=db)
                            opps_by_id = {str(o.get("id")).strip().upper(): o for o in all_opps}
                            matching = advisor_engine.filter_opportunities(all_opps, criteria)
                            new_opps = [o for o in matching if str(o.get("id")).strip().upper() not in already_delivered]
                        except Exception as e_sync:
                            logger.warning(f"Aviso en sincronización proactiva de alerta #{c.id}: {e_sync}")

                    if not new_opps:
                        continue

                    # Limitar entrega a max_cards_per_consultation (máx 20 al día)
                    to_deliver = new_opps[:max_cards_per_consultation]
                    chat_id = c.telegram_chat_id

                    # Enviar mensaje de cabecera de alerta
                    header_text = (
                        f"🔔 <b>ALERTA DIARIA HIVEX: {len(to_deliver)} NUEVAS OPORTUNIDADES</b>\n\n"
                        f"Para tu búsqueda activa: <b>«{html.escape(c.title or 'Búsqueda')}»</b> (ID #{c.id})\n"
                        f"Criterio: <i>«{html.escape(c.description[:100])}...»</i>\n\n"
                        f"Hemos detectado los siguientes nuevos activos inmobiliarios que cumplen tus criterios:"
                    )
                    await telegram_advisor_bot.send_message(chat_id=chat_id, text=header_text, parse_mode="HTML")

                    # Enviar cada ficha visual
                    cards_sent = 0
                    for opp in to_deliver:
                        try:
                            success = await telegram_advisor_bot.send_photo_card(chat_id=chat_id, opp=opp)
                            if success:
                                cards_sent += 1
                            await asyncio.sleep(0.85)  # Respetar rate limits de Telegram
                        except Exception as e_card:
                            logger.error(f"Error enviando tarjeta de alerta en chat {chat_id}: {e_card}")

                    # Actualizar registro de consulta con las nuevas oportunidades añadidas
                    new_ids = [str(o.get("id")).strip().upper() for o in to_deliver if o.get("id")]
                    updated_ids_set = already_delivered.union(new_ids)
                    c.matched_opportunity_ids_json = json.dumps(list(updated_ids_set))
                    c.matched_count = len(updated_ids_set)
                    c.last_alert_at = datetime.utcnow()
                    c.updated_at = datetime.utcnow()
                    db.commit()

                    report["alerts_triggered"] += 1
                    report["new_opportunities_delivered"] += cards_sent
                    report["details"].append({
                        "consultation_id": c.id,
                        "title": c.title,
                        "chat_id": chat_id,
                        "delivered_count": cards_sent
                    })
                    logger.info(f"[Alerts Worker] Alerta #{c.id} completada: {cards_sent} oportunidades entregadas a {chat_id}.")

                except Exception as e_item:
                    logger.error(f"Error procesando alerta para consulta #{c.id}: {e_item}")
                    db.rollback()

        except Exception as e_scan:
            logger.error(f"Error general en run_daily_scan: {e_scan}")
        finally:
            if close_db_when_done and db:
                db.close()

        return report

    async def _worker_loop(self):
        """Bucle periódico en segundo plano que vigila las alertas activas."""
        logger.info("[Alerts Worker] Bucle de alertas diarias iniciado.")
        while self.is_running:
            try:
                # Comprobar cada intervalo
                await self.run_daily_scan()
            except Exception as e:
                logger.error(f"[Alerts Worker] Error en ciclo de escaneo: {e}")
            await asyncio.sleep(self.interval_seconds)

    def start(self):
        """Inicia el worker en segundo plano."""
        if self.is_running:
            return
        self.is_running = True
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._worker_loop())
        logger.info("[Alerts Worker] Worker de alertas diarias registrado y activo.")

    def stop(self):
        """Detiene el worker."""
        self.is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("[Alerts Worker] Worker de alertas detenido.")

consultation_alerts_worker = ConsultationAlertsWorker()
