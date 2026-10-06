"""
HIVEX Telegram Conversational Real Estate Advisor Service
Gestiona la recepción de mensajes de texto y notas de voz, autenticación de usuarios,
interacción conversacional y ejecución del motor asesor inmobiliario.
"""

import os
import re
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.db.models import User, TelegramConversationMessage
from app.engine.advisor_engine import advisor_engine

logger = logging.getLogger(__name__)

VERIFIED_REAL_ESTATE_PHOTOS = [
    "https://images.unsplash.com/photo-1560518883-ce09059eeffa?w=800&q=80",
    "https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?w=800&q=80",
    "https://images.unsplash.com/photo-1512917774080-9991f1c4c750?w=800&q=80",
    "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?w=800&q=80",
    "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?w=800&q=80",
    "https://images.unsplash.com/photo-1502672260266-1c1ef2d93688?w=800&q=80",
    "https://images.unsplash.com/photo-1560448204-e02f11c3d0e2?w=800&q=80",
    "https://images.unsplash.com/photo-1484154218962-a197022b5858?w=800&q=80",
    "https://images.unsplash.com/photo-1502005229762-ae1b46642b58?w=800&q=80",
    "https://images.unsplash.com/photo-1570129477492-45c003edd2be?w=800&q=80"
]

class TelegramAdvisorBot:
    """
    Bot conversacional de Telegram para HIVEX Real Estate.
    Funciona como Asesor Inmobiliario, verifica identidad de usuarios,
    transcribe notas de voz y ejecuta consultas guardándolas en BD.
    """

    def __init__(self, token: Optional[str] = None):
        self.token = token or settings.TELEGRAM_BOT_TOKEN or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.api_base = f"https://api.telegram.org/bot{self.token}"
        self.authorized_env_users = [
            u.strip().lower() for u in (settings.TELEGRAM_AUTHORIZED_USERS or os.getenv("TELEGRAM_AUTHORIZED_USERS", "")).split(",")
            if u.strip()
        ]
        self.platform_url = getattr(settings, "PLATFORM_BASE_URL", "https://hivex-realestate-spain.vercel.app").rstrip("/")
        self._polling_task: Optional[asyncio.Task] = None
        self._is_polling = False
        self._processed_message_ids = set()
        self._cached_opportunities: Dict[str, Dict[str, Any]] = {}
        self._load_catalog_cache()

    # --------------------------------------------------------------------------
    # 1. VERIFICACIÓN Y VINCULACIÓN DE USUARIOS
    # --------------------------------------------------------------------------
    def verify_or_link_user(
        self,
        db: Session,
        telegram_user_id: int,
        telegram_username: Optional[str] = None,
        first_name: Optional[str] = None,
        command_args: Optional[str] = None
    ) -> Tuple[bool, Optional[User], str]:
        """
        Verifica si el usuario de Telegram está autorizado en la plataforma HIVEX.
        La autorización se gestiona exclusivamente por el administrador en la plataforma
        (mediante User.telegram_id, User.telegram_username o lista autorizada en variables de entorno).
        """
        str_tg_id = str(telegram_user_id)
        tg_user_clean = (telegram_username or "").lower().lstrip("@")

        # 1. Búsqueda por telegram_id ya registrado en BD por el administrador
        user = db.query(User).filter(User.telegram_id == str_tg_id).first()
        if user and user.is_active:
            return True, user, f"Usuario autenticado por ID de Telegram ({user.username})"

        # 2. Búsqueda por username coincidente en BD registrado por el administrador
        if tg_user_clean:
            user = db.query(User).filter(
                (User.telegram_username.ilike(tg_user_clean)) |
                (User.username.ilike(tg_user_clean))
            ).first()
            if user and user.is_active:
                # Auto-asociar telegram_id
                user.telegram_id = str_tg_id
                user.telegram_username = tg_user_clean
                db.commit()
                return True, user, f"Usuario vinculado automáticamente por username ({user.username})"

        # 3. Comprobación en lista autorizada de variables de entorno
        if (str_tg_id in self.authorized_env_users) or (tg_user_clean and tg_user_clean in self.authorized_env_users):
            admin_user = db.query(User).filter(User.is_active == True).first()
            if admin_user:
                admin_user.telegram_id = str_tg_id
                admin_user.telegram_username = tg_user_clean
                db.commit()
                return True, admin_user, "Usuario autorizado por configuración de entorno"

        return False, None, "Usuario no identificado en HIVEX"

    # --------------------------------------------------------------------------
    # 2. DESCARGA DE AUDIO / NOTA DE VOZ DESDE TELEGRAM
    # --------------------------------------------------------------------------
    async def download_telegram_file(self, file_id: str) -> Optional[bytes]:
        """Descarga el binario de audio de una nota de voz mediante la API de Telegram."""
        if not self.token:
            return None
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                # 1. Obtener file_path
                res = await client.get(f"{self.api_base}/getFile?file_id={file_id}")
                if res.status_code != 200:
                    logger.error(f"Error getFile Telegram: {res.text}")
                    return None
                file_path = res.json().get("result", {}).get("file_path")
                if not file_path:
                    return None

                # 2. Descargar archivo
                download_url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
                file_res = await client.get(download_url)
                if file_res.status_code == 200:
                    return file_res.content
                else:
                    logger.error(f"Error descargando archivo Telegram: {file_res.status_code}")
                    return None
        except Exception as e:
            logger.error(f"Excepción descargando audio de Telegram: {e}")
            return None

    # --------------------------------------------------------------------------
    # 3. ENVÍO DE MENSAJES A TELEGRAM
    # --------------------------------------------------------------------------
    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str = "Markdown",
        reply_to_message_id: Optional[int] = None,
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Envía un mensaje de texto a un chat o grupo de Telegram."""
        if not self.token:
            logger.warning("TELEGRAM_BOT_TOKEN no configurado. Mensaje no enviado.")
            return False

        # Sanitizar textos para HTML de Telegram evitando que '<' numéricos o entidades rompan el parser
        clean_text = text
        if parse_mode == "HTML":
            clean_text = re.sub(r'<(?!(?:/?(?:b|i|u|s|code|pre|a)\b))', '&lt;', clean_text)

        url = f"{self.api_base}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": clean_text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": False
        }
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        if reply_markup:
            payload["reply_markup"] = reply_markup

        # Si el mensaje supera 3900 caracteres, dividir en bloques inteligentes
        if len(clean_text) > 3900:
            chunks = []
            current = []
            curr_len = 0
            for line in clean_text.splitlines(keepends=True):
                if curr_len + len(line) > 3800:
                    chunks.append("".join(current))
                    current = [line]
                    curr_len = len(line)
                else:
                    current.append(line)
                    curr_len += len(line)
            if current:
                chunks.append("".join(current))

            success = True
            for idx, ch in enumerate(chunks):
                chunk_payload = {
                    "chat_id": chat_id,
                    "text": ch,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": False
                }
                if idx == 0 and reply_to_message_id:
                    chunk_payload["reply_to_message_id"] = reply_to_message_id
                if idx == len(chunks) - 1 and reply_markup:
                    chunk_payload["reply_markup"] = reply_markup

                try:
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        res = await client.post(url, json=chunk_payload)
                        if res.status_code != 200:
                            chunk_payload.pop("parse_mode", None)
                            chunk_payload["text"] = re.sub(r'<[^>]+>', '', ch)
                            r_fallback = await client.post(url, json=chunk_payload)
                            if r_fallback.status_code != 200:
                                success = False
                except Exception as e:
                    logger.error(f"Error enviando fragmento de mensaje Telegram: {e}")
                    success = False
            return success

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    return True
                else:
                    logger.warning(f"Telegram sendMessage error {res.status_code}: {res.text}. Reintentando con texto limpio...")
                    # Si falla por parseo HTML/Markdown, retirar parse_mode y limpiar etiquetas para no mostrar tags crudos
                    payload.pop("parse_mode", None)
                    payload["text"] = re.sub(r'<[^>]+>', '', text)
                    res2 = await client.post(url, json=payload)
                    return res2.status_code == 200
        except Exception as e:
            logger.error(f"Error al enviar mensaje a Telegram: {e}")
            return False

    async def send_chat_action(self, chat_id: int, action: str = "typing") -> bool:
        """Envía una acción de chat (ej: typing) a Telegram."""
        if not self.token:
            return False
        url = f"{self.api_base}/sendChatAction"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.post(url, json={"chat_id": chat_id, "action": action})
                return res.status_code == 200
        except Exception as e:
            logger.debug(f"Aviso en send_chat_action: {e}")
            return False

    def _load_catalog_cache(self):
        """Carga en memoria el catálogo de mercado para permitir carrusel instantáneo."""
        try:
            catalog_path = os.path.join(os.path.dirname(__file__), "..", "data", "verified_market_catalog.json")
            if os.path.exists(catalog_path):
                with open(catalog_path, "r", encoding="utf-8") as f:
                    items = json.load(f)
                    for item in items:
                        if item.get("id"):
                            self._cached_opportunities[str(item["id"]).strip().upper()] = item
            logger.info(f"TelegramAdvisorBot: {len(self._cached_opportunities)} oportunidades cargadas en caché.")
        except Exception as e:
            logger.debug(f"Aviso cargando catálogo en caché del bot: {e}")

    def cache_opportunity(self, opp: Dict[str, Any]):
        """Registra una oportunidad en la caché del bot para interactividad."""
        if opp and opp.get("id"):
            self._cached_opportunities[str(opp["id"]).strip().upper()] = opp

    def _get_cached_opportunity(self, opp_id: str) -> Optional[Dict[str, Any]]:
        """Recupera una oportunidad de la memoria o del catálogo."""
        opp_id_upper = str(opp_id).strip().upper()
        if opp_id_upper in self._cached_opportunities:
            return self._cached_opportunities[opp_id_upper]
        for k, v in self._cached_opportunities.items():
            if k.upper() == opp_id_upper:
                return v
        return None

    def build_card_reply_markup(
        self,
        opp_id: str,
        is_favorite: bool = False,
        portal_url: str = ""
    ) -> Dict[str, Any]:
        """
        Construye la botonera integrada solicitada estilo WhatsApp Marketing Template:
        - Fila 1: [ 🔍 Ver Ficha en HIVEX ] (Acceso directo a la plataforma)
        - Fila 2: [ 🌐 Visitar Portal ] (Acceso al portal fuente Idealista/Pisos.com/BOE)
        - Fila 3: [ 🤍 Guardar en Favoritos ] / [ ❤️ Guardado en Favoritos ] (Pulsable e interactivo)
        """
        opp_id_clean = str(opp_id).strip()
        norm_id = re.sub(r'^(SUB-)+', 'SUB-', opp_id_clean) if ('JA-' in opp_id_clean or 'SUB-' in opp_id_clean) else opp_id_clean
        web_link = f"{self.platform_url}/?opp_id={norm_id}"

        fav_text = "❤️ Guardado en Favoritos" if is_favorite else "🤍 Guardar en Favoritos"

        keyboard = [
            [{"text": "🔍 Ver Ficha en HIVEX", "url": web_link}]
        ]
        if portal_url and portal_url != web_link and portal_url.startswith("http"):
            keyboard.append([{"text": "🌐 Visitar Portal", "url": portal_url}])
        keyboard.append([{"text": fav_text, "callback_data": f"fav:{norm_id}"}])

        return {"inline_keyboard": keyboard}



    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
        show_alert: bool = False
    ) -> bool:
        """Responde a un callback_query de Telegram mostrando toast o alerta."""
        if not self.token:
            return False
        url = f"{self.api_base}/answerCallbackQuery"
        payload = {"callback_query_id": str(callback_query_id)}
        if text:
            payload["text"] = text
        if show_alert:
            payload["show_alert"] = True
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, json=payload)
                return res.status_code == 200
        except Exception as e:
            logger.debug(f"Aviso en answerCallbackQuery: {e}")
            return False

    async def edit_message_reply_markup(
        self,
        chat_id: int,
        message_id: int,
        reply_markup: Dict[str, Any]
    ) -> bool:
        """Actualiza los botones interactivos de un mensaje existente en Telegram."""
        if not self.token:
            return False
        url = f"{self.api_base}/editMessageReplyMarkup"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": reply_markup
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, json=payload)
                return res.status_code == 200
        except Exception as e:
            logger.debug(f"Aviso en editMessageReplyMarkup: {e}")
            return False

    async def set_message_reaction(
        self,
        chat_id: int,
        message_id: int,
        emoji: str = "❤️"
    ) -> bool:
        """Añade o quita una reacción nativa (ej. ❤️) al mensaje de la ficha en Telegram."""
        if not self.token:
            return False
        url = f"{self.api_base}/setMessageReaction"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "reaction": [{"type": "emoji", "emoji": emoji}] if emoji else []
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, json=payload)
                return res.status_code == 200
        except Exception as e:
            logger.debug(f"Aviso en setMessageReaction: {e}")
            return False


    async def edit_message_media(
        self,
        chat_id: int,
        message_id: int,
        card_bytes: bytes,
        reply_markup: Dict[str, Any]
    ) -> bool:
        """Actualiza la imagen y los botones de una ficha en Telegram en tiempo real."""
        if not self.token:
            return False
        url = f"{self.api_base}/editMessageMedia"
        media_obj = {
            "type": "photo",
            "media": "attach://photo"
        }
        data = {
            "chat_id": str(chat_id),
            "message_id": str(message_id),
            "media": json.dumps(media_obj),
            "reply_markup": json.dumps(reply_markup)
        }
        files = {"photo": ("hivex_card.png", card_bytes, "image/png")}
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                res = await client.post(url, data=data, files=files)
                return res.status_code == 200
        except Exception as e:
            logger.debug(f"Aviso en editMessageMedia: {e}")
            return False

    async def send_photo_card(
        self,
        chat_id: int,
        opp: Dict[str, Any],
        reply_to_message_id: Optional[int] = None
    ) -> bool:
        """
        Envía una alerta idéntica a la plantilla de WhatsApp solicitada:
        1. Fotos agrupadas arriba (mosaico armónico con contador de fotos).
        2. Cuerpo de tarjeta en blanco puro con el estilo visual del dashboard (título, pin, CP, métricas).
        3. Botonera integrada: 'Ver Ficha en HIVEX' y 'Visitar Portal'.
        4. Corazón pulsable e interactivo (toggle favoritos en DB y reacción nativa ❤️).
        """
        if not self.token:
            return False

        opp_id = str(opp.get("id", "")).strip()
        self.cache_opportunity(opp)

        web_link = f"{self.platform_url}/?opp_id={opp_id}"
        portal_url = opp.get("portal_url") or opp.get("url") or opp.get("source_url") or ""

        # Comprobar si el chat ya lo tiene en favoritos
        is_favorite = False

        # Construir botonera integrada limpia
        reply_markup = self.build_card_reply_markup(
            opp_id=opp_id,
            is_favorite=is_favorite,
            portal_url=portal_url
        )

        # 1. Intentar renderizar la ficha gráfica estilo WhatsApp con fotos agrupadas y cuerpo blanco
        try:
            from app.services.card_image_generator import generate_whatsapp_style_card
            card_bytes = await asyncio.to_thread(generate_whatsapp_style_card, opp)
            if card_bytes:
                photo_url = f"{self.api_base}/sendPhoto"
                files = {"photo": ("hivex_card.png", card_bytes, "image/png")}
                data = {
                    "chat_id": str(chat_id),
                    "reply_markup": json.dumps(reply_markup)
                }
                if reply_to_message_id:
                    data["reply_to_message_id"] = str(reply_to_message_id)

                async with httpx.AsyncClient(timeout=45.0) as client:
                    res = await client.post(photo_url, data=data, files=files)
                    if res.status_code == 200:
                        res_data = res.json().get("result", {})
                        sent_msg_id = res_data.get("message_id")
                        if sent_msg_id:
                            # Añadir reacción de corazón al pie del mensaje (igual que en WhatsApp)
                            await self.set_message_reaction(chat_id=chat_id, message_id=sent_msg_id, emoji="❤️")
                        return True
                    else:
                        logger.warning(f"sendPhoto devolvió {res.status_code}: {res.text}. Intentando fallback...")
        except Exception as e_card:
            logger.warning(f"Excepción renderizando tarjeta gráfica WhatsApp: {repr(e_card)}", exc_info=True)

        # 2. Fallback a mensaje HTML si el upload o render de imagen fallase
        card_html = advisor_engine.generate_telegram_card_html(opp)
        return await self.send_message(
            chat_id=chat_id,
            text=card_html,
            parse_mode="HTML",
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup
        )

    async def handle_callback_query(self, callback_query: Dict[str, Any]) -> Dict[str, Any]:
        """Gestiona eventos interactivos de botones en Telegram (favoritos, carrusel de fotos)."""
        cq_id = callback_query.get("id")
        from_user = callback_query.get("from", {})
        telegram_user_id = from_user.get("id")
        telegram_username = from_user.get("username")
        first_name = from_user.get("first_name", "Usuario")
        data = callback_query.get("data", "")
        message = callback_query.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")

        db = SessionLocal()
        try:
            # 1. Verificar si el usuario está autorizado
            is_authorized, db_user, _ = self.verify_or_link_user(
                db=db,
                telegram_user_id=telegram_user_id,
                telegram_username=telegram_username,
                first_name=first_name
            )

            # 2. Pulsación de Favorito: fav:<opp_id>
            if data.startswith("fav:"):
                opp_id = data.split("fav:", 1)[1].strip()
                opp_id_upper = opp_id.upper()

                if not is_authorized:
                    await self.answer_callback_query(
                        cq_id,
                        text="⚠️ Solo usuarios registrados y autorizados en HIVEX pueden guardar favoritos.",
                        show_alert=True
                    )
                    return {"status": "unauthorized"}

                favs = []
                if db_user and db_user.favorites_json:
                    try:
                        favs = json.loads(db_user.favorites_json)
                    except Exception:
                        favs = []

                if opp_id_upper in favs:
                    favs.remove(opp_id_upper)
                    is_now_fav = False
                    toast_text = "🤍 Oportunidad eliminada de tus favoritos de HIVEX."
                else:
                    favs.append(opp_id_upper)
                    is_now_fav = True
                    toast_text = "❤️ ¡Oportunidad guardada en tus favoritos de HIVEX!"

                if db_user:
                    db_user.favorites_json = json.dumps(favs)
                    db.commit()

                await self.answer_callback_query(cq_id, text=toast_text)

                opp = self._get_cached_opportunity(opp_id)
                raw_images = (opp.get("images") or []) if opp else []
                if isinstance(raw_images, str):
                    raw_images = [raw_images]
                valid_images = [i for i in raw_images if i and "catastro.meh.es" not in str(i).lower() and str(i).startswith("http")]
                total_photos = len(valid_images)
                portal_url = (opp.get("url") or opp.get("portal_url") or "") if opp else ""

                new_markup = self.build_card_reply_markup(
                    opp_id=opp_id,
                    is_favorite=is_now_fav,
                    portal_url=portal_url
                )
                await self.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=new_markup)
                if is_now_fav:
                    await self.set_message_reaction(chat_id=chat_id, message_id=message_id, emoji="❤️")
                return {"status": "ok", "action": "toggle_fav", "is_fav": is_now_fav}


            # 3. Pulsación de Carrusel: car:<opp_id>:<direction>:<current_index>
            elif data.startswith("car:"):
                parts = data.split(":")
                if len(parts) >= 4:
                    opp_id = parts[1]
                    direction = parts[2]
                    curr_idx = int(parts[3])

                    opp = self._get_cached_opportunity(opp_id)
                    if not opp:
                        await self.answer_callback_query(cq_id, text="⚠️ Oportunidad no encontrada en caché.")
                        return {"status": "not_found"}

                    raw_images = opp.get("images") or []
                    if isinstance(raw_images, str):
                        raw_images = [raw_images]
                    valid_images = [i for i in raw_images if i and "catastro.meh.es" not in str(i).lower() and str(i).startswith("http")]
                    total_photos = len(valid_images)

                    if total_photos <= 1:
                        await self.answer_callback_query(cq_id, text="Esta oportunidad solo dispone de 1 foto.")
                        return {"status": "single_photo"}

                    if direction == "next":
                        new_idx = (curr_idx + 1) % total_photos
                    else:
                        new_idx = (curr_idx - 1) % total_photos

                    # Comprobar si es favorito
                    favs = []
                    if db_user and db_user.favorites_json:
                        try:
                            favs = json.loads(db_user.favorites_json)
                        except Exception:
                            favs = []
                    is_fav = opp_id.upper() in favs

                    from app.services.card_image_generator import generate_opportunity_card_image
                    gmaps_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
                    new_card_bytes = generate_opportunity_card_image(
                        opp=opp,
                        gmaps_api_key=gmaps_key,
                        photo_index=new_idx,
                        is_favorite=is_fav
                    )

                    portal_url = opp.get("url") or opp.get("portal_url") or ""
                    new_markup = self.build_card_reply_markup(
                        opp_id=opp_id,
                        is_favorite=is_fav,
                        photo_index=new_idx,
                        total_photos=total_photos,
                        portal_url=portal_url
                    )

                    await self.edit_message_media(
                        chat_id=chat_id,
                        message_id=message_id,
                        card_bytes=new_card_bytes,
                        reply_markup=new_markup
                    )
                    await self.answer_callback_query(cq_id)
                    return {"status": "ok", "action": "carousel", "photo_index": new_idx}

            # 4. Contador de fotos
            elif data.startswith("noop"):
                await self.answer_callback_query(cq_id, text="ℹ️ Pulsa ◀️ o ▶️ para cambiar la foto del inmueble.")
                return {"status": "noop"}

            await self.answer_callback_query(cq_id)
            return {"status": "unknown_action"}

        except Exception as e_cq:
            logger.error(f"Error gestionando callback_query: {e_cq}", exc_info=True)
            await self.answer_callback_query(cq_id, text="⚠️ Error procesando la acción.")
            return {"status": "error", "error": str(e_cq)}
        finally:
            db.close()

    def synthesize_conversation_prompt(
        self,
        chat_id: Any,
        user_id: Any,
        current_text: str,
        reply_to: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Sintetiza de forma inteligente el prompt cuando el usuario encadena mensajes
        o responde a una propuesta previa del asistente (ej: el bot propone buscar fincas rústicas en
        el radio de 15km del Colegio Suizo y el usuario responde 'sí' y luego añade 'busca también los chalets individuales').
        Garantiza que nunca se pierda el hilo conductor ni los criterios acumulados.
        """
        clean_text = (current_text or "").strip()
        if not clean_text:
            return clean_text

        # 1. Si el usuario utilizó la función nativa 'Reply' de Telegram
        if reply_to:
            prev_text = reply_to.get("text") or reply_to.get("caption") or ""
            if prev_text:
                clean_prev = re.sub(r'<[^>]+>', '', prev_text).strip()
                logger.info(f"Incorporando contexto de mensaje respondido nativamente ({len(clean_prev)} caracteres)")
                return (
                    f"[Contexto conversacional: El usuario está respondiendo específicamente a este mensaje previo de HIVEX:\n"
                    f"'''{clean_prev[:600]}'''\n]\n"
                    f"Pregunta del usuario sobre el mensaje anterior: {clean_text}"
                )

        # 2. Consultar historial reciente en BD para este chat y usuario
        last_assistant_msg = None
        recent_user_msgs = []
        try:
            with SessionLocal() as db_hist:
                last_assistant_msg = db_hist.query(TelegramConversationMessage).filter(
                    TelegramConversationMessage.telegram_chat_id == str(chat_id),
                    TelegramConversationMessage.role == "assistant"
                ).order_by(TelegramConversationMessage.id.desc()).first()

                window_ago = datetime.utcnow() - timedelta(hours=24)
                recent_user_msgs = db_hist.query(TelegramConversationMessage).filter(
                    TelegramConversationMessage.telegram_chat_id == str(chat_id),
                    TelegramConversationMessage.telegram_user_id == str(user_id),
                    TelegramConversationMessage.role == "user",
                    TelegramConversationMessage.created_at >= window_ago
                ).order_by(TelegramConversationMessage.id.desc()).limit(5).all()
        except Exception as e_hist:
            logger.warning(f"Error recuperando historial para concatenación de prompt: {e_hist}")

        clean_lower = clean_text.lower()
        affirmation_words = {"sí", "si", "vale", "ok", "adelante", "hazlo", "de acuerdo", "perfecto", "actívalo", "activar", "por favor", "claro"}
        is_pure_affirmation = any(clean_lower == aff or clean_lower.startswith(aff + " ") or clean_lower.startswith(aff + ",") for aff in affirmation_words)

        extension_triggers = [
            "busca también", "busca tambien", "también", "tambien", "además", "ademas",
            "y además", "y ademas", "y busca", "y también", "y tambien", "pero también",
            "pero tambien", "incluye", "añade", "agrega"
        ]
        is_extension = any(clean_lower.startswith(ext) or f" {ext} " in clean_lower for ext in extension_triggers)

        # Extraer propuesta o pregunta del asistente previo si existe
        assistant_proposal = ""
        if last_assistant_msg and last_assistant_msg.content:
            ast_content = last_assistant_msg.content
            # Buscar preguntas explícitas como "¿Deseas que activemos el radar...?"
            m_q = re.search(r'¿(?:Deseas?|Quieres?|Te gustaría|Gusta)\s+(?:que\s+)?([^?]+)\?', ast_content, re.IGNORECASE)
            if m_q:
                assistant_proposal = m_q.group(1).strip()
            else:
                # Buscar en el bloque de Próximo Paso Accionable
                m_step = re.search(r'(?:Próximo Paso Accionable|💡)[^\n]*\n+([^\n]+(?:\n[^\n]+)?)', ast_content, re.IGNORECASE)
                if m_step:
                    raw_p = re.sub(r'<[^>]+>', '', m_step.group(1)).strip()
                    m_p_q = re.search(r'¿(?:Deseas?|Quieres?|Te gustaría|Gusta)\s+(?:que\s+)?([^?]+)\?', raw_p, re.IGNORECASE)
                    if m_p_q:
                        assistant_proposal = m_p_q.group(1).strip()
                    else:
                        assistant_proposal = raw_p

        # Comprobar si el usuario había enviado una afirmación previa en el historial
        had_recent_affirmation = False
        for u_msg in recent_user_msgs:
            u_clean = u_msg.content.strip().lower()
            if any(u_clean == aff or u_clean.startswith(aff + " ") for aff in affirmation_words):
                had_recent_affirmation = True
                break

        # Normalizar propuesta
        normalized_proposal = assistant_proposal
        if normalized_proposal.lower().startswith("activemos "):
            normalized_proposal = "activa " + normalized_proposal[10:]
        elif normalized_proposal.lower().startswith("nuestro equipo de inteligencia de mercado rastree "):
            normalized_proposal = "activa el radar para rastrear " + normalized_proposal[50:]

        if normalized_proposal:
            # Caso 1: El usuario sólo dijo "sí" o "de acuerdo"
            if is_pure_affirmation and len(clean_text.split()) <= 4:
                logger.info(f"[Prompt Chaining] Usuario afirmó propuesta previa -> 'Sí, {normalized_proposal}'")
                return f"Sí, {normalized_proposal}"

            # Caso 2: El usuario añadió una extensión tras decir "sí" previamente, o este mensaje empieza con extensión
            if had_recent_affirmation and (is_extension or len(clean_text.split()) > 1):
                logger.info(f"[Prompt Chaining] Encadenando afirmación previa + nuevo requisito -> 'Sí, {normalized_proposal}, y además {clean_text}'")
                return f"Sí, {normalized_proposal}, y además {clean_text}"

            # Caso 3: El mensaje actual combina afirmación y extensión (ej: "Sí, busca también chalets")
            if is_pure_affirmation and is_extension:
                clean_remainder = re.sub(r'^(?:sí|si|vale|ok|adelante|de acuerdo|por favor)[,.\s]+(?:y\s+)?', '', clean_text, flags=re.IGNORECASE).strip()
                logger.info(f"[Prompt Chaining] Mensaje con afirmación y extensión directa -> 'Sí, {normalized_proposal}, y además {clean_remainder}'")
                return f"Sí, {normalized_proposal}, y además {clean_remainder}"

        # Caso 4: Encadenamiento directo de mensajes del usuario sin propuesta del asistente
        if is_extension and recent_user_msgs:
            for u_m in recent_user_msgs:
                prev_u = (u_m.content or "").strip()
                if prev_u and not any(prev_u.lower() == aff for aff in affirmation_words) and len(prev_u) > 10:
                    logger.info(f"[Prompt Chaining] Concatenando mensaje previo del usuario: '{prev_u}' + '{clean_text}'")
                    return f"{prev_u}, y además {clean_text}"

        return clean_text

    # --------------------------------------------------------------------------
    # 4. GESTIÓN Y PROCESAMIENTO DE UPDATES
    # --------------------------------------------------------------------------
    async def process_update(self, update: Dict[str, Any]) -> Dict[str, Any]:
        """Procesa un update entrante de Telegram (vía Webhook o Polling)."""
        # 1. Si es interacción de botones (callback_query)
        callback_query = update.get("callback_query")
        if callback_query:
            return await self.handle_callback_query(callback_query)

        message = update.get("message") or update.get("edited_message")
        if not message:
            return {"status": "ignored", "reason": "No message or callback_query in update"}

        from_user = message.get("from", {})
        # Ignorar mensajes enviados por bots (incluyendo el propio bot) para evitar bucles
        if from_user.get("is_bot", False):
            return {"status": "ignored", "reason": "Message from bot"}

        message_id = message.get("message_id")
        if message_id:
            if message_id in self._processed_message_ids:
                return {"status": "ignored", "reason": "Already processed message"}
            self._processed_message_ids.add(message_id)
            if len(self._processed_message_ids) > 1000:
                self._processed_message_ids.clear()

        chat = message.get("chat", {})
        chat_id = chat.get("id")
        user_id = from_user.get("id")
        username = from_user.get("username")
        first_name = from_user.get("first_name", "Usuario")

        text_content = (message.get("text") or "").strip()
        voice = message.get("voice")
        audio = message.get("audio")

        # Comprobar comandos especiales
        is_link_cmd = text_content.startswith("/vincular") or text_content.startswith("/link")
        link_args = text_content.split(maxsplit=1)[1] if (is_link_cmd and len(text_content.split()) > 1) else None

        # Enviar acción "typing" inmediatamente para feedback en tiempo real
        asyncio.create_task(self.send_chat_action(chat_id, "typing"))

        try:
            # 1. VERIFICAR AUTENTICACIÓN DEL USUARIO (Sesión DB corta y aislada)
            user_display_name = username or first_name or "usuario"
            with SessionLocal() as db_auth:
                is_authorized, db_user, auth_reason = self.verify_or_link_user(
                    db=db_auth,
                    telegram_user_id=user_id,
                    telegram_username=username,
                    first_name=first_name,
                    command_args=link_args
                )
                if is_authorized and db_user:
                    user_display_name = db_user.username

            # Si el usuario NO está autorizado, responder con advertencia indicando contactar al administrador
            if not is_authorized:
                logger.warning(f"Intento de acceso no autorizado en Telegram: UserID={user_id}, Username={username}, Name={first_name}, ChatID={chat_id}, Text={text_content}")
                unauth_reply = (
                    "⚠️ El usuario que realiza la solicitud no ha sido identificado como un usuario con acceso en el portal inmobiliario de HIVEX.\n\n"
                    "Por favor, contacta con el administrador de la plataforma para obtener acceso."
                )
                await self.send_message(chat_id, unauth_reply, reply_to_message_id=message_id)
                return {"status": "unauthorized", "user_id": user_id, "username": username}

            # Si el usuario está autorizado pero envía /vincular, informar que ya tiene acceso
            if is_link_cmd:
                reply = (
                    f"✅ Tu cuenta ya está autorizada en HIVEX como <b>{user_display_name}</b>.\n"
                    f"Puedes hacerme cualquier consulta directamente."
                )
                await self.send_message(chat_id, reply, parse_mode="HTML", reply_to_message_id=message_id)
                return {"status": "already_authorized", "user": username}

            # 2. PROCESAR MENSAJE (TEXTO O AUDIO)
            audio_bytes = None
            audio_duration = None
            # Sintetizar prompt contextualizado si hay encadenamiento de mensajes o respuesta previa
            reply_to = message.get("reply_to_message")
            prompt_to_process = self.synthesize_conversation_prompt(
                chat_id=chat_id,
                user_id=user_id,
                current_text=text_content or "",
                reply_to=reply_to
            )

            # Si es nota de voz o archivo de audio
            if voice or audio:
                target_file_id = voice.get("file_id") if voice else audio.get("file_id")
                audio_duration = voice.get("duration") if voice else audio.get("duration")
                await self.send_message(chat_id, "🎙️ _Escuchando y analizando nota de voz..._", reply_to_message_id=message_id)

                audio_bytes = await self.download_telegram_file(target_file_id)
                if not audio_bytes:
                    await self.send_message(chat_id, "❌ No se pudo descargar el audio. Por favor intenta enviarlo nuevamente.")
                    return {"status": "audio_download_failed"}

            # Si es comando /start o /help
            if text_content in ("/start", "/help", "/ayuda"):
                welcome_msg = (
                    f"👋 **¡Hola {db_user.username if db_user else first_name}!**\n\n"
                    f"Soy tu **Asesor Inmobiliario Conversacional HIVEX**.\n\n"
                    f"💡 **¿Qué puedes pedirme?**\n"
                    f"• *Buscar oportunidades:* «Busca pisos en Valencia por menos de 150.000€ con más del 20% de descuento»\n"
                    f"• *Audios de voz:* ¡Grábame una nota de voz con lo que necesitas!\n"
                    f"• *Análisis de Zonas:* «Cómo está el distrito centro de Madrid y qué precios m² hay»\n"
                    f"• *Cálculo de ROI / BTL:* «Qué rentabilidad de alquiler puedo esperar en Alicante»\n"
                    f"• *Scoring y Comparativa:* «Cuáles son las 3 mejores oportunidades en Zaragoza por score»\n"
                    f"• *Alertas Programadas:* «Avísame cuando salga una vivienda en Málaga con yield > 8%»\n\n"
                    f"📂 *Todas tus consultas quedan guardadas automáticamente en tu panel web de HIVEX.*"
                )
                await self.send_message(chat_id, welcome_msg, reply_to_message_id=message_id)
                return {"status": "welcomed"}

            # Enviar indicador de 'escribiendo...' a Telegram mientras se ejecuta el razonamiento
            await self.send_chat_action(chat_id, "typing")

            # Ejecutar consulta en el Motor Asesor (process_user_query abre su propia sesión corta al persistir)
            res = await advisor_engine.process_user_query(
                user_name=user_display_name,
                telegram_chat_id=str(chat_id),
                telegram_user_id=str(user_id),
                prompt_text=prompt_to_process,
                audio_bytes=audio_bytes,
                audio_duration=audio_duration,
                db=None
            )

            # Enviar la respuesta del Asesor a Telegram con fichas visuales
            matched_opps = res.get("matched_opportunities") or []
            should_display_cards = res.get("should_display_cards", False)
            intro_text = res.get("intro_text")

            if matched_opps and should_display_cards:
                # 1. Enviar resumen diagnóstico introductorio
                if intro_text:
                    await self.send_message(chat_id, intro_text, parse_mode="HTML", reply_to_message_id=message_id)
                else:
                    await self.send_message(chat_id, res["response_text"], parse_mode="HTML", reply_to_message_id=message_id)

                target_count = int(res.get("criteria", {}).get("target_count") or 20)
                # Enviar exactamente las oportunidades solicitadas
                cards_to_send = matched_opps[:target_count]
                for opp in cards_to_send:
                    await self.send_photo_card(chat_id=chat_id, opp=opp)
                    await asyncio.sleep(0.35)

            else:
                # Si no hubo petición explícita de fichas o es reporte cuantitativo, despachar el texto analítico
                await self.send_message(chat_id, res["response_text"], parse_mode="HTML", reply_to_message_id=message_id)

            return {
                "status": "success",
                "consultation_id": res.get("saved_consultation_id"),
                "title": res.get("title"),
                "matched_count": res.get("matched_count")
            }

        except Exception as e:
            logger.error(f"Error procesando update de Telegram: {e}", exc_info=True)
            await self.send_message(chat_id, f"⚠️ Ocurrió un error al procesar tu solicitud: {str(e)}")
            return {"status": "error", "error": str(e)}

    # --------------------------------------------------------------------------
    # 5. POLLING EN SEGUNDO PLANO (MODO DESARROLLO / LOCAL)
    # --------------------------------------------------------------------------
    async def start_polling(self):
        """Inicia un ciclo de polling para recibir updates si no se utiliza webhook."""
        if not self.token:
            logger.info("TelegramAdvisorBot: No hay token configurado. Polling desactivado.")
            return

        if self._is_polling:
            return

        self._is_polling = True
        logger.info("TelegramAdvisorBot: Iniciando polling conversacional en segundo plano...")

        offset = 0
        async with httpx.AsyncClient(timeout=35.0) as client:
            while self._is_polling:
                try:
                    url = f"{self.api_base}/getUpdates?offset={offset}&timeout=20"
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        data = resp.json()
                        updates = data.get("result", [])
                        for u in updates:
                            update_id = u.get("update_id", 0)
                            offset = max(offset, update_id + 1)
                            # Procesar en segundo plano
                            asyncio.create_task(self.process_update(u))
                    elif resp.status_code == 409:
                        # Conflicto con webhook existente
                        logger.warning("Telegram polling en conflicto con webhook activo. Esperando 10s...")
                        await asyncio.sleep(10)
                    else:
                        await asyncio.sleep(3)
                except Exception as e:
                    logger.debug(f"Aviso en polling Telegram: {e}")
                    await asyncio.sleep(3)

    def stop_polling(self):
        """Detiene el polling."""
        self._is_polling = False
        if self._polling_task:
            self._polling_task.cancel()

telegram_advisor_bot = TelegramAdvisorBot()
