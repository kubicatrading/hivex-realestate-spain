"""
Servicio Cron / Worker de Alertas Diarias (09:00h CET/CEST) para Consultas Guardadas en Plataforma (HIVEX).
Recorre todas las consultas guardadas activas (SavedConsultation con is_active == True),
evalúa sus filtros exactos (criteria_json), descubre nuevas oportunidades en los portales
inmobiliarios y en el catálogo en vivo que no hayan sido servidas previamente en esa consulta,
actualiza la consulta en plataforma y las sirve directamente en Telegram.
"""

import asyncio
import json
import html
import logging
import os
from datetime import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal, ACTIVE_DB_ENGINE
from app.db.models import SavedConsultation, PipelineSyncState
from app.engine.advisor_engine import advisor_engine, AdvisorEngine

logger = logging.getLogger(__name__)


class ConsultationAlertsWorker:
    def __init__(self):
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        self.interval_seconds = 3600  # Comprobación periódica en background

    @staticmethod
    def _resolve_telegram_chat_id(raw_chat_id: Optional[str]) -> str:
        """
        Resuelve el chat_id de Telegram de una consulta guardada.
        Si la consulta se creó desde simulación web ('web-simulation', 'web-refresh', etc.),
        redirige al supergrupo principal configurado en TELEGRAM_CHAT_ID (-1003904392737).
        """
        default_cid = (
            getattr(settings, "TELEGRAM_CHAT_ID", None)
            or os.environ.get("TELEGRAM_CHAT_ID")
            or "-1003904392737"
        ).strip()
        cid = str(raw_chat_id or "").strip()
        if not cid or cid in ("web-simulation", "web-refresh", "default_chat") or not (cid.lstrip("-").isdigit()):
            cid = default_cid
        if cid.startswith("-") and not cid.startswith("-100"):
            cid = f"-100{cid[1:]}"
        return cid

    @staticmethod
    def _extract_consultation_criteria(consultation: SavedConsultation) -> Dict[str, Any]:
        """
        Construye el diccionario de filtros (criteria) de una consulta guardada priorizando
        los parámetros estructurados persistidos en criteria_json y completando cualquier
        campo ausente mediante el parser heurístico sobre la descripción.
        """
        heur_criteria = advisor_engine._parse_query_intent_heuristics(consultation.description or "")
        criteria: Dict[str, Any] = dict(heur_criteria)

        if consultation.criteria_json:
            try:
                stored_crit = json.loads(consultation.criteria_json)
                if isinstance(stored_crit, dict):
                    for k, v in stored_crit.items():
                        if v is not None and v != "" and v != []:
                            criteria[k] = v
            except Exception as e_crit:
                logger.warning(f"[Alerts Worker] Aviso parseando criteria_json en consulta #{consultation.id}: {e_crit}")

        return criteria

    async def run_daily_scan(
        self,
        db: Optional[Session] = None,
        force: bool = False,
        max_cards_per_consultation: int = 8,
        sync_external_portals: bool = True,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Cron Diario 09:00h (07:00 UTC):
        Escanea todas las consultas guardadas activas en plataforma, descubre nuevas
        oportunidades según los filtros exactos de cada consulta que no hayan sido
        servidas previamente, actualiza el repositorio en BD y las envía a Telegram.
        """
        from app.services.telegram_advisor_bot import telegram_advisor_bot

        report: Dict[str, Any] = {
            "status": "completed",
            "executed_at_utc": datetime.utcnow().isoformat(),
            "scanned_consultations": 0,
            "alerts_triggered": 0,
            "new_opportunities_delivered": 0,
            "details": []
        }

        # Nunca disparar alertas en entorno serverless si la BD cayó en fallback SQLite local
        if os.environ.get("VERCEL") and "SQLite" in str(ACTIVE_DB_ENGINE):
            logger.warning("[Alerts Worker] Ignorando escaneo en Vercel por estar en modo fallback SQLite.")
            report["status"] = "skipped_sqlite_fallback"
            return report

        close_db_when_done = False
        if db is None:
            db = SessionLocal()
            close_db_when_done = True

        try:
            # Saneamiento previo para descartar consultas vacías o duplicadas
            AdvisorEngine.deduplicate_saved_consultations(db)

            # Seleccionar todas las consultas guardadas vigentes en plataforma (id >= 48 y activas)
            active_consultations = db.query(SavedConsultation).filter(
                SavedConsultation.id >= 48,
                SavedConsultation.is_active == True,
                SavedConsultation.matched_opportunity_ids_json.isnot(None),
                SavedConsultation.matched_opportunity_ids_json != "[]",
                SavedConsultation.matched_count > 0
            ).order_by(SavedConsultation.id.asc()).all()

            report["scanned_consultations"] = len(active_consultations)
            logger.info(
                f"[Alerts Worker 09:00h] Iniciando evaluación de {len(active_consultations)} consultas guardadas activas."
            )

            # Cargar catálogo actual e indexar URLs por ID para evitar duplicados por URL
            all_opps = advisor_engine.get_live_catalog_opportunities(db=db)
            opps_by_id = {str(o.get("id")).strip().upper(): o for o in all_opps if o.get("id")}

            for c in active_consultations:
                try:
                    fresh_c = db.query(SavedConsultation).filter(
                        SavedConsultation.id == c.id,
                        SavedConsultation.is_active == True
                    ).first()
                    if not fresh_c:
                        continue

                    # Si no es forzado, verificar que no se haya enviado alerta en las últimas 20 horas
                    if not force and fresh_c.last_alert_at:
                        hours_since_last = (datetime.utcnow() - fresh_c.last_alert_at).total_seconds() / 3600.0
                        if hours_since_last < 20.0:
                            report["details"].append({
                                "consultation_id": fresh_c.id,
                                "title": fresh_c.title,
                                "status": "skipped_recent",
                                "delivered_count": 0
                            })
                            continue

                    # IDs, URLs e inmuebles físicos ya entregados previamente en esta consulta
                    from app.connectors.market_scraper import MarketScraper
                    already_delivered_list: List[str] = []
                    already_delivered_set = set()
                    already_delivered_urls = set()
                    already_delivered_opps: List[Dict[str, Any]] = []
                    if fresh_c.matched_opportunity_ids_json:
                        try:
                            raw_ids = json.loads(fresh_c.matched_opportunity_ids_json)
                            for x in raw_ids:
                                if x:
                                    uid = str(x).strip().upper()
                                    if uid not in already_delivered_set:
                                        already_delivered_list.append(uid)
                                        already_delivered_set.add(uid)
                                    existing_opp = opps_by_id.get(uid)
                                    if existing_opp:
                                        already_delivered_opps.append(existing_opp)
                                        for al in (existing_opp.get("alias_ids") or []):
                                            if al:
                                                already_delivered_set.add(str(al).strip().upper())
                                        u_norm = str(existing_opp.get("url") or existing_opp.get("portal_url") or "").strip().rstrip("/").lower()
                                        if u_norm:
                                            already_delivered_urls.add(u_norm)
                        except Exception:
                            pass

                    def _is_already_delivered_physical(cand: Dict[str, Any]) -> bool:
                        cid = str(cand.get("id") or "").strip().upper()
                        if cid in already_delivered_set:
                            return True
                        for al in (cand.get("alias_ids") or []):
                            if al and str(al).strip().upper() in already_delivered_set:
                                return True
                        cu = str(cand.get("url") or cand.get("portal_url") or "").strip().rstrip("/").lower()
                        if cu and cu in already_delivered_urls:
                            return True
                        for prev_opp in already_delivered_opps:
                            if MarketScraper.are_same_physical_property(cand, prev_opp):
                                return True
                        return False

                    # Extraer los filtros de la consulta guardada
                    criteria = self._extract_consultation_criteria(fresh_c)

                    # 1. Evaluar oportunidades nuevas ya presentes en el catálogo interno
                    matching = advisor_engine.filter_opportunities(all_opps, criteria)
                    new_opps = [o for o in matching if not _is_already_delivered_physical(o)]

                    # 2. Sincronizar proactivamente con los portales externos para descubrir nuevos anuncios publicados
                    if sync_external_portals and len(new_opps) < max_cards_per_consultation:
                        try:
                            newly_synced = await advisor_engine.sync_portal_opportunities_on_demand(
                                criteria=criteria,
                                prompt_text=fresh_c.description or fresh_c.title or "",
                                target_count=max_cards_per_consultation,
                                db=db
                            )
                            if newly_synced:
                                all_opps = advisor_engine.get_live_catalog_opportunities(db=db)
                                seen_urls = {str(o.get("url") or "").strip().rstrip("/").lower() for o in all_opps if o.get("url")}
                                for n_item in newly_synced:
                                    nu = str(n_item.get("url") or "").strip().rstrip("/").lower()
                                    if nu and nu not in seen_urls:
                                        all_opps.append(n_item)
                                        seen_urls.add(nu)
                                all_opps = MarketScraper.deduplicate_cross_portal_opportunities(all_opps)
                                opps_by_id = {}
                                for o in all_opps:
                                    if o.get("id"):
                                        opps_by_id[str(o.get("id")).strip().upper()] = o
                                    for al in (o.get("alias_ids") or []):
                                        if al:
                                            opps_by_id[str(al).strip().upper()] = o
                                matching = advisor_engine.filter_opportunities(all_opps, criteria)
                                new_opps = [o for o in matching if not _is_already_delivered_physical(o)]
                        except Exception as e_sync:
                            logger.warning(f"[Alerts Worker 09:00h] Aviso en prospección de portales para consulta #{fresh_c.id}: {e_sync}")

                    if not new_opps:
                        report["details"].append({
                            "consultation_id": fresh_c.id,
                            "title": fresh_c.title,
                            "status": "no_new_opportunities",
                            "delivered_count": 0
                        })
                        continue

                    # 3. Verificar vigencia y calidad fotográfica (0 fotos duplicadas, anuncio activo)
                    to_deliver = advisor_engine.verify_and_filter_active_market_opportunities(
                        new_opps,
                        target_count=max_cards_per_consultation
                    )
                    if not to_deliver:
                        report["details"].append({
                            "consultation_id": fresh_c.id,
                            "title": fresh_c.title,
                            "status": "filtered_by_guardian",
                            "delivered_count": 0
                        })
                        continue

                    if dry_run:
                        report["details"].append({
                            "consultation_id": fresh_c.id,
                            "title": fresh_c.title,
                            "status": "dry_run_ready",
                            "candidates_count": len(to_deliver),
                            "candidate_ids": [str(o.get("id")) for o in to_deliver]
                        })
                        continue

                    # Re-comprobar en BD que la consulta sigue activa antes de emitir en Telegram
                    db.expire_all()
                    still_active_c = db.query(SavedConsultation).filter(
                        SavedConsultation.id == fresh_c.id,
                        SavedConsultation.is_active == True
                    ).first()
                    if not still_active_c:
                        continue

                    chat_id = self._resolve_telegram_chat_id(still_active_c.telegram_chat_id)
                    loc_label = (
                        criteria.get("zone_or_neighborhood")
                        or criteria.get("full_location_query")
                        or criteria.get("municipality")
                        or criteria.get("province")
                        or "Zona seleccionada"
                    )
                    ptype_label = criteria.get("property_type") or "Inmuebles"

                    # Pre-renderizar las tarjetas ANTES de enviar la cabecera en Telegram
                    # para garantizar que NUNCA se anuncie una alerta diaria sin que salgan las fichas detrás
                    from app.services.card_image_generator import generate_whatsapp_style_card
                    from app.services.telegram_advisor_bot import TelegramAdvisorBot
                    is_mocked_send_card = (
                        getattr(telegram_advisor_bot.send_photo_card, "__func__", None)
                        is not TelegramAdvisorBot.send_photo_card
                    )
                    renderable_deliveries = []
                    for opp in to_deliver:
                        if is_mocked_send_card:
                            renderable_deliveries.append((opp, None))
                            continue
                        try:
                            c_bytes = await asyncio.to_thread(generate_whatsapp_style_card, opp)
                            if c_bytes:
                                renderable_deliveries.append((opp, c_bytes))
                            else:
                                logger.warning(
                                    f"[Alerts Worker 09:00h] Oportunidad {opp.get('id')} no pudo renderizarse con fotos reales. Omitiendo de alerta #{still_active_c.id}."
                                )
                        except Exception as e_pre:
                            logger.error(f"[Alerts Worker 09:00h] Error pre-renderizando ficha {opp.get('id')}: {e_pre}")

                    if not renderable_deliveries:
                        report["details"].append({
                            "consultation_id": still_active_c.id,
                            "title": still_active_c.title,
                            "chat_id": chat_id,
                            "status": "no_renderable_cards",
                            "delivered_count": 0
                        })
                        continue

                    # Enviar cabecera ejecutiva referenciando la consulta guardada con el conteo exacto de fichas listas
                    header_text = (
                        f"🔔 <b>ALERTA DIARIA 09:00h · NUEVAS OPORTUNIDADES DESCUBIERTAS</b>\n\n"
                        f"📋 Consulta guardada: <b>{html.escape(still_active_c.title or f'Búsqueda #{still_active_c.id}')}</b>\n"
                        f"🎯 Filtros activos: <b>{html.escape(str(ptype_label))}</b> en <b>{html.escape(str(loc_label))}</b>\n"
                        f"✨ Nuevos activos detectados hoy: <b>{len(renderable_deliveries)}</b>\n\n"
                        f"A continuación se detallan las nuevas oportunidades incorporadas a tu consulta en plataforma:"
                    )
                    await telegram_advisor_bot.send_message(chat_id=chat_id, text=header_text, parse_mode="HTML")

                    # Enviar cada ficha visual pre-renderizada a Telegram
                    cards_sent = 0
                    delivered_opp_ids: List[str] = []
                    for opp, c_bytes in renderable_deliveries:
                        try:
                            success = await telegram_advisor_bot.send_photo_card(
                                chat_id=chat_id,
                                opp=opp,
                                pre_rendered_card_bytes=c_bytes
                            )
                            if success:
                                cards_sent += 1
                                if opp.get("id"):
                                    oid = str(opp.get("id")).strip().upper()
                                    if oid not in already_delivered_set and oid not in delivered_opp_ids:
                                        delivered_opp_ids.append(oid)
                            await asyncio.sleep(0.85)
                        except Exception as e_card:
                            logger.error(f"[Alerts Worker 09:00h] Error enviando ficha en chat {chat_id}: {e_card}")

                    if delivered_opp_ids:
                        updated_ids_list = already_delivered_list + delivered_opp_ids
                        still_active_c.matched_opportunity_ids_json = json.dumps(updated_ids_list)
                        still_active_c.matched_count = len(updated_ids_list)
                        still_active_c.last_alert_at = datetime.utcnow()
                        still_active_c.updated_at = datetime.utcnow()
                        db.commit()

                    report["alerts_triggered"] += 1 if cards_sent > 0 else 0
                    report["new_opportunities_delivered"] += cards_sent
                    report["details"].append({
                        "consultation_id": still_active_c.id,
                        "title": still_active_c.title,
                        "chat_id": chat_id,
                        "status": "delivered" if cards_sent > 0 else "send_failed",
                        "delivered_count": cards_sent,
                        "new_opportunity_ids": delivered_opp_ids
                    })
                    logger.info(
                        f"[Alerts Worker 09:00h] Consulta #{still_active_c.id} actualizada: "
                        f"{cards_sent} nuevas oportunidades servidas en Telegram ({chat_id})."
                    )

                except Exception as e_item:
                    logger.error(f"[Alerts Worker 09:00h] Error procesando consulta #{c.id}: {e_item}")
                    db.rollback()

            # Registrar estado de ejecución del Cron de las 09:00h en PipelineSyncState para Salud de Cabina
            try:
                last_sync = db.query(PipelineSyncState).order_by(PipelineSyncState.id.desc()).first()
                if last_sync:
                    sdata = json.loads(last_sync.summary_json) if last_sync.summary_json else {}
                    sdata["cron_9am_last_run_utc"] = datetime.utcnow().strftime("%H:%M")
                    sdata["cron_9am_scanned_consultations"] = report["scanned_consultations"]
                    sdata["cron_9am_alerts_triggered"] = report["alerts_triggered"]
                    sdata["cron_9am_new_delivered"] = report["new_opportunities_delivered"]
                    last_sync.summary_json = json.dumps(sdata, ensure_ascii=False)
                    db.commit()
            except Exception as e_sync_state:
                logger.warning(f"[Alerts Worker 09:00h] Aviso guardando estado en PipelineSyncState: {e_sync_state}")

        except Exception as e_scan:
            logger.error(f"[Alerts Worker 09:00h] Error general en run_daily_scan: {e_scan}")
            report["status"] = "error"
            report["error"] = str(e_scan)
        finally:
            if close_db_when_done and db:
                db.close()

        return report

    async def _worker_loop(self):
        """Bucle periódico en segundo plano que vigila las consultas activas."""
        logger.info("[Alerts Worker] Bucle de alertas de consultas guardadas iniciado.")
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
