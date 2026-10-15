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

from app.db.session import SessionLocal, ACTIVE_DB_ENGINE
from app.db.models import SavedConsultation, Opportunity
from app.engine.advisor_engine import advisor_engine, AdvisorEngine, normalize_prompt_fingerprint
import os

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
        Escanea todas las búsquedas activas vigentes en plataforma y entrega únicamente
        nuevas oportunidades verificadas con fotografía real a Telegram.
        """
        from app.services.telegram_advisor_bot import telegram_advisor_bot

        report = {
            "scanned_consultations": 0,
            "alerts_triggered": 0,
            "new_opportunities_delivered": 0,
            "details": []
        }

        # Nunca disparar alertas en entorno serverless si la BD cayó en fallback SQLite local
        if os.environ.get("VERCEL") and "SQLite" in str(ACTIVE_DB_ENGINE):
            logger.warning("[Alerts Worker] Ignorando escaneo en Vercel por estar en modo fallback SQLite.")
            return report

        close_db_when_done = False
        if db is None:
            db = SessionLocal()
            close_db_when_done = True

        try:
            # Saneamiento previo para descartar consultas vacías o duplicadas
            AdvisorEngine.deduplicate_saved_consultations(db)

            # Seleccionar únicamente consultas activas vigentes en la plataforma (no eliminadas, no pausadas y con fichas)
            active_consultations = db.query(SavedConsultation).filter(
                SavedConsultation.is_active == True,
                SavedConsultation.telegram_chat_id.isnot(None),
                SavedConsultation.telegram_chat_id != "",
                SavedConsultation.matched_opportunity_ids_json.isnot(None),
                SavedConsultation.matched_opportunity_ids_json != "[]",
                SavedConsultation.matched_count > 0
            ).order_by(SavedConsultation.id.desc()).all()

            report["scanned_consultations"] = len(active_consultations)
            logger.info(f"[Alerts Worker] Iniciando escaneo diario sobre {len(active_consultations)} búsquedas activas vigentes.")

            # Catálogo actual
            all_opps = advisor_engine.get_live_catalog_opportunities(db=db)

            for c in active_consultations:
                try:
                    # Re-verificar en BD que la consulta sigue existiendo y sigue activa (no eliminada ni pausada)
                    fresh_c = db.query(SavedConsultation).filter(
                        SavedConsultation.id == c.id,
                        SavedConsultation.is_active == True
                    ).first()
                    if not fresh_c:
                        logger.info(f"[Alerts Worker] Consulta #{c.id} ya no está activa o fue eliminada de plataforma. Omitiendo.")
                        continue

                    # Si no es forzado, verificar que no se haya alertado hoy (últimas 20 horas)
                    if not force and fresh_c.last_alert_at:
                        hours_since_last = (datetime.utcnow() - fresh_c.last_alert_at).total_seconds() / 3600.0
                        if hours_since_last < 20.0:
                            continue

                    # IDs ya entregados previamente
                    already_delivered = set()
                    if fresh_c.matched_opportunity_ids_json:
                        try:
                            raw_ids = json.loads(fresh_c.matched_opportunity_ids_json)
                            already_delivered = {str(x).strip().upper() for x in raw_ids if x}
                        except Exception:
                            already_delivered = set()

                    # Criterios de la consulta (enriquecidos siempre con el parser jerárquico actual)
                    heur_criteria = advisor_engine._parse_query_intent_heuristics(fresh_c.description or "")
                    criteria = dict(heur_criteria)
                    if fresh_c.criteria_json:
                        try:
                            stored_crit = json.loads(fresh_c.criteria_json)
                            if isinstance(stored_crit, dict):
                                for k, v in stored_crit.items():
                                    if v is not None and k not in ("municipality", "urbanization_or_street", "location_hierarchy"):
                                        criteria[k] = v
                                # Preservar siempre la jerarquía geográfica completa extraída del prompt original
                                for geo_key in ("province", "municipality", "postal_code", "urbanization_or_street", "zone_or_neighborhood", "location_hierarchy"):
                                    if heur_criteria.get(geo_key):
                                        criteria[geo_key] = heur_criteria[geo_key]
                        except Exception:
                            pass

                    # 1. Buscar en catálogo actual con filtro AND jerárquico estricto
                    matching = advisor_engine.filter_opportunities(all_opps, criteria)
                    new_opps = [o for o in matching if str(o.get("id")).strip().upper() not in already_delivered]

                    # 2. Si no hay suficientes nuevas en catálogo, intentar sincronización proactiva de portales
                    if len(new_opps) < max_cards_per_consultation:
                        try:
                            await advisor_engine.sync_portal_opportunities_on_demand(
                                criteria,
                                prompt_text=fresh_c.description,
                                target_count=max_cards_per_consultation,
                                db=db
                            )
                            all_opps = advisor_engine.get_live_catalog_opportunities(db=db)
                            matching = advisor_engine.filter_opportunities(all_opps, criteria)
                            new_opps = [o for o in matching if str(o.get("id")).strip().upper() not in already_delivered]
                        except Exception as e_sync:
                            logger.warning(f"Aviso en sincronización proactiva de alerta #{fresh_c.id}: {e_sync}")

                    if not new_opps:
                        continue

                    # 3. GUARDIAN DE CALIDAD Y FOTOGRAFÍA: Verificar que tengan fotos reales y sigan activas antes de enviar
                    to_deliver = advisor_engine.verify_and_filter_active_market_opportunities(
                        new_opps,
                        target_count=max_cards_per_consultation
                    )
                    if not to_deliver:
                        logger.info(f"[Alerts Worker] Consulta #{fresh_c.id}: 0 oportunidades tras filtro CatalogGuardian (sin fotos o inactivas).")
                        continue

                    # Re-comprobar justo antes de emitir a Telegram que no haya sido eliminada ni pausada durante el escaneo
                    db.expire_all()
                    still_active_c = db.query(SavedConsultation).filter(
                        SavedConsultation.id == fresh_c.id,
                        SavedConsultation.is_active == True
                    ).first()
                    if not still_active_c:
                        logger.info(f"[Alerts Worker] Consulta #{fresh_c.id} fue eliminada o pausada antes del envío. Cancelando envío.")
                        continue

                    chat_id = still_active_c.telegram_chat_id

                    # Enviar mensaje de cabecera de alerta
                    header_text = (
                        f"🔔 <b>ALERTA DIARIA HIVEX: {len(to_deliver)} NUEVAS OPORTUNIDADES</b>\n\n"
                        f"Para tu búsqueda activa: <b>«{html.escape(still_active_c.title or 'Búsqueda')}»</b> (ID #{still_active_c.id})\n"
                        f"Criterio: <i>«{html.escape((still_active_c.description or '')[:100])}...»</i>\n\n"
                        f"Hemos detectado los siguientes nuevos activos inmobiliarios que cumplen tus criterios:"
                    )
                    await telegram_advisor_bot.send_message(chat_id=chat_id, text=header_text, parse_mode="HTML")

                    # Enviar cada ficha visual (únicamente con foto real verificada)
                    cards_sent = 0
                    delivered_opp_ids = []
                    for opp in to_deliver:
                        try:
                            success = await telegram_advisor_bot.send_photo_card(chat_id=chat_id, opp=opp)
                            if success:
                                cards_sent += 1
                                if opp.get("id"):
                                    delivered_opp_ids.append(str(opp.get("id")).strip().upper())
                            await asyncio.sleep(0.85)  # Respetar rate limits de Telegram
                        except Exception as e_card:
                            logger.error(f"Error enviando tarjeta de alerta en chat {chat_id}: {e_card}")

                    # Actualizar registro de consulta con las nuevas oportunidades efectivamente entregadas
                    updated_ids_set = already_delivered.union(delivered_opp_ids)
                    still_active_c.matched_opportunity_ids_json = json.dumps(list(updated_ids_set))
                    still_active_c.matched_count = len(updated_ids_set)
                    still_active_c.last_alert_at = datetime.utcnow()
                    still_active_c.updated_at = datetime.utcnow()
                    db.commit()

                    report["alerts_triggered"] += 1
                    report["new_opportunities_delivered"] += cards_sent
                    report["details"].append({
                        "consultation_id": still_active_c.id,
                        "title": still_active_c.title,
                        "chat_id": chat_id,
                        "delivered_count": cards_sent
                    })
                    logger.info(f"[Alerts Worker] Alerta #{still_active_c.id} completada: {cards_sent} oportunidades entregadas a {chat_id}.")

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
        # Esperar antes del primer barrido automático tras un cold-start para evitar disparos espurios en despliegues
        await asyncio.sleep(60)
        while self.is_running:
            try:
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
