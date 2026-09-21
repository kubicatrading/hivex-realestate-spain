import os
import re
import math
import httpx
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import PipelineSyncState
from app.connectors.market_scraper import MarketScraper
from app.connectors.pgou_scraper import PGOUScraper
from app.connectors.boe_scraper import BOESubastasScraper

logger = logging.getLogger(__name__)

class RealEstateAlertEngine:
    """
    Motor inteligente de alertas de Real Estate para Telegram (24h, 8:00 AM).
    
    Criterios de selección:
    2.1. Mejor oportunidad 'market' de alquiler en Madrid (BTL)
    2.2. Mejor oportunidad 'market' de house flipping en Madrid
    2.3. Mejor oportunidad 'market' de alquiler/house flipping con sinergia PGOU
    2.4. Mejor oportunidad 'market' solar en precio
    2.5. Mejor oportunidad 'market' solar con sinergia PGOU
    
    Look & Feel:
    Título: Alertas Oportunidades - 24h
    BTL: [Dirección completa incluida la provincia](PLATFORM_URL/?opp_id=...)
    House Flipping: [Dirección completa incluida la provincia](PLATFORM_URL/?opp_id=...)
    Solar: [Dirección del solar + provincia](PLATFORM_URL/?opp_id=...)
    House Flipping PGOU: [Dirección del inmueble + provincia](PLATFORM_URL/?opp_id=...)
    Solar PGOU: [Dirección del inmueble + provincia](PLATFORM_URL/?opp_id=...)
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        base_url: Optional[str] = None
    ):
        self.bot_token = bot_token or getattr(settings, "TELEGRAM_BOT_TOKEN", None) or os.environ.get("TELEGRAM_BOT_TOKEN", "8889706886:AAGu97kanMwK9L3d5_7yGXQR-d5ojfYRUHs")
        raw_chat_id = chat_id or getattr(settings, "TELEGRAM_CHAT_ID", None) or os.environ.get("TELEGRAM_CHAT_ID", "-1003904392737")
        self.chat_id = self._normalize_chat_id(str(raw_chat_id))
        self.base_url = (base_url or getattr(settings, "PLATFORM_BASE_URL", None) or os.environ.get("PLATFORM_BASE_URL", "https://hivex-realestate-spain.vercel.app")).rstrip("/")

    @staticmethod
    def _normalize_chat_id(chat_id: str) -> str:
        """Normaliza el ID de supergrupo para la API de Telegram anteponiendo -100 si es necesario."""
        cid = str(chat_id).strip()
        if cid.startswith("-") and not cid.startswith("-100"):
            return f"-100{cid[1:]}"
        return cid

    @staticmethod
    def _format_address_with_province(opp: Dict[str, Any]) -> str:
        """Genera el texto amigable de dirección con provincia para el link."""
        address = (opp.get("address") or opp.get("title") or "Inmueble").strip()
        locality = (opp.get("locality") or "").strip()
        province = (opp.get("province") or "").strip()

        # Evitar duplicaciones tipo "Madrid, Madrid (Madrid)"
        parts = []
        if address:
            parts.append(address)
        if locality and locality.lower() not in address.lower():
            parts.append(locality)
        
        main_addr = ", ".join(parts)
        if province:
            if province.lower() not in main_addr.lower():
                return f"{main_addr} ({province})"
            return main_addr
        return main_addr or "Inmueble Seleccionado"

    def select_top_opportunities(
        self,
        market_items: List[Dict[str, Any]],
        pgou_items: Optional[List[Dict[str, Any]]] = None,
        db: Optional[Session] = None,
        force_all: bool = False
    ) -> Dict[str, Dict[str, Any]]:
        """
        Selecciona las oportunidades ganadoras para cada uno de los 5 disparadores.
        Aplica deduplicación para enviar únicamente las que no se hayan alertado recientemente,
        a menos que force_all sea True (p. ej. disparador manual de prueba).
        """
        # Cargar historial de IDs alertados en los últimos 7 días
        already_alerted_ids = set()
        if db and not force_all:
            try:
                # Consultar en PipelineSyncState
                syncs = db.query(PipelineSyncState).order_by(PipelineSyncState.id.desc()).limit(14).all()
                for s in syncs:
                    if s.summary_json:
                        import json
                        sdata = json.loads(s.summary_json)
                        already_alerted_ids.update(sdata.get("alerted_telegram_opp_ids", []))
            except Exception as e_hist:
                logger.warning(f"Aviso consultando historial de alertas: {e_hist}")

        # Excluir cualquier oportunidad de naves (solo inmuebles residenciales y solares)
        market_items = [
            it for it in market_items
            if not BOESubastasScraper.is_nave(
                title=it.get("title", ""),
                desc=it.get("description", ""),
                property_type=it.get("property_type", "")
            )
        ]

        results: Dict[str, Dict[str, Any]] = {}

        # 1. 2.1. Mejor oportunidad 'market' de alquiler en Madrid (BTL)
        btl_madrid_candidates = [
            it for it in market_items
            if ("madrid" in (it.get("province") or "").lower() or "madrid" in (it.get("locality") or "").lower())
            and it.get("strategy") != "LAND_DEVELOPMENT"
            and not any(k in (it.get("property_type") or "").lower() for k in ["solar", "terreno", "suelo", "parcela"])
            and (it.get("btl_score") is not None or (it.get("rental_yield") or 0.0) > 0)
        ]
        btl_madrid_candidates.sort(
            key=lambda x: (x.get("btl_score") or 0.0, x.get("rental_yield") or 0.0, x.get("overall_score") or 0.0),
            reverse=True
        )
        for c in btl_madrid_candidates:
            if force_all or c["id"] not in already_alerted_ids:
                results["BTL"] = c
                break

        # 2. 2.3. Mejor oportunidad 'market' de alquiler/house flipping con sinergia PGOU
        flipping_pgou_candidates = [
            it for it in market_items
            if it.get("has_pgou_synergy")
            and it.get("strategy") != "LAND_DEVELOPMENT"
            and not any(k in (it.get("property_type") or "").lower() for k in ["solar", "terreno", "suelo", "parcela"])
        ]
        flipping_pgou_candidates.sort(
            key=lambda x: (x.get("overall_score") or 0.0, x.get("discount_vs_market") or 0.0),
            reverse=True
        )
        for c in flipping_pgou_candidates:
            if force_all or c["id"] not in already_alerted_ids:
                results["House Flipping PGOU"] = c
                break

        # 3. 2.2. Mejor oportunidad 'market' de house flipping en Madrid (diferente a PGOU)
        flipping_madrid_candidates = [
            it for it in market_items
            if ("madrid" in (it.get("province") or "").lower() or "madrid" in (it.get("locality") or "").lower())
            and it.get("strategy") == "HOUSE_FLIPPING"
            and not any(k in (it.get("property_type") or "").lower() for k in ["solar", "terreno", "suelo", "parcela"])
        ]
        flipping_madrid_candidates.sort(
            key=lambda x: (
                x.get("overall_score") or 0.0,
                x.get("potential_gross_profit") or 0.0,
                x.get("discount_vs_market") or x.get("discount_percentage") or 0.0
            ),
            reverse=True
        )
        for c in flipping_madrid_candidates:
            assigned_ids = {results.get("BTL", {}).get("id"), results.get("House Flipping PGOU", {}).get("id")}
            if (force_all or c["id"] not in already_alerted_ids) and (c["id"] not in assigned_ids or len(flipping_madrid_candidates) <= len(assigned_ids)):
                results["House Flipping"] = c
                break

        # 4. 2.4. Mejor oportunidad solar / suelo en Market (o activo con mayor potencial de transformación)
        solar_candidates = [
            it for it in market_items
            if it.get("strategy") == "LAND_DEVELOPMENT"
            or any(k in (it.get("property_type") or "").lower() for k in ["solar", "terreno", "suelo", "parcela"])
        ]
        # Ordenar por menor €/m² (>0), o mayor descuento
        solar_candidates.sort(
            key=lambda x: (
                -(x.get("property_m2_price") or 999999.0) if (x.get("property_m2_price") or 0) > 0 else -999999.0,
                x.get("discount_percentage") or x.get("discount_vs_market") or 0.0
            ),
            reverse=True
        )
        assigned_ids = {v.get("id") for v in results.values() if v.get("id")}
        for c in solar_candidates:
            if (force_all or c["id"] not in already_alerted_ids) and c["id"] not in assigned_ids:
                results["Solar"] = c
                break

        # Si aún no hay solares específicos en Market, seleccionar el siguiente activo de mayor descuento en Market
        if "Solar" not in results:
            market_high_discount = [
                it for it in market_items
                if it.get("id") not in assigned_ids
            ]
            market_high_discount.sort(
                key=lambda x: (x.get("discount_percentage") or x.get("discount_vs_market") or 0.0, x.get("overall_score") or 0.0),
                reverse=True
            )
            for c in market_high_discount:
                if force_all or c["id"] not in already_alerted_ids:
                    results["Solar"] = c
                    break

        # 5. 2.5. Oportunidad con Sinergia PGOU en Market (Solar o Inmueble en zona de desarrollo PGOU)
        # REGLA DE ORO HIVEX: Siempre circunscrito a la pestaña Market, NUNCA a planeamientos urbanísticos de la pestaña PGOU
        assigned_ids = {v.get("id") for v in results.values() if v.get("id")}
        solar_pgou_candidates = [
            it for it in market_items
            if it.get("has_pgou_synergy")
            and (
                it.get("strategy") == "LAND_DEVELOPMENT"
                or any(k in (it.get("property_type") or "").lower() for k in ["solar", "terreno", "suelo", "parcela"])
            )
            and it.get("id") not in assigned_ids
        ]
        solar_pgou_candidates.sort(
            key=lambda x: (x.get("overall_score") or 0.0, x.get("discount_percentage") or 0.0),
            reverse=True
        )
        for c in solar_pgou_candidates:
            if (force_all or c["id"] not in already_alerted_ids) and c["id"] not in assigned_ids:
                results["Solar PGOU"] = c
                break

        # Si no hay un solar con sinergia PGOU en Market, seleccionar el siguiente inmueble de Market con sinergia PGOU
        if "Solar PGOU" not in results:
            other_pgou_candidates = [
                it for it in market_items
                if it.get("has_pgou_synergy")
                and it.get("id") not in assigned_ids
            ]
            other_pgou_candidates.sort(
                key=lambda x: (x.get("overall_score") or 0.0, x.get("discount_vs_market") or 0.0),
                reverse=True
            )
            for c in other_pgou_candidates:
                if (force_all or c["id"] not in already_alerted_ids) and c["id"] not in assigned_ids:
                    results["Solar PGOU"] = c
                    break

        return results

    def build_alert_message(self, selected_opps: Dict[str, Dict[str, Any]]) -> str:
        """
        Construye el mensaje formateado con el Look & Feel exacto requerido:
        
        Alertas Oportunidades - 24h
        BTL: [link con dirección completa incluida la provincia](PLATFORM_URL/?opp_id=...)
        House Flipping: [link con dirección completa incluida la provincia](PLATFORM_URL/?opp_id=...)
        Solar: [link con dirección solar + provincia](PLATFORM_URL/?opp_id=...)
        House Flipping PGOU: [link con dirección inmueble + provincia](PLATFORM_URL/?opp_id=...)
        Solar PGOU: [link con dirección inmueble + provincia](PLATFORM_URL/?opp_id=...)
        """
        if not selected_opps:
            return ""

        lines = ["🔔 *Alertas Oportunidades - 24h*", ""]

        order = [
            ("BTL", "🏢"),
            ("House Flipping", "🔨"),
            ("Solar", "🏗️"),
            ("House Flipping PGOU", "🎯"),
            ("Solar PGOU", "📐")
        ]

        for key, icon in order:
            if key in selected_opps:
                opp = selected_opps[key]
                opp_id = opp.get("id")
                friendly_text = self._format_address_with_province(opp)
                # Escapar corchetes en el texto amigable para no romper Markdown
                safe_text = friendly_text.replace("[", "(").replace("]", ")")
                deep_link = f"{self.base_url}/?opp_id={opp_id}"

                # Métricas adicionales breves y útiles
                extra_info = ""
                if key == "BTL":
                    yield_val = opp.get("rental_yield") or 0.0
                    btl_score = opp.get("btl_score")
                    extra_info = f" • Yield: *{yield_val:.2f}%*" if yield_val > 0 else ""
                    if btl_score is not None:
                        extra_info += f" ({btl_score:.0f} pts)"
                elif key == "House Flipping":
                    dto = opp.get("discount_vs_market") or opp.get("discount_percentage") or 0.0
                    profit = opp.get("potential_gross_profit")
                    extra_info = f" • Dto: *{dto:.1f}%*"
                    if profit and profit > 0:
                        extra_info += f" (+{profit:,.0f} €)".replace(",", ".")
                elif key == "Solar":
                    m2_price = opp.get("property_m2_price")
                    surface = opp.get("surface_m2")
                    if m2_price and m2_price > 0:
                        extra_info = f" • *{m2_price:,.0f} €/m²*".replace(",", ".")
                    if surface and surface > 0:
                        extra_info += f" ({surface:,.0f} m²)".replace(",", ".")
                elif "PGOU" in key:
                    pgou_title = opp.get("pgou_title") or "Ámbito PGOU"
                    uplift = opp.get("pgou_uplift") or ""
                    extra_info = f" • Sinergia: _{pgou_title[:28]}_"
                    if uplift:
                        extra_info += f" ({uplift.split()[0]})"

                # Enlace directo contrastado al portal inmobiliario (Idealista, Fotocasa, BOE...)
                portal_url = opp.get("portal_url") or opp.get("boe_url")
                portal_name = opp.get("primary_portal") or ("Idealista" if "idealista" in str(portal_url).lower() else "Portal")
                direct_portal_badge = f" • [{portal_name} ↗]({portal_url})" if portal_url else ""

                lines.append(f"{icon} *{key}:* [{safe_text}]({deep_link}){extra_info}{direct_portal_badge}")

        return "\n".join(lines)

    def send_alert(self, message: str) -> bool:
        """Envía el mensaje Markdown a través de la API oficial de Telegram."""
        if not message.strip():
            logger.info("No hay oportunidades nuevas que alertar hoy.")
            return False

        if not self.bot_token or not self.chat_id:
            logger.warning("TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no configurados. Alerta mostrada en logs.")
            logger.info(f"\n--- MENSAJE TELEGRAM (SIMULADO) ---\n{message}\n-----------------------------------")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False
        }

        try:
            resp = httpx.post(url, json=payload, timeout=12.0)
            if resp.status_code == 200:
                logger.info(f"Alerta diaria de oportunidades enviada exitosamente a Telegram ({self.chat_id}).")
                return True
            else:
                logger.error(f"Error enviando alerta Telegram: {resp.status_code} - {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Excepción al enviar alerta a Telegram: {e}")
            return False

    def run_daily_alert_check(
        self,
        db: Optional[Session] = None,
        force_all: bool = False
    ) -> Dict[str, Any]:
        """
        Ejecución orquestada del servicio de alertas diarias:
        1. Carga oportunidades de Market y PGOU.
        2. Selecciona las mejores oportunidades por disparador.
        3. Construye el mensaje con los enlaces directos a la ficha.
        4. Envía la alerta a Telegram y registra el estado.
        """
        # Cargar catálogo de mercado y cruzar con PGOU
        market_scraper = MarketScraper()
        market_items = market_scraper.fetch_market_opportunities(live_scrape=False)
        
        pgou_scraper = PGOUScraper()
        pgou_items = pgou_scraper.fetch_pgou_opportunities()
        MarketScraper.cross_reference_with_pgou(market_items, pgou_items)

        selected = self.select_top_opportunities(market_items, pgou_items=pgou_items, db=db, force_all=force_all)
        if not selected:
            return {
                "status": "skipped",
                "message": "No hay nuevas oportunidades elegibles en las últimas 24h.",
                "selected_count": 0
            }

        msg = self.build_alert_message(selected)
        sent = self.send_alert(msg)

        # Registrar IDs alertados
        alerted_ids = [opp["id"] for opp in selected.values()]
        if db and sent:
            try:
                sync_rec = db.query(PipelineSyncState).order_by(PipelineSyncState.id.desc()).first()
                if sync_rec and sync_rec.summary_json:
                    import json
                    sdata = json.loads(sync_rec.summary_json)
                    curr_alerted = set(sdata.get("alerted_telegram_opp_ids", []))
                    curr_alerted.update(alerted_ids)
                    sdata["alerted_telegram_opp_ids"] = list(curr_alerted)
                    sync_rec.summary_json = json.dumps(sdata)
                    db.commit()
            except Exception as e_reg:
                logger.warning(f"Aviso registrando IDs alertados en DB: {e_reg}")

        return {
            "status": "sent" if sent else "failed",
            "message": msg,
            "selected_categories": list(selected.keys()),
            "alerted_ids": alerted_ids
        }

# Alias de compatibilidad
AlertEngine = RealEstateAlertEngine
