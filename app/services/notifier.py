import json
import html
import httpx
import logging
from typing import Optional, Dict, Any, List
from app.db.models import Opportunity
from app.core.config import settings

logger = logging.getLogger(__name__)

class TelegramNotifier:
    """
    Servicio de alertas instantáneas a Telegram para enviar oportunidades de inversión
    formateadas como fichas visuales con fotografía y botones interactivos.
    """

    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        self.token = token or settings.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or settings.TELEGRAM_CHAT_ID
        self.platform_url = settings.PLATFORM_BASE_URL.rstrip("/")

    def send_opportunity_alert(self, opp: Opportunity) -> bool:
        """
        Envía una ficha visual con foto y botones de acción a Telegram con los detalles de la oportunidad.
        Si la foto no carga, realiza fallback automático a mensaje HTML.
        """
        auction = opp.auction
        discount_pct_display = round(opp.discount_percentage * 100, 1)
        gross_profit = opp.estimated_reference_value - opp.listing_price

        strategy_label = "Flipping" if opp.strategy == "HOUSE_FLIPPING" else "Suelo / PGOU"
        title = html.escape(auction.title or "Inmueble Detectado")
        loc = html.escape(auction.locality or "España")
        prov = html.escape(auction.province or "España")
        addr = html.escape(auction.address or loc)
        surf = float(getattr(auction, "surface_m2", None) or 80.0)

        price = float(opp.listing_price or 0.0)
        ref_val = float(opp.estimated_reference_value or price)
        disc_str = f"-{discount_pct_display:.1f}%" if discount_pct_display > 0 else f"+{abs(discount_pct_display):.1f}%"

        ryield = float(getattr(opp, "rental_yield", 0.0) or 0.0)
        rent = float(getattr(opp, "estimated_monthly_rent", 0.0) or 0.0)
        score = float(opp.overall_score or 80.0)
        portal = html.escape(str(auction.source or "BOE Subastas").upper())

        web_link = f"{self.platform_url}/?opp_id={opp.id}"
        boe_url = f"https://subastas.boe.es/detalleSubasta.php?idSub={auction.id_subasta}"

        lines = [
            f"🚨 <b>¡NUEVA OPORTUNIDAD ENCONTRADA!</b>\n",
            f"🏡 <b>{title}</b>",
            f"📍 <i>{addr}, {loc} ({prov}) • {surf:.0f} m²</i>\n",
            f"💰 <b>Precio Salida:</b> {price:,.0f} €  <code>({disc_str} s/ Ref: {ref_val:,.0f} €)</code>",
        ]

        if ryield > 0 or rent > 0:
            lines.append(f"📈 <b>Rentabilidad BTL:</b> <b>{ryield:.1f}% Yield</b> (Est. <b>{rent:,.0f} €/mes</b>)")

        lines.extend([
            f"⭐ <b>HIVEX Score:</b> <b>{score:.0f}/100</b> | 🏷️ <b>{strategy_label}</b>",
            f"💶 <b>Margen Bruto:</b> <b>+{gross_profit:,.0f} €</b>",
            f"🛒 <b>Fuente:</b> {portal}  <code>({auction.id_subasta})</code>"
        ])

        card_html = "\n".join(lines)

        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "🔍 Ver Ficha Completa", "url": web_link},
                    {"text": "🌐 Portal Origen", "url": boe_url}
                ]
            ]
        }

        if not self.token or not self.chat_id:
            logger.warning("TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no configurados. Alerta mostrada en logs.")
            return False

        # Extraer imagen principal si existe en images_json
        first_photo = None
        if getattr(auction, "images_json", None):
            try:
                imgs = json.loads(auction.images_json)
                if isinstance(imgs, list) and imgs and imgs[0]:
                    first_photo = str(imgs[0])
            except Exception:
                pass

        if not first_photo:
            # Fallback a CDN residencial
            first_photo = "https://img4.idealista.com/blur/WEB_DETAIL-XL-L/0/id.pro.es.image.master/0a/08/72/1347770919.jpg"

        if first_photo and str(first_photo).startswith("http"):
            photo_url = f"https://api.telegram.org/bot{self.token}/sendPhoto"
            payload = {
                "chat_id": self.chat_id,
                "photo": first_photo,
                "caption": card_html,
                "parse_mode": "HTML",
                "reply_markup": reply_markup
            }
            try:
                resp = httpx.post(photo_url, json=payload, timeout=20.0)
                if resp.status_code == 200:
                    logger.info(f"Ficha visual con foto enviada exitosamente para subasta {auction.id_subasta}")
                    return True
                else:
                    logger.warning(f"sendPhoto falló ({resp.status_code}: {resp.text}). Reintentando como mensaje HTML...")
            except Exception as e_photo:
                logger.warning(f"Excepción en sendPhoto: {e_photo}")

        # Fallback a sendMessage con HTML y botones
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": card_html,
                "parse_mode": "HTML",
                "reply_markup": reply_markup,
                "disable_web_page_preview": False
            }
            resp = httpx.post(url, json=payload, timeout=15.0)
            if resp.status_code == 200:
                logger.info(f"Alerta HTML enviada exitosamente para la subasta {auction.id_subasta}")
                return True
            else:
                logger.error(f"Error enviando Telegram alert: {resp.status_code} - {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Excepción al enviar Telegram alert: {e}")
            return False
