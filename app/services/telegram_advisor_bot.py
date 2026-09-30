"""
HIVEX Telegram Conversational Real Estate Advisor Service
Gestiona la recepción de mensajes de texto y notas de voz, autenticación de usuarios,
interacción conversacional y ejecución del motor asesor inmobiliario.
"""

import os
import json
import logging
import asyncio
from typing import Optional, Dict, Any, Tuple
import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.db.models import User
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
        self._polling_task: Optional[asyncio.Task] = None
        self._is_polling = False

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

        url = f"{self.api_base}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": False
        }
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    return True
                else:
                    # Si falla por markdown parsing de algún caracter especial, reintentar en texto plano
                    payload.pop("parse_mode", None)
                    res2 = await client.post(url, json=payload)
                    return res2.status_code == 200
        except Exception as e:
            logger.error(f"Error al enviar mensaje a Telegram: {e}")
            return False

    async def send_photo_card(
        self,
        chat_id: int,
        opp: Dict[str, Any],
        reply_to_message_id: Optional[int] = None
    ) -> bool:
        """
        Envía una ficha visual formateada con estilos y foto a Telegram,
        replicando la estética del modal de preview de mapas de HIVEX.
        """
        if not self.token:
            return False

        opp_id = opp.get("id", "")
        web_link = f"{self.platform_url}/?opp_id={opp_id}"
        portal_url = opp.get("url") or web_link
        card_html = advisor_engine.generate_telegram_card_html(opp)

        inline_keyboard = [
            [
                {"text": "🔍 Ver Ficha Completa", "url": web_link},
                {"text": "🌐 Portal Fuente", "url": portal_url}
            ]
        ]
        reply_markup = {"inline_keyboard": inline_keyboard}

        # Intentar enviar con foto si tiene imágenes
        images = opp.get("images") or []
        first_photo = images[0] if (images and isinstance(images, list) and images[0]) else None

        if first_photo and str(first_photo).startswith("http"):
            photo_url = f"{self.api_base}/sendPhoto"
            payload = {
                "chat_id": chat_id,
                "photo": first_photo,
                "caption": card_html,
                "parse_mode": "HTML",
                "reply_markup": reply_markup
            }
            if reply_to_message_id:
                payload["reply_to_message_id"] = reply_to_message_id

            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    res = await client.post(photo_url, json=payload)
                    if res.status_code == 200:
                        return True
                    else:
                        logger.warning(f"sendPhoto falló ({res.status_code}: {res.text}). Reintentando como mensaje HTML...")
            except Exception as e_photo:
                logger.warning(f"Excepción en sendPhoto: {e_photo}")

        # Fallback a send_message con HTML y botones interactivos
        return await self.send_message(
            chat_id=chat_id,
            text=card_html,
            parse_mode="HTML",
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup
        )

    # --------------------------------------------------------------------------
    # 4. GESTIÓN Y PROCESAMIENTO DE UPDATES
    # --------------------------------------------------------------------------
    async def process_update(self, update: Dict[str, Any]) -> Dict[str, Any]:
        """Procesa un update entrante de Telegram (vía Webhook o Polling)."""
        message = update.get("message") or update.get("edited_message")
        if not message:
            return {"status": "ignored", "reason": "No message in update"}

        chat = message.get("chat", {})
        chat_id = chat.get("id")
        from_user = message.get("from", {})
        user_id = from_user.get("id")
        username = from_user.get("username")
        first_name = from_user.get("first_name", "Usuario")
        message_id = message.get("message_id")

        text_content = (message.get("text") or "").strip()
        voice = message.get("voice")
        audio = message.get("audio")

        # Comprobar comandos especiales
        is_link_cmd = text_content.startswith("/vincular") or text_content.startswith("/link")
        link_args = text_content.split(maxsplit=1)[1] if (is_link_cmd and len(text_content.split()) > 1) else None

        db = SessionLocal()
        try:
            # 1. VERIFICAR AUTENTICACIÓN DEL USUARIO
            is_authorized, db_user, auth_reason = self.verify_or_link_user(
                db=db,
                telegram_user_id=user_id,
                telegram_username=username,
                first_name=first_name,
                command_args=link_args
            )

            # Si el usuario intenta auto-vincularse, indicar que debe gestionarse por el administrador
            if is_link_cmd:
                reply = (
                    "ℹ️ **Gestión de Accesos HIVEX**\n\n"
                    "La vinculación y activación de cuentas se gestiona exclusivamente por el administrador de la plataforma.\n\n"
                    "Por favor, contacta con tu administrador para dar de alta tu cuenta o asociar tu ID de Telegram en el portal HIVEX."
                )
                await self.send_message(chat_id, reply, reply_to_message_id=message_id)
                return {"status": "admin_managed_only", "user": username}

            # Si el usuario NO está autorizado, responder con advertencia indicando contactar al administrador
            if not is_authorized:
                unauth_reply = (
                    "⚠️ El usuario que realiza la solicitud no ha sido identificado como un usuario con acceso en el portal inmobiliario de HIVEX.\n\n"
                    "Por favor, contacta con el administrador de la plataforma para obtener acceso."
                )
                await self.send_message(chat_id, unauth_reply, reply_to_message_id=message_id)
                return {"status": "unauthorized", "user_id": user_id, "username": username}

            # 2. PROCESAR MENSAJE (TEXTO O AUDIO)
            audio_bytes = None
            audio_duration = None
            prompt_to_process = text_content

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

            # Ejecutar consulta en el Motor Asesor
            res = await advisor_engine.process_user_query(
                user_name=db_user.username if db_user else (username or first_name),
                telegram_chat_id=str(chat_id),
                telegram_user_id=str(user_id),
                prompt_text=prompt_to_process,
                audio_bytes=audio_bytes,
                audio_duration=audio_duration,
                db=db
            )

            # Enviar la respuesta del Asesor a Telegram con fichas visuales
            matched_opps = res.get("matched_opportunities") or []
            intro_text = res.get("intro_text")

            if matched_opps:
                # 1. Enviar resumen diagnóstico introductorio
                if intro_text:
                    await self.send_message(chat_id, intro_text, parse_mode="HTML", reply_to_message_id=message_id)
                else:
                    await self.send_message(chat_id, res["response_text"], reply_to_message_id=message_id)

                # 2. Despachar fichas fotográficas visuales con foto y botones de acción
                target_count = int(res.get("criteria", {}).get("target_count") or 5)
                for opp in matched_opps[:target_count]:
                    await self.send_photo_card(chat_id=chat_id, opp=opp)

                # 3. Mensaje de cierre confirmando persistencia
                closing_msg = (
                    f"💾 <i>Las fichas han sido registradas de forma persistente en tu base de datos y repositorio de conocimiento HIVEX.</i>\n"
                    f"🔗 <i>Puedes explorarlas interactivamente en la pestaña 'Consultas & Asesor Telegram' del dashboard web.</i>"
                )
                await self.send_message(chat_id, closing_msg, parse_mode="HTML")
            else:
                # Si no hubo matches, despachar el texto de respuesta del asesor
                await self.send_message(chat_id, res["response_text"], reply_to_message_id=message_id)

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
        finally:
            db.close()

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
