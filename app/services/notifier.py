import httpx
import logging
from typing import Optional
from app.db.models import Opportunity
from app.core.config import settings

logger = logging.getLogger(__name__)

class TelegramNotifier:
    """
    Servicio de alertas instantáneas a Telegram para enviar oportunidades de inversión.
    """

    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        self.token = token or settings.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or settings.TELEGRAM_CHAT_ID

    def send_opportunity_alert(self, opp: Opportunity) -> bool:
        """
        Envía un mensaje formateado en Markdown a Telegram con los detalles de la oportunidad.
        """
        auction = opp.auction
        discount_pct_display = round(opp.discount_percentage * 100, 1)
        gross_profit = opp.estimated_reference_value - opp.listing_price

        strategy_emoji = "🔨" if opp.strategy == "HOUSE_FLIPPING" else "🏗️"
        strategy_label = "Vivienda (Flipping)" if opp.strategy == "HOUSE_FLIPPING" else "Suelo / Solar"

        message = (
            f"🚨 **¡NUEVA OPORTUNIDAD ENCONTRADA!** 🚨\n\n"
            f"{strategy_emoji} **Estrategia:** {strategy_label}\n"
            f"📍 **Ubicación:** {auction.locality or 'N/D'}, {auction.province or 'N/D'}\n"
            f"🏢 **Inmueble:** {auction.title}\n"
            f"📑 **ID Subasta:** `{auction.id_subasta}`\n\n"
            f"💰 **Precio Salida (BOE):** {opp.listing_price:,.0f} €\n"
            f"📊 **Valor Estimado Zona:** {opp.estimated_reference_value:,.0f} €\n"
            f"🔥 **Descuento Detectado:** {discount_pct_display}% !!\n"
            f"💵 **Margen Bruto Teórico:** {gross_profit:,.0f} €\n\n"
            f"🌟 **Score Global:** {opp.overall_score} / 100\n"
            f"🏫 **Score Servicios (OSM):** {opp.poi_score} / 100\n\n"
            f"🔗 [Ver Subasta en Portal BOE](https://subastas.boe.es/detalleSubasta.php?idSub={auction.id_subasta})\n"
        )

        logger.info(f"--- ALERTA HIVEX REAL ESTATE ---\n{message}\n--------------------------------")

        if not self.token or not self.chat_id:
            logger.warning("TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no configurados. Alerta mostrada en logs.")
            return False

        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False
            }
            resp = httpx.post(url, json=payload, timeout=10.0)
            if resp.status_code == 200:
                logger.info(f"Alerta de Telegram enviada exitosamente para la subasta {auction.id_subasta}")
                return True
            else:
                logger.error(f"Error enviando Telegram alert: {resp.status_code} - {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Excepción al enviar Telegram alert: {e}")
            return False
