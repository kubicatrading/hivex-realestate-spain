"""
HIVEX Telegram Conversational Real Estate Advisor Service
Gestiona la recepción de mensajes de texto y notas de voz, autenticación de usuarios,
interacción conversacional y ejecución del motor asesor inmobiliario.
"""

import os
import re
import json
import html
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.db.models import User, TelegramConversationMessage, SavedConsultation
from app.engine.advisor_engine import advisor_engine

logger = logging.getLogger(__name__)

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

    def _ensure_token(self) -> str:
        """Garantiza que el token de Telegram esté cargado dinámicamente desde settings o variables de entorno."""
        if not self.token:
            self.token = (
                os.getenv("TELEGRAM_BOT_TOKEN")
                or getattr(settings, "TELEGRAM_BOT_TOKEN", "")
                or ""
            ).strip()
            if self.token:
                self.api_base = f"https://api.telegram.org/bot{self.token}"
        return self.token

    # --------------------------------------------------------------------------
    # 1. VERIFICACIÓN Y VINCULACIÓN DE USUARIOS
    # --------------------------------------------------------------------------
    def verify_or_link_user(
        self,
        db: Session,
        telegram_user_id: Any,
        telegram_username: Optional[str] = None,
        first_name: Optional[str] = None,
        command_args: Optional[str] = None,
        chat_id: Optional[Any] = None
    ) -> Tuple[bool, Optional[User], str]:
        """
        Verifica si el usuario de Telegram está autorizado en la plataforma HIVEX.
        La autorización se gestiona exclusivamente por el administrador en la plataforma
        (mediante User.telegram_id, User.telegram_username o lista autorizada en variables de entorno).
        """
        # 0. En el grupo corporativo oficial de HIVEX (-1003904392737), siempre autorizar
        if str(chat_id) == "-1003904392737": # Solo el chat_id negativo es el grupo oficial
            admin = db.query(User).filter(User.username == "jsaavedra").first()
            if admin:
                return True, admin, "Usuario autorizado por pertenecer al grupo oficial HIVEX"

        str_tg_id = str(telegram_user_id) if telegram_user_id is not None else ""
        tg_user_clean = (telegram_username or "").lower().lstrip("@")

        # 1. Caso explícito prioritario para el administrador y usuario principal jsaavedra
        if str_tg_id == "1450113787" or tg_user_clean in ["juanma_oms", "jsaavedra"]:
            admin = db.query(User).filter(User.username == "jsaavedra").first()
            if not admin:
                try:
                    admin = User(
                        username="jsaavedra",
                        email="juanma@hivex.internal",
                        hashed_password="admin_default_hash",
                        salt="admin_default_salt",
                        is_active=True,
                        is_admin=True,
                        telegram_id="1450113787",
                        telegram_username="Juanma_OMS"
                    )
                    db.add(admin)
                    db.commit()
                    db.refresh(admin)
                except Exception as e_add_admin:
                    db.rollback()
                    logger.warning(f"Error creando usuario jsaavedra: {e_add_admin}")
            else:
                if admin.telegram_id != "1450113787" or admin.telegram_username != "Juanma_OMS":
                    admin.telegram_id = "1450113787"
                    admin.telegram_username = "Juanma_OMS"
                    db.commit()
            return True, admin, f"Usuario autenticado como jsaavedra (Juanma)"

        # 2. Búsqueda por telegram_id ya registrado en BD
        user = db.query(User).filter(User.telegram_id == str_tg_id).first()
        if user and user.is_active:
            return True, user, f"Usuario autenticado por ID de Telegram ({user.username})"

        # 3. Búsqueda por username coincidente en BD registrado por el administrador
        if tg_user_clean:
            user = db.query(User).filter(
                (User.telegram_username.ilike(tg_user_clean)) |
                (User.username.ilike(tg_user_clean))
            ).first()
            if user and user.is_active:
                user.telegram_id = str_tg_id
                user.telegram_username = tg_user_clean
                db.commit()
                return True, user, f"Usuario vinculado automáticamente por username ({user.username})"

        # 4. Comprobación en lista autorizada de variables de entorno (mapeo unívoco por username)
        if (str_tg_id in self.authorized_env_users) or (tg_user_clean and tg_user_clean in self.authorized_env_users):
            target_user = None
            if tg_user_clean:
                target_user = db.query(User).filter(
                    (User.username.ilike(tg_user_clean)) | (User.telegram_username.ilike(tg_user_clean))
                ).first()
            if not target_user:
                # Si es el ID conocido de Juanma
                if str_tg_id == "1450113787":
                    target_user = db.query(User).filter(User.username == "jsaavedra").first()
                else:
                    target_user = db.query(User).filter(User.telegram_id == str_tg_id).first()
            if target_user:
                target_user.telegram_id = str_tg_id
                if tg_user_clean:
                    target_user.telegram_username = tg_user_clean
                db.commit()
                return True, target_user, f"Usuario autorizado por configuración de entorno ({target_user.username})"

        return False, None, "Usuario no identificado en HIVEX"

    # --------------------------------------------------------------------------
    # 2. DESCARGA DE AUDIO / NOTA DE VOZ DESDE TELEGRAM
    # --------------------------------------------------------------------------
    async def download_telegram_file(self, file_id: str) -> Optional[bytes]:
        """Descarga el binario de audio de una nota de voz mediante la API de Telegram."""
        if not self._ensure_token():
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
        if not self._ensure_token():
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
                            chunk_payload.pop("reply_to_message_id", None)
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
                    # Si falla por parseo HTML/Markdown o por reply_to_message_id no encontrado, retirar ambos
                    payload.pop("parse_mode", None)
                    payload.pop("reply_to_message_id", None)
                    payload["text"] = re.sub(r'<[^>]+>', '', text)
                    res2 = await client.post(url, json=payload)
                    return res2.status_code == 200
        except Exception as e:
            logger.error(f"Error al enviar mensaje a Telegram: {e}")
            return False

    async def send_chat_action(self, chat_id: int, action: str = "typing") -> bool:
        """Envía una acción de chat (ej: typing) a Telegram."""
        if not self._ensure_token():
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
        if not self._ensure_token():
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
        if not self._ensure_token():
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
        if not self._ensure_token():
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
        if not self._ensure_token():
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
        if not self._ensure_token():
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
                    for attempt in range(3):
                        res = await client.post(photo_url, data=data, files=files)
                        if res.status_code == 200:
                            res_data = res.json().get("result", {})
                            sent_msg_id = res_data.get("message_id")
                            if sent_msg_id:
                                # Añadir reacción de corazón al pie del mensaje (igual que en WhatsApp)
                                await self.set_message_reaction(chat_id=chat_id, message_id=sent_msg_id, emoji="❤️")
                            return True
                        elif res.status_code == 429:
                            try:
                                retry_sec = int(res.json().get("parameters", {}).get("retry_after", 3))
                            except Exception:
                                retry_sec = 3
                            logger.warning(f"sendPhoto rate-limited (429, intento {attempt+1}/3). Pausando {retry_sec + 1}s...")
                            await asyncio.sleep(retry_sec + 1)
                            files = {"photo": ("hivex_card.png", card_bytes, "image/png")}
                        else:
                            logger.warning(f"sendPhoto devolvió {res.status_code}: {res.text}. Reintentando...")
                            await asyncio.sleep(1.0)
                            files = {"photo": ("hivex_card.png", card_bytes, "image/png")}
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

    def get_last_active_search_context(self, chat_id: Any) -> Optional[Dict[str, Any]]:
        """
        Recupera el último contexto o búsqueda activa en la memoria de este chat.
        Examina SavedConsultation y TelegramConversationMessage previos.
        """
        try:
            with SessionLocal() as db_mem:
                # 1. Buscar en SavedConsultation de este chat
                last_consultation = db_mem.query(SavedConsultation).filter(
                    SavedConsultation.telegram_chat_id == str(chat_id)
                ).order_by(SavedConsultation.id.desc()).first()

                if last_consultation:
                    crit = {}
                    if last_consultation.criteria_json:
                        try:
                            crit = json.loads(last_consultation.criteria_json)
                        except Exception:
                            crit = {}
                    zone = crit.get("zone_or_neighborhood") or crit.get("province") or crit.get("locality")
                    if not zone and last_consultation.title:
                        m = re.search(r'en\s+([A-Za-zÁÉÍÓÚáéíóúñÑ\s]+)$', last_consultation.title)
                        if m:
                            zone = m.group(1).strip()
                    if zone and zone.lower() != "españa":
                        return {
                            "zone": zone,
                            "title": last_consultation.title,
                            "description": last_consultation.description or "",
                            "criteria": crit
                        }

                # 2. Buscar en los últimos mensajes de usuario en este chat
                from app.engine.advisor_engine import advisor_engine
                recent_msgs = db_mem.query(TelegramConversationMessage).filter(
                    TelegramConversationMessage.telegram_chat_id == str(chat_id),
                    TelegramConversationMessage.role == "user"
                ).order_by(TelegramConversationMessage.id.desc()).limit(10).all()

                for m in recent_msgs:
                    txt = (m.content or "").strip()
                    crit = advisor_engine._parse_query_intent_heuristics(txt)
                    zone = crit.get("zone_or_neighborhood") or crit.get("province")
                    if zone and zone.lower() != "españa":
                        return {
                            "zone": zone,
                            "title": f"Búsqueda en {zone}",
                            "description": txt,
                            "criteria": crit
                        }
        except Exception as e_mem:
            logger.warning(f"Error consultando banco de memoria para chat {chat_id}: {e_mem}")

        return None

    def synthesize_conversation_prompt(
        self,
        chat_id: Any,
        user_id: Any,
        current_text: str,
        reply_to: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, Optional[str]]:
        """
        Sintetiza de forma inteligente el prompt contextualizado del usuario:
        1. Si responde a un mensaje específico con Reply nativo de Telegram.
        2. Si hace referencia a 'misma zona' o 'misma búsqueda': busca en el banco de memoria la última búsqueda activa.
           Si no encuentra nada, activa fallback conversacional para solicitar confirmación de zona de forma natural.
        3. Concatena mensajes consecutivos del mismo usuario o chat con punto y seguido sin exigir palabras clave.
        Retorna (prompt_to_process, clarification_question).
        """
        clean_text = (current_text or "").strip()
        if not clean_text:
            return clean_text, None

        # 1. Si el usuario utilizó la función nativa 'Reply' de Telegram
        if reply_to:
            prev_text = reply_to.get("text") or reply_to.get("caption") or ""
            if prev_text:
                clean_prev = re.sub(r'<[^>]+>', '', prev_text).strip()
                logger.info(f"Incorporando contexto de mensaje respondido nativamente ({len(clean_prev)} caracteres)")
                return (
                    f"[Contexto conversacional: El usuario está respondiendo específicamente a este mensaje previo de HIVEX:\n"
                    f"'''{clean_prev[:600]}'''\n]\n"
                    f"Pregunta del usuario sobre el mensaje anterior: {clean_text}",
                    None
                )

        clean_lower = clean_text.lower()
        anaphora_triggers = [
            "la misma", "misma zona", "mismo lugar", "misma búsqueda", "misma busqueda",
            "en esa zona", "por allí", "por alli", "en ese eje", "por esa zona", "en la misma"
        ]
        
        # Comprobar si el texto actual YA especifica una zona o términos geográficos explícitos
        from app.engine.advisor_engine import advisor_engine
        current_parsed = advisor_engine._parse_query_intent_heuristics(clean_text)
        has_explicit_zone = bool(current_parsed.get("zone_or_neighborhood"))
        
        # Es anáfora hacia una búsqueda anterior SOLO si el usuario NO especifica una nueva zona en este mensaje
        is_anaphora = not has_explicit_zone and any(ana in clean_lower for ana in anaphora_triggers)

        # 2. Consultar historial reciente en BD para este chat
        last_assistant_msg = None
        recent_user_msgs = []
        try:
            with SessionLocal() as db_hist:
                last_assistant_msg = db_hist.query(TelegramConversationMessage).filter(
                    TelegramConversationMessage.telegram_chat_id == str(chat_id),
                    TelegramConversationMessage.role == "assistant"
                ).order_by(TelegramConversationMessage.id.desc()).first()

                window_ago = datetime.utcnow() - timedelta(minutes=25)
                recent_user_msgs = db_hist.query(TelegramConversationMessage).filter(
                    TelegramConversationMessage.telegram_chat_id == str(chat_id),
                    TelegramConversationMessage.role == "user",
                    TelegramConversationMessage.created_at >= window_ago
                ).order_by(TelegramConversationMessage.id.desc()).limit(3).all()
        except Exception as e_hist:
            logger.warning(f"Error recuperando historial para concatenación de prompt: {e_hist}")

        # 3. Referencia a "la misma zona" o "la misma búsqueda" (Banco de memoria previo)
        if is_anaphora:
            last_context = self.get_last_active_search_context(chat_id)
            if last_context and last_context.get("zone"):
                recovered_zone = last_context["zone"]
                logger.info(f"[Memory Bank] ✅ Zona activa previa recuperada con éxito: '{recovered_zone}'")
                enriched_text = f"{clean_text}. Zona: {recovered_zone} (Búsqueda previa de referencia: {last_context.get('description', '')[:120]})"
                return enriched_text, None
            else:
                # Fallback conversacional: Preguntar la zona de forma natural para no lanzar macro-análisis a ciegas
                logger.info("[Memory Bank] ⚠️ No se encontró zona activa en memoria. Activando fallback conversacional de aclaración.")
                fallback_question = (
                    "🤔 Para realizar la búsqueda en la misma zona, ¿a qué municipio o zona te refieres exactamente?\n\n"
                    "Indícamelo para afinar los resultados y buscar con precisión."
                )
                return clean_text, fallback_question

        # 4. Concatenación de mensajes consecutivos: SOLO si el mensaje actual es una continuación o refinamiento
        # (ej: "y con piscina", "de más de 100m2", "con pozo"), NO si es una búsqueda completa independiente
        if recent_user_msgs:
            last_u = recent_user_msgs[0]
            prev_u_text = (last_u.content or "").strip()
            affirmation_words = {"sí", "si", "vale", "ok", "adelante", "hazlo", "de acuerdo", "perfecto"}
            
            is_new_independent_search = any(
                clean_lower.startswith(prefix) for prefix in [
                    "búscame", "buscame", "busca", "buscar", "encuentra", "dime", "muéstrame", "muestrame",
                    "quiero", "necesito", "dame", "analiza", "cuál es", "cual es", "qué tal", "que tal"
                ]
            ) or has_explicit_zone

            if not is_new_independent_search and prev_u_text and prev_u_text != clean_text and prev_u_text.lower() not in affirmation_words:
                logger.info(f"[Prompt Chaining] Concatenando refinamiento previo del usuario con punto y seguido: '{prev_u_text}. {clean_text}'")
                combined_text = f"{prev_u_text}. {clean_text}"
                return combined_text, None

        return clean_text, None

    # --------------------------------------------------------------------------
    # 4. GESTIÓN Y PROCESAMIENTO DE UPDATES
    # --------------------------------------------------------------------------
    async def process_update(self, update: Dict[str, Any]) -> Dict[str, Any]:
        """Procesa un update entrante de Telegram (vía Webhook o Polling)."""
        # 1. Si es interacción de botones (callback_query)
        callback_query = update.get("callback_query")
        if callback_query:
            return await self.handle_callback_query(callback_query)

        is_edited = "edited_message" in update
        message = update.get("message") or update.get("edited_message")
        if not message:
            return {"status": "ignored", "reason": "No message or callback_query in update"}

        from_user = message.get("from", {})
        is_anonymous_group_admin = from_user.get("is_bot", False) and from_user.get("username") == "GroupAnonymousBot"
        # Ignorar mensajes enviados por bots ajenos (incluyendo el propio bot) para evitar bucles
        if from_user.get("is_bot", False) and not is_anonymous_group_admin:
            return {"status": "ignored", "reason": "Message from bot"}

        message_id = message.get("message_id")
        dedup_key = f"edit_{message_id}_{message.get('edit_date', '')}" if is_edited else message_id
        if dedup_key:
            if dedup_key in self._processed_message_ids:
                return {"status": "ignored", "reason": "Already processed message"}
            self._processed_message_ids.add(dedup_key)
            if len(self._processed_message_ids) > 1000:
                self._processed_message_ids.clear()

        chat = message.get("chat", {})
        chat_id = chat.get("id")
        user_id = from_user.get("id")
        username = from_user.get("username")
        first_name = from_user.get("first_name", "Usuario")

        sender_chat = message.get("sender_chat", {})
        if (not user_id or is_anonymous_group_admin) and sender_chat:
            user_id = sender_chat.get("id") or 1450113787
            username = sender_chat.get("title") or "jsaavedra"
            first_name = "Admin"

        text_content = (message.get("text") or "").strip()
        if text_content:
            # Normalizar comandos de grupo como /dev@HIVEXRealEstateBot -> /dev
            text_content = re.sub(r'^/(dev|agent|desarrollo|alertas|activar|desactivar|pausar|reanudar|vincular|link)@\w+', r'/\1', text_content, flags=re.IGNORECASE).strip()
            # Limpiar menciones al bot para que las preguntas naturales fluyan limpiamente
            text_content = re.sub(r'@\w*hivex\w*', '', text_content, flags=re.IGNORECASE).strip()

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
                    command_args=link_args,
                    chat_id=chat_id
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
            if text_content:
                # Comprobar si es comando para el DevAgent (/dev, /agent, /desarrollo)
                if text_content.lower().startswith(("/dev", "/agent", "/desarrollo")):
                    dev_handled = await self.handle_dev_agent_command(
                        chat_id=chat_id,
                        user_id=user_id,
                        user_display_name=user_display_name,
                        task_text=text_content,
                        message_id=message_id
                    )
                    if dev_handled:
                        return {"status": "dev_agent_triggered", "user": user_display_name}

                # REQUISITO 3: El bot es capaz de activar o inactivar una alerta/búsqueda desde el propio grupo de Telegram
                alert_handled = await self.handle_toggle_alert_command(
                    chat_id=chat_id,
                    user_id=user_id,
                    user_display_name=user_display_name,
                    text_content=text_content,
                    message_id=message_id
                )
                if alert_handled:
                    return {"status": "alert_toggled", "user": user_display_name}

            audio_bytes = None
            audio_duration = None
            # Sintetizar prompt contextualizado si hay encadenamiento de mensajes o respuesta previa
            reply_to = message.get("reply_to_message")
            prompt_to_process, clarification_question = self.synthesize_conversation_prompt(
                chat_id=chat_id,
                user_id=user_id,
                current_text=text_content or "",
                reply_to=reply_to
            )

            # Si se requiere aclaración conversacional (ej: fallback cuando no se encuentra la zona en memoria)
            if clarification_question:
                await self.send_message(chat_id, clarification_question, reply_to_message_id=message_id)
                # Registrar en memoria para que la respuesta subsiguiente del usuario se encadene naturalmente
                try:
                    with SessionLocal() as db_clarify:
                        db_clarify.add(TelegramConversationMessage(
                            telegram_chat_id=str(chat_id),
                            telegram_user_id=str(user_id),
                            user_id=db_user.id if db_user else None,
                            role="user",
                            content=text_content or ""
                        ))
                        db_clarify.add(TelegramConversationMessage(
                            telegram_chat_id=str(chat_id),
                            telegram_user_id=str(user_id),
                            user_id=db_user.id if db_user else None,
                            role="assistant",
                            content=clarification_question
                        ))
                        db_clarify.commit()
                except Exception as e_reg:
                    logger.warning(f"Error registrando aclaración conversacional en BD: {e_reg}")
                return {"status": "clarification_requested", "question": clarification_question}

            # Si es nota de voz o archivo de audio
            if voice or audio:
                target_file_id = voice.get("file_id") if voice else audio.get("file_id")
                audio_duration = voice.get("duration") if voice else audio.get("duration")
                await self.send_message(chat_id, "🎙️ _Escuchando y analizando nota de voz..._", reply_to_message_id=message_id)

                audio_bytes = await self.download_telegram_file(target_file_id)
                if not audio_bytes:
                    await self.send_message(chat_id, "❌ No se pudo descargar el audio. Por favor intenta enviarlo nuevamente.")
                    return {"status": "audio_download_failed"}

                # Comprobar si la nota de voz es una instrucción para el DevAgent
                try:
                    voice_transcription = await advisor_engine.transcribe_audio(audio_bytes)
                    if voice_transcription:
                        clean_vt = voice_transcription.strip().lower()
                        if clean_vt.startswith(("/dev", "dev", "desarrollo", "modo dev", "código", "programar")):
                            dev_handled = await self.handle_dev_agent_command(
                                chat_id=chat_id,
                                user_id=user_id,
                                user_display_name=user_display_name,
                                task_text=voice_transcription,
                                message_id=message_id
                            )
                            if dev_handled:
                                return {"status": "dev_agent_triggered", "user": user_display_name}
                        prompt_to_process = voice_transcription
                except Exception as e_tr:
                    logger.warning(f"Error procesando nota de voz para DevAgent: {e_tr}")

            # Si es comando /start o /help
            if text_content in ("/start", "/help", "/ayuda"):
                admin_help = ""
                if str(user_id) == "1450113787" or user_display_name.lower() in ["juanma_oms", "jsaavedra"]:
                    admin_help = "• *Modo Desarrollo (DevAgent):* «`/dev Corrige el bug X y corre los tests`»\n"

                welcome_msg = (
                    f"👋 **¡Hola {db_user.username if db_user else first_name}!**\n\n"
                    f"Soy tu **Asesor Inmobiliario Conversacional HIVEX**.\n\n"
                    f"💡 **¿Qué puedes pedirme?**\n"
                    f"• *Buscar oportunidades:* «Busca pisos en Valencia por menos de 150.000€ con más del 20% de descuento»\n"
                    f"• *Audios de voz:* ¡Grábame una nota de voz con lo que necesitas!\n"
                    f"• *Análisis de Zonas:* «Cómo está el distrito centro de Madrid y qué precios m² hay»\n"
                    f"• *Cálculo de ROI / BTL:* «Qué rentabilidad de alquiler puedo esperar en Alicante»\n"
                    f"• *Scoring y Comparativa:* «Cuáles son las 3 mejores oportunidades en Zaragoza por score»\n"
                    f"• *Alertas Programadas:* «Avísame cuando salga una vivienda en Málaga con yield > 8%»\n"
                    f"{admin_help}\n"
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
                target_count = int(res.get("criteria", {}).get("target_count") or 20)
                cards_to_send = matched_opps[:target_count]

                # 1. Notificación previa: si hubo ampliación geográfica (is_relaxed), enviar aviso explícito FIRST
                if res.get("is_relaxed"):
                    crit = res.get("criteria", {})
                    zone_label = crit.get("zone_or_neighborhood") or crit.get("postal_code") or "la micro-zona solicitada"
                    prov_label = crit.get("province") or "Madrid"
                    exact_count = res.get("exact_zone_count", 0)
                    if exact_count == 0:
                        warning_msg = (
                            f"⚠️ <b>Aviso de Búsqueda HIVEX</b>\n\n"
                            f"No constan activos exactos registrados en la micro-dirección: <b>{zone_label}</b>.\n\n"
                            f"Para satisfacer tu petición y no dejar la consulta vacía, hemos ampliado la búsqueda al ámbito de la provincia / corona metropolitana de <b>{prov_label}</b>, seleccionando las <b>{len(cards_to_send)} mejores oportunidades</b> disponibles por scoring de rentabilidad y descuento.\n\n"
                            f"<i>A continuación volcamos las {len(cards_to_send)} fichas interactivas completas:</i>"
                        )
                    else:
                        warning_msg = (
                            f"🎯 <b>Resultados de Búsqueda HIVEX</b>\n\n"
                            f"Se han localizado <b>{exact_count} oportunidades exclusivas</b> en la micro-zona de <b>{zone_label}</b>.\n\n"
                            f"Para completar tu solicitud con las <b>{len(cards_to_send)} mejores opciones</b> del mercado, hemos añadido las más rentables de la corona metropolitana de <b>{prov_label}</b>.\n\n"
                            f"<i>A continuación volcamos las {len(cards_to_send)} fichas interactivas (las {exact_count} primeras corresponden a la micro-zona exacta):</i>"
                        )
                    await self.send_message(chat_id, warning_msg, parse_mode="HTML", reply_to_message_id=message_id)
                    await asyncio.sleep(1.2)
                elif intro_text:
                    await self.send_message(chat_id, intro_text, parse_mode="HTML", reply_to_message_id=message_id)
                    await asyncio.sleep(0.5)
                else:
                    await self.send_message(chat_id, res["response_text"], parse_mode="HTML", reply_to_message_id=message_id)
                    await asyncio.sleep(0.5)

                # 2. Despachar exactamente las oportunidades solicitadas garantizando la entrega íntegra
                for idx, opp in enumerate(cards_to_send):
                    sent = await self.send_photo_card(chat_id=chat_id, opp=opp)
                    if not sent:
                        logger.warning(f"[Advisor Bot] Tarjeta {idx+1}/{len(cards_to_send)} ({opp.get('id')}) falló en primer intento. Reintentando...")
                        await asyncio.sleep(1.2)
                        await self.send_photo_card(chat_id=chat_id, opp=opp)
                    await asyncio.sleep(0.85)

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

    async def handle_dev_agent_command(
        self,
        chat_id: Any,
        user_id: Any,
        user_display_name: str,
        task_text: str,
        message_id: Optional[int] = None
    ) -> bool:
        """
        Dispara el DevAgent autónomo en GitHub Actions para el administrador.
        Permite programar, corregir bugs, ejecutar tests y desplegar cambios desde Telegram.
        """
        str_user_id = str(user_id) if user_id is not None else ""
        str_chat_id = str(chat_id)
        is_admin = (str_user_id == "1450113787") or (user_display_name.lower() in ["juanma_oms", "jsaavedra"]) or (str_chat_id in ["-1003904392737", "3904392737"])
        if not is_admin:
            await self.send_message(
                chat_id,
                "⛔ <i>El modo de desarrollo autónomo (DevAgent) está reservado exclusivamente para el administrador principal de la plataforma.</i>",
                parse_mode="HTML",
                reply_to_message_id=message_id
            )
            return True

        clean_task = task_text
        clean_task = re.sub(r'^/(dev|agent|desarrollo)(@\w+)?\s*', '', clean_task, flags=re.IGNORECASE).strip()
        clean_task = re.sub(r'^(dev|desarrollo):\s*', '', clean_task, flags=re.IGNORECASE).strip()
        clean_task = re.sub(r'@\w*hivex\w*', '', clean_task, flags=re.IGNORECASE).strip()

        if not clean_task:
            help_msg = (
                "🛠️ <b>HIVEX DevAgent (Modo Desarrollo Autónomo)</b>\n\n"
                "Puedes pedirme cualquier cambio en el código, corrección de bugs, nuevas funciones o ejecución de pruebas.\n\n"
                "💡 <b>Ejemplos de uso:</b>\n"
                "• <code>/dev Revisa tests/ y comprueba que pasen todos</code>\n"
                "• <code>/dev En advisor_engine.py mejora la detección de zonas periféricas</code>\n"
                "• <i>(O grábame un audio de voz empezando por 'desarrollo: ...')</i>\n\n"
                "🚀 El agente arrancará en GitHub Actions, editará los archivos, correrá pytest y subirá el commit a <code>main</code>."
            )
            await self.send_message(chat_id, help_msg, parse_mode="HTML", reply_to_message_id=message_id)
            return True

        gh_token = getattr(settings, "GITHUB_TOKEN", "") or os.getenv("GITHUB_TOKEN", "")
        repo = getattr(settings, "GITHUB_REPO", "") or os.getenv("GITHUB_REPO", "kubicatrading/hivex-realestate-spain")

        if not gh_token:
            missing_msg = (
                "⚠️ <b>Falta configurar GITHUB_TOKEN</b>\n\n"
                "Para poder disparar el DevAgent autónomo en GitHub Actions desde Telegram, es necesario añadir un "
                "<b>Personal Access Token (Classic)</b> con permisos <code>repo</code> y <code>workflow</code> en las variables de entorno de Vercel.\n\n"
                "1. En GitHub: <b>Settings ➔ Developer Settings ➔ Personal access tokens ➔ Tokens (classic)</b>\n"
                "2. Genera un token marcando <code>repo</code> y <code>workflow</code>\n"
                "3. Añádelo como <code>GITHUB_TOKEN</code> en Vercel."
            )
            await self.send_message(chat_id, missing_msg, parse_mode="HTML", reply_to_message_id=message_id)
            return True

        # Disparar workflow en GitHub Actions vía API REST
        url = f"https://api.github.com/repos/{repo}/actions/workflows/dev_agent.yml/dispatches"
        headers = {
            "Authorization": f"Bearer {gh_token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        payload = {
            "ref": "main",
            "inputs": {
                "task": clean_task,
                "telegram_chat_id": str(chat_id),
                "telegram_message_id": str(message_id) if message_id else ""
            }
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(url, json=payload, headers=headers)
                if res.status_code == 204:
                    confirm_msg = (
                        f"🚀 <b>¡DevAgent activado en GitHub Actions!</b>\n\n"
                        f"🎯 <b>Tarea:</b> <i>{html.escape(clean_task)}</i>\n\n"
                        f"📦 <b>Entorno:</b> GitHub Actions (Ubuntu Cloud Runner)\n"
                        f"⏳ El agente está clonando el repositorio, analizando el código y preparando los cambios...\n\n"
                        f"📲 <i>Te notificaré por este mismo chat en cuanto termine la ejecución y los tests pasen.</i>"
                    )
                    await self.send_message(chat_id, confirm_msg, parse_mode="HTML", reply_to_message_id=message_id)
                    return True
                else:
                    err_msg = f"❌ Error comunicando con GitHub Actions ({res.status_code}):\n<code>{html.escape(res.text[:200])}</code>"
                    await self.send_message(chat_id, err_msg, parse_mode="HTML", reply_to_message_id=message_id)
                    return True
        except Exception as e_gh:
            logger.error(f"Error disparando GitHub Actions: {e_gh}")
            await self.send_message(chat_id, f"❌ Error disparando DevAgent: {html.escape(str(e_gh))}", parse_mode="HTML", reply_to_message_id=message_id)
            return True

    async def handle_toggle_alert_command(
        self,
        chat_id: Any,
        user_id: Any,
        user_display_name: str,
        text_content: str,
        message_id: Optional[int] = None
    ) -> bool:
        """
        Interpreta comandos conversacionales en el grupo de Telegram para activar,
        pausar o listar búsquedas/alertas del módulo visual de oportunidades.
        Retorna True si el mensaje fue un comando de alerta y se procesó.
        """
        import re
        txt = text_content.strip().lower()

        # Regex para detectar intenciones sobre alertas/búsquedas
        list_match = bool(re.search(r'\b(mis alertas|alertas activas|qué alertas|que alertas|ver alertas|listar alertas|estado de alertas|/alertas)\b', txt))
        
        deact_verbs = r'(desactiva|desactivar|pausa|pausar|inactiva|inactivar|deten|detén|detener|cancela|cancelar|apaga|apagar|silencia|silenciar)'
        act_verbs = r'(activa|activar|reanuda|reanudar|reactiva|reactivar|enciende|encender|habilita|habilitar)'
        alert_nouns = r'(?:la\s+|las\s+|mi\s+|mis\s+)?(?:alerta|alertas|búsqueda|busqueda|búsquedas|busquedas|radar)'

        is_deactivate = bool(re.search(rf'\b{deact_verbs}\b(?:\s+{alert_nouns})?', txt) and any(w in txt for w in ["alerta", "busqueda", "búsqueda", "radar"])) or txt.startswith("/pausar") or txt.startswith("/desactivar")
        is_activate = bool(re.search(rf'\b{act_verbs}\b(?:\s+{alert_nouns})?', txt) and any(w in txt for w in ["alerta", "busqueda", "búsqueda", "radar"])) or txt.startswith("/activar") or txt.startswith("/reanudar")

        if not (list_match or is_deactivate or is_activate):
            return False

        with SessionLocal() as db:
            from app.db.models import SavedConsultation
            from sqlalchemy import or_

            # Recuperar consultas para este chat o usuario
            user_conds = [SavedConsultation.telegram_chat_id == str(chat_id)]
            if user_display_name:
                user_conds.append(SavedConsultation.user_name.ilike(user_display_name.strip()))

            consultations = db.query(SavedConsultation).filter(
                or_(*user_conds),
                SavedConsultation.matched_opportunity_ids_json.isnot(None),
                SavedConsultation.matched_opportunity_ids_json != "[]",
                SavedConsultation.matched_count > 0
            ).order_by(SavedConsultation.id.desc()).all()

            if not consultations:
                msg = (
                    f"ℹ️ No he encontrado búsquedas ni alertas guardadas registradas para este chat o usuario (<b>{html.escape(user_display_name)}</b>).\n\n"
                    f"Puedes crear una nueva simplemente pidiéndome lo que buscas (ejemplo: <i>«Búscame fincas rústicas en Madrid con buena rentabilidad»</i>)."
                )
                await self.send_message(chat_id, msg, parse_mode="HTML", reply_to_message_id=message_id)
                return True

            # Caso 1: Listar alertas
            if list_match:
                lines = [f"📋 <b>ESTADO DE TUS BÚSQUEDAS Y ALERTAS (HIVEX):</b>\n"]
                for c in consultations[:10]:
                    status_badge = "🟢 <b>ACTIVA</b>" if c.is_active else "⏸️ <b>PAUSADA</b>"
                    lines.append(
                        f"• #{c.id} {status_badge} — <b>«{html.escape(c.title or 'Búsqueda')}»</b>\n"
                        f"  <i>{html.escape(c.description[:80])}...</i>\n"
                        f"  (Total oportunidades vinculadas: {c.matched_count})"
                    )
                lines.append(
                    f"\n💡 <i>Para pausar o activar una búsqueda di: «pausar alerta #ID» o «activar alerta #ID».</i>"
                )
                await self.send_message(chat_id, "\n".join(lines), parse_mode="HTML", reply_to_message_id=message_id)
                return True

            # Caso 2 y 3: Activar o Desactivar
            target_status = True if is_activate else False
            action_word = "activada" if target_status else "pausada"
            icon = "▶️" if target_status else "⏸️"

            # Intentar identificar consulta específica por ID numérico (#12, 12)
            id_match = re.search(r'#?(\d+)', txt)
            target_consultation = None
            if id_match:
                cand_id = int(id_match.group(1))
                target_consultation = next((c for c in consultations if c.id == cand_id), None)

            # Si no hay ID, buscar por coincidencia en texto o título (ej. "fincas", "guadalix", "madrid")
            if not target_consultation:
                clean_term = re.sub(rf'\b({deact_verbs}|{act_verbs}|{alert_nouns}|de|en|por|para|la|el|los|las)\b', ' ', txt).strip()
                if len(clean_term) >= 3:
                    for c in consultations:
                        c_text = f"{c.title} {c.description}".lower()
                        if clean_term in c_text:
                            target_consultation = c
                            break

            # Si aún no hay target, seleccionar la más reciente
            if not target_consultation:
                target_consultation = consultations[0]

            target_consultation.is_active = target_status
            target_consultation.updated_at = datetime.utcnow()
            db.commit()

            reply = (
                f"{icon} <b>Alerta {action_word.capitalize()}</b>\n\n"
                f"He {action_word} la búsqueda: <b>«{html.escape(target_consultation.title or 'Búsqueda')}»</b> (ID #{target_consultation.id}).\n"
                f"Criterio: <i>«{html.escape(target_consultation.description[:100])}...»</i>\n\n"
            )
            if target_status:
                reply += "🔔 El rastreador diario de HIVEX te notificará en este grupo cuando descubra nuevas oportunidades que no estuvieran en la plataforma (hasta 20 al día).\n\n"
                reply += f"💡 <i>Para pausarla cuando quieras, escribe: «pausar alerta #{target_consultation.id}».</i>"
            else:
                reply += "🔕 No recibirás más notificaciones diarias automáticas de esta búsqueda mientras esté en pausa.\n\n"
                reply += f"💡 <i>Para reactivarla cuando quieras, escribe: «activar alerta #{target_consultation.id}».</i>"

            await self.send_message(chat_id, reply, parse_mode="HTML", reply_to_message_id=message_id)
            return True

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
