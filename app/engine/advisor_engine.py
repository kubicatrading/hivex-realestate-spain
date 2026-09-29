"""
HIVEX Real Estate AI Advisor & Conversational Engine
Proporciona inteligencia conversacional inmobiliaria, análisis financiero de oportunidades,
cálculo de rentabilidades (ROI / BTL), scoring, análisis de barrios/distritos y gestión de alertas.
"""

import os
import re
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
import httpx
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.config import settings
from app.db.models import (
    User,
    Opportunity,
    Auction,
    SavedConsultation,
    TelegramConversationMessage,
    StrategyType
)
from app.connectors.ine_client import INEClient
from app.engine.kpi_calculator import KPICalculator

logger = logging.getLogger(__name__)

SPANISH_PROVINCES = [
    "Álava", "Albacete", "Alicante", "Almería", "Asturias", "Ávila", "Badajoz", "Barcelona",
    "Burgos", "Cáceres", "Cádiz", "Cantabria", "Castellón", "Ciudad Real", "Córdoba", "Cuenca",
    "Girona", "Granada", "Guadalajara", "Guipúzcoa", "Huelva", "Huesca", "Illes Balears", "Jaén",
    "La Rioja", "Las Palmas", "León", "Lleida", "Lugo", "Madrid", "Málaga", "Murcia", "Navarra",
    "Ourense", "Palencia", "Pontevedra", "Salamanca", "Santa Cruz de Tenerife", "Segovia", "Sevilla",
    "Soria", "Tarragona", "Teruel", "Toledo", "Valencia", "Valladolid", "Vizcaya", "Zamora", "Zaragoza"
]

class AdvisorEngine:
    """
    Motor del Asesor Inmobiliario Conversacional HIVEX.
    Permite consultar oportunidades, analizar distritos, calcular ROI/BTL,
    generar scoring y programar alertas a través de Telegram y Web.
    """

    def __init__(self):
        self.ine_client = INEClient()
        self.openai_key = settings.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY", "")
        self.groq_key = settings.GROQ_API_KEY or os.getenv("GROQ_API_KEY", "")
        self.platform_url = settings.PLATFORM_BASE_URL.rstrip("/")

    # --------------------------------------------------------------------------
    # 1. TRANSCRIPCIÓN DE AUDIO (Whisper / Speech-to-Text)
    # --------------------------------------------------------------------------
    async def transcribe_audio(self, audio_bytes: bytes, filename: str = "voice_note.ogg") -> str:
        """
        Transcribe notas de voz y audios de Telegram a texto en español.
        Utiliza OpenAI Whisper o Groq Whisper si las API keys están presentes,
        o un extractor de respaldo.
        """
        if not audio_bytes:
            return ""

        # Intento con OpenAI Whisper API
        if self.openai_key:
            try:
                headers = {"Authorization": f"Bearer {self.openai_key}"}
                files = {"file": (filename, audio_bytes, "audio/ogg")}
                data = {"model": "whisper-1", "language": "es"}
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        "https://api.openai.com/v1/audio/transcriptions",
                        headers=headers,
                        files=files,
                        data=data
                    )
                    if resp.status_code == 200:
                        transcription = resp.json().get("text", "").strip()
                        logger.info(f"Transcripción OpenAI completada: {transcription[:80]}...")
                        return transcription
                    else:
                        logger.error(f"Error OpenAI Whisper: {resp.status_code} - {resp.text}")
            except Exception as e:
                logger.error(f"Excepción en transcripción OpenAI: {e}")

        # Intento con Groq Whisper API (ultra-rápido)
        if self.groq_key:
            try:
                headers = {"Authorization": f"Bearer {self.groq_key}"}
                files = {"file": (filename, audio_bytes, "audio/ogg")}
                data = {"model": "whisper-large-v3", "language": "es"}
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        "https://api.groq.com/openai/v1/audio/transcriptions",
                        headers=headers,
                        files=files,
                        data=data
                    )
                    if resp.status_code == 200:
                        transcription = resp.json().get("text", "").strip()
                        logger.info(f"Transcripción Groq completada: {transcription[:80]}...")
                        return transcription
                    else:
                        logger.error(f"Error Groq Whisper: {resp.status_code} - {resp.text}")
            except Exception as e:
                logger.error(f"Excepción en transcripción Groq: {e}")

        # Si no hay API Key de transcripción configurada
        return "[Audio recibido: Para habilitar transcripción automática de voz con Whisper, configure OPENAI_API_KEY o GROQ_API_KEY en .env]"

    # --------------------------------------------------------------------------
    # 2. PARSING DE INTENCIÓN Y CRITERIOS
    # --------------------------------------------------------------------------
    def parse_query_intent(self, text_input: str) -> Dict[str, Any]:
        """
        Extrae intención, provincia, rangos de precio, tipos de activo,
        descuentos mínimos y solicitud de alertas a partir del lenguaje natural.
        """
        q_lower = text_input.lower()

        # Detección de Provincia / Zona
        matched_province = None
        for prov in SPANISH_PROVINCES:
            prov_clean = prov.lower()
            # Búsqueda de palabra exacta o con acentos
            if re.search(r'\b' + re.escape(prov_clean) + r'\b', q_lower):
                matched_province = prov
                break
            # Variaciones comunes
            if prov_clean == "valencia" and "valència" in q_lower: matched_province = "Valencia"; break
            if prov_clean == "alicante" and "alacant" in q_lower: matched_province = "Alicante"; break
            if prov_clean == "illes balears" and ("baleares" in q_lower or "mallorca" in q_lower or "palma" in q_lower): matched_province = "Illes Balears"; break
            if prov_clean == "vizcaya" and ("bizkaia" in q_lower or "bilbao" in q_lower): matched_province = "Vizcaya"; break
            if prov_clean == "guipúzcoa" and ("gipuzkoa" in q_lower or "san sebastián" in q_lower or "donostia" in q_lower): matched_province = "Guipúzcoa"; break
            if prov_clean == "á lava" or prov_clean == "alava" and "vitoria" in q_lower: matched_province = "Álava"; break
            if prov_clean == "la coruña" or ("coruña" in q_lower): matched_province = "A Coruña"; break

        # Detección de Precio Máximo / Mínimo
        max_price = None
        min_price = None

        # Patrones como "menos de 150000", "hasta 150k", "< 200.000€"
        max_price_match = re.search(r'(?:menos de|hasta|máximo|max|menor a|<|inferior a)\s*(\d+[\d\.,]*)\s*(k|mil|€|euros)?', q_lower)
        if max_price_match:
            val_str = max_price_match.group(1).replace(".", "").replace(",", ".")
            try:
                val = float(val_str)
                unit = (max_price_match.group(2) or "").strip()
                if unit in ("k", "mil") or val < 1000:
                    val *= 1000
                max_price = val
            except ValueError:
                pass

        # Detección de Descuento Mínimo (ej. "más del 20%", "dto > 15%", "descuento superior al 15%")
        min_discount = None
        disc_match = re.search(r'(?:descuento|dto|rebaja|margen)\s*(?:de\s+más\s+de(?:l)?|de(?:l)?|superior\s+a(?:l)?|mayor\s+a(?:l)?|mínimo\s+de(?:l)?|min|más\s+de(?:l)?|>)?\s*(\d+)\s*%', q_lower)
        if disc_match:
            try:
                min_discount = float(disc_match.group(1))
            except ValueError:
                pass
        elif re.search(r'(\d+)\s*%\s*(?:de\s+)?(?:descuento|dto)', q_lower):
            m = re.search(r'(\d+)\s*%\s*(?:de\s+)?(?:descuento|dto)', q_lower)
            if m:
                min_discount = float(m.group(1))

        # Detección de Rentabilidad Mínima BTL (ej. "rentabilidad > 8%", "yield 7%", "rentabilidad superior al 8%")
        min_yield = None
        yield_match = re.search(r'(?:rentabilidad|yield|retorno|roi)\s*(?:de\s+más\s+de(?:l)?|de(?:l)?|superior\s+a(?:l)?|mayor\s+a(?:l)?|mínimo\s+de(?:l)?|min|más\s+de(?:l)?|>)?\s*(\d+(?:[\.,]\d+)?)\s*%', q_lower)
        if yield_match:
            try:
                min_yield = float(yield_match.group(1).replace(",", "."))
            except ValueError:
                pass

        # Detección de Estrategia o Tipo de Propiedad
        property_type = None
        strategy = None
        if any(w in q_lower for w in ["solar", "terreno", "parcela", "suelo", "urbanizable", "pgou"]):
            property_type = "Solar"
            strategy = "LAND_DEVELOPMENT"
        elif any(w in q_lower for w in ["piso", "vivienda", "apartamento", "casa", "chalet", "ático", "duplex"]):
            property_type = "Vivienda"
            strategy = "HOUSE_FLIPPING"
        elif any(w in q_lower for w in ["local", "comercial", "oficina"]):
            property_type = "Local"

        # Detección si es una solicitud de Alerta Programada
        is_alert = False
        if any(w in q_lower for w in ["alerta", "avísame", "avisame", "notifícame", "notificame", "programa una alerta", "guarda esta búsqueda", "guardar alerta"]):
            is_alert = True

        # Clasificación del Tipo de Consulta
        if is_alert:
            query_type = "SCHEDULED_ALERT"
        elif any(w in q_lower for w in ["barrio", "distrito", "zona", "renta media", "demografía", "demografia", "precios de ruzafa", "precios de chamberí", "precio m2 en"]):
            query_type = "DISTRICT_ANALYSIS"
        elif min_yield is not None or any(w in q_lower for w in ["rentabilidad", "yield", "alquiler", "btl", "retorno", "roi"]):
            query_type = "ROI_BTL_CALC"
        elif any(w in q_lower for w in ["mejor", "top", "ranking", "scoring", "compara", "cruce"]):
            query_type = "SCORING_CROSSREF"
        elif any(w in q_lower for w in ["busca", "encuentra", "qué hay", "dime", "oportunidades", "inmuebles", "pisos", "subastas"]):
            query_type = "SEARCH_OPPORTUNITIES"
        else:
            query_type = "SEARCH_OPPORTUNITIES"

        return {
            "query_type": query_type,
            "province": matched_province,
            "property_type": property_type,
            "strategy": strategy,
            "max_price": max_price,
            "min_price": min_price,
            "min_discount": min_discount,
            "min_yield": min_yield,
            "is_alert": is_alert,
            "raw_text": text_input
        }

    # --------------------------------------------------------------------------
    # 3. CARGA Y FILTRADO DE OPORTUNIDADES REALES
    # --------------------------------------------------------------------------
    def get_live_catalog_opportunities(self, db: Optional[Session] = None) -> List[Dict[str, Any]]:
        """
        Carga el conjunto completo de oportunidades verificadas (BD Subastas + Catálogo Market multicanal).
        """
        all_opps = []

        # 1. Carga de base de datos PostgreSQL (Subastas)
        if db:
            try:
                from sqlalchemy.orm import joinedload
                db_opps = db.query(Opportunity).options(
                    joinedload(Opportunity.auction).joinedload(Auction.parcel)
                ).outerjoin(Auction).all()

                for opp in db_opps:
                    auc = opp.auction
                    if not auc:
                        continue
                    if auc.status in ("FINALIZADA", "CONCLUIDA", "CANCELADA", "SUSPENDIDA"):
                        continue
                    if auc.auction_end_date and auc.auction_end_date <= datetime.utcnow():
                        continue

                    disc_pct = round(opp.discount_percentage * 100, 1)
                    profit = max(0.0, round(opp.estimated_reference_value - opp.listing_price, 2))

                    all_opps.append({
                        "id": f"SUB-{auc.id_subasta}",
                        "source_type": "subastas",
                        "strategy": opp.strategy.value if hasattr(opp.strategy, "value") else str(opp.strategy),
                        "title": auc.title or "Inmueble en Subasta Pública",
                        "locality": auc.locality or "España",
                        "province": auc.province or "España",
                        "listing_price": opp.listing_price,
                        "estimated_reference_value": opp.estimated_reference_value,
                        "discount_percentage": disc_pct,
                        "potential_gross_profit": profit,
                        "rental_yield": getattr(opp, "rental_yield", 0.0) or 0.0,
                        "estimated_monthly_rent": getattr(opp, "estimated_monthly_rent", 0.0) or 0.0,
                        "overall_score": opp.overall_score or 75.0,
                        "poi_score": opp.poi_score or 70.0,
                        "surface_m2": getattr(auc, "surface_m2", None) or 90.0,
                        "url": f"https://subastas.boe.es/detalleSubasta.php?idSub={auc.id_subasta}",
                        "images": json.loads(auc.images_json) if getattr(auc, "images_json", None) else []
                    })
            except Exception as e_db:
                logger.warning(f"Aviso cargando subastas en Asesor: {e_db}")

        # 2. Carga de Catálogo Market Verificado
        catalog_path = "app/data/verified_market_catalog.json"
        if os.path.exists(catalog_path):
            try:
                with open(catalog_path, "r", encoding="utf-8") as f:
                    market_items = json.load(f)
                for item in market_items:
                    price = float(item.get("price") or item.get("listing_price") or 0)
                    mkt_val = float(item.get("estimated_reference_value") or item.get("market_valuation") or price)
                    disc = float(item.get("discount_percentage") or 0)
                    if disc <= 0 and mkt_val > price and mkt_val > 0:
                        disc = round(((mkt_val - price) / mkt_val) * 100, 1)

                    all_opps.append({
                        "id": str(item.get("id")),
                        "source_type": "market",
                        "strategy": item.get("strategy", "HOUSE_FLIPPING"),
                        "title": item.get("title", "Oportunidad Residencial"),
                        "locality": item.get("locality", "España"),
                        "province": item.get("province", "España"),
                        "listing_price": price,
                        "estimated_reference_value": mkt_val,
                        "discount_percentage": disc,
                        "potential_gross_profit": max(0.0, round(mkt_val - price, 2)),
                        "rental_yield": float(item.get("rental_yield") or 0.0),
                        "estimated_monthly_rent": float(item.get("estimated_monthly_rent") or 0.0),
                        "overall_score": float(item.get("overall_score") or 80.0),
                        "poi_score": float(item.get("poi_score") or 75.0),
                        "surface_m2": float(item.get("surface_m2") or 80.0),
                        "url": item.get("url") or item.get("portal_url") or "",
                        "images": item.get("images") or []
                    })
            except Exception as e_cat:
                logger.warning(f"Aviso cargando catálogo de mercado: {e_cat}")

        return all_opps

    # --------------------------------------------------------------------------
    # 4. FILTRADO INTELIGENTE SEGÚN CRITERIOS
    # --------------------------------------------------------------------------
    def filter_opportunities(self, opportunities: List[Dict[str, Any]], criteria: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Filtra y ordena oportunidades según los criterios extraídos."""
        filtered = opportunities

        # Provincia
        if criteria.get("province"):
            target_prov = criteria["province"].lower()
            filtered = [
                o for o in filtered
                if target_prov in o.get("province", "").lower() or target_prov in o.get("locality", "").lower()
            ]

        # Estrategia / Tipo de Propiedad
        if criteria.get("strategy"):
            filtered = [o for o in filtered if o.get("strategy") == criteria["strategy"]]

        # Precio Máximo
        if criteria.get("max_price"):
            filtered = [o for o in filtered if o.get("listing_price", 0) <= criteria["max_price"]]

        # Precio Mínimo
        if criteria.get("min_price"):
            filtered = [o for o in filtered if o.get("listing_price", 0) >= criteria["min_price"]]

        # Descuento Mínimo
        if criteria.get("min_discount"):
            filtered = [o for o in filtered if o.get("discount_percentage", 0) >= criteria["min_discount"]]

        # Rentabilidad Mínima BTL
        if criteria.get("min_yield"):
            filtered = [o for o in filtered if o.get("rental_yield", 0) >= criteria["min_yield"]]

        # Ordenar por mejor Score Global y luego por Descuento
        filtered.sort(
            key=lambda x: (x.get("overall_score", 0), x.get("discount_percentage", 0)),
            reverse=True
        )

        return filtered

    # --------------------------------------------------------------------------
    # 5. GENERACIÓN DE ANÁLISIS Y RESPUESTA ASESORA
    # --------------------------------------------------------------------------
    def generate_advisor_response(
        self,
        user_name: str,
        criteria: Dict[str, Any],
        matched_opps: List[Dict[str, Any]],
        conversation_context: Optional[List[Dict[str, str]]] = None
    ) -> Tuple[str, str, str]:
        """
        Genera la respuesta del Asesor Inmobiliario formateada en Markdown para Telegram,
        junto con el título del grupo y el resumen ejecutivo.
        """
        q_type = criteria.get("query_type", "SEARCH_OPPORTUNITIES")
        prov = criteria.get("province") or "España"
        count = len(matched_opps)

        # Generar Título amigable para el Repositorio de la plataforma
        if criteria.get("is_alert"):
            title = f"🔔 Alerta: {criteria.get('property_type') or 'Inmuebles'} en {prov}"
            if criteria.get("max_price"):
                title += f" < {int(criteria['max_price']):,}€".replace(",", ".")
            if criteria.get("min_discount"):
                title += f" (dto ≥ {int(criteria['min_discount'])}%)"
        elif q_type == "DISTRICT_ANALYSIS":
            title = f"📊 Análisis de Barrio / Zona: {prov}"
        elif q_type == "ROI_BTL_CALC":
            title = f"📈 Rentabilidad BTL & Retorno en {prov}"
        elif q_type == "SCORING_CROSSREF":
            title = f"🌟 Scoring & Comparativa Top en {prov}"
        else:
            title = f"🔍 Búsqueda: {criteria.get('property_type') or 'Oportunidades'} en {prov}"
            if criteria.get("max_price"):
                title += f" (< {int(criteria['max_price']):,}€)".replace(",", ".")

        # Construcción del Mensaje Conversacional de Telegram
        lines = []

        if criteria.get("is_alert"):
            lines.append(f"🔔 **¡ALERTA REGISTRADA EN HIVEX!**")
            lines.append(f"Hola **{user_name}**, he guardado tu solicitud en el repositorio de alertas de la plataforma.")
            lines.append(f"Monitorizaremos en tiempo real cualquier nuevo activo que cumpla:")
            if criteria.get("province"): lines.append(f"• **Zona:** {criteria['province']}")
            if criteria.get("max_price"): lines.append(f"• **Presupuesto Máximo:** {criteria['max_price']:,.0f} €")
            if criteria.get("min_discount"): lines.append(f"• **Descuento Mínimo:** {criteria['min_discount']}%")
            if criteria.get("min_yield"): lines.append(f"• **Yield Alquiler Mín:** {criteria['min_yield']}%")
            lines.append("")

        else:
            lines.append(f"💼 **ASESOR INMOBILIARIO HIVEX**")
            lines.append(f"Hola **{user_name}**, he analizado tu consulta sobre el mercado en **{prov}**.")

        # Resumen de Métricas de Mercado en la Zona
        if matched_opps:
            avg_price = sum(o.get("listing_price", 0) for o in matched_opps) / count
            avg_disc = sum(o.get("discount_percentage", 0) for o in matched_opps) / count
            avg_yield = sum(o.get("rental_yield", 0) for o in matched_opps) / count

            lines.append(f"\n📊 **Diagnóstico del Mercado ({count} oportunidad{'es' if count != 1 else ''} localizadas):**")
            lines.append(f"• **Precio medio de entrada:** {avg_price:,.0f} €")
            lines.append(f"• **Descuento medio vs mercado:** {avg_disc:.1f}%")
            if avg_yield > 0:
                lines.append(f"• **Rentabilidad media estimada (BTL):** {avg_yield:.1f}%")

            # Destacar las mejores oportunidades (Top 3)
            lines.append(f"\n🏆 **Principales Oportunidades Seleccionadas:**\n")
            for idx, opp in enumerate(matched_opps[:3], start=1):
                p = opp.get("listing_price", 0)
                mkt = opp.get("estimated_reference_value", p)
                disc = opp.get("discount_percentage", 0)
                disc_sign = f"(-{disc:.1f}%)" if disc > 0 else f"(+{abs(disc):.1f}%)"
                strat = "🔨 Flipping" if opp.get("strategy") == "HOUSE_FLIPPING" else "🏗️ Suelo/PGOU"
                score = opp.get("overall_score", 80)
                opp_id = opp.get("id", "")

                web_link = f"{self.platform_url}/?opp_id={opp_id}"

                lines.append(f"**{idx}. {opp.get('title', 'Inmueble')}**")
                lines.append(f"   📍 {opp.get('locality', 'N/D')}, {opp.get('province', 'N/D')} | {strat}")
                lines.append(f"   💰 **Precio:** {p:,.0f} € `{disc_sign}` vs Mkt: {mkt:,.0f} €")
                if opp.get("rental_yield", 0) > 0:
                    lines.append(f"   📈 **Yield Alquiler:** {opp['rental_yield']:.1f}% ({opp.get('estimated_monthly_rent', 0):,.0f} €/mes)")
                lines.append(f"   ⭐ **Score HIVEX:** {score:.0f}/100 | Margen: {opp.get('potential_gross_profit', 0):,.0f} €")
                lines.append(f"   🔗 [Abrir Ficha en HIVEX Plataforma]({web_link})\n")

            if count > 3:
                lines.append(f"➕ *Hay {count - 3} oportunidades más disponibles en este grupo dentro de la plataforma.*")

        else:
            lines.append(f"\n🔍 No he encontrado activos activos que cumplan con todos los filtros exactos en este instante.")
            lines.append(f"💡 **Recomendación del Asesor:**")
            lines.append(f"He registrado la búsqueda en tu repositorio de HIVEX para notificarte en cuanto aparezca una oportunidad en {prov}.")

        lines.append(f"\n📂 *Consulta guardada en la pestaña 'Consultas & Asesor Telegram' del dashboard web.*")

        response_text = "\n".join(lines)

        # Resumen ejecutivo para almacenar en la ficha
        ai_summary = (
            f"Consulta de {user_name} sobre {prov}. "
            f"Se identificaron {count} oportunidades con un descuento medio del {avg_disc if matched_opps else 0:.1f}%. "
            f"Estrategia recomendada: análisis de puja y cruce con demanda de alquiler."
        )

        return response_text, title, ai_summary

    # --------------------------------------------------------------------------
    # 6. MÉTODO PRINCIPAL DE PROCESAMIENTO
    # --------------------------------------------------------------------------
    async def process_user_query(
        self,
        user_name: str,
        telegram_chat_id: str,
        telegram_user_id: Optional[str] = None,
        prompt_text: str = "",
        audio_bytes: Optional[bytes] = None,
        audio_duration: Optional[int] = None,
        db: Optional[Session] = None
    ) -> Dict[str, Any]:
        """
        Ejecuta el ciclo completo:
        1. Transcribe audio si procede.
        2. Extrae intención y criterios.
        3. Filtra el catálogo en vivo.
        4. Genera respuesta de asesor inmobiliario.
        5. Persiste mensaje y grupo de consulta en Base de Datos.
        """
        is_voice = bool(audio_bytes)
        transcription = None

        if is_voice and audio_bytes:
            transcription = await self.transcribe_audio(audio_bytes)
            final_prompt = transcription if transcription else prompt_text
        else:
            final_prompt = prompt_text.strip()

        if not final_prompt:
            final_prompt = "Consultar oportunidades destacadas"

        # 1. Parse de criterios
        criteria = self.parse_query_intent(final_prompt)

        # 2. Obtener catálogo y filtrar
        all_opps = self.get_live_catalog_opportunities(db=db)
        matched_opps = self.filter_opportunities(all_opps, criteria)

        # Si el filtro fue muy estricto y devolvió 0, obtener top 5 de la provincia o general
        if not matched_opps and criteria.get("province"):
            relaxed_criteria = {"province": criteria["province"]}
            matched_opps = self.filter_opportunities(all_opps, relaxed_criteria)[:5]

        # 3. Generar respuesta
        response_text, title, ai_summary = self.generate_advisor_response(
            user_name=user_name,
            criteria=criteria,
            matched_opps=matched_opps
        )

        # 4. Persistir en Base de Datos
        saved_consultation_id = None
        if db:
            try:
                # Buscar id del usuario si existe
                db_user = None
                if telegram_user_id:
                    db_user = db.query(User).filter(User.telegram_id == str(telegram_user_id)).first()
                if not db_user and user_name:
                    db_user = db.query(User).filter(
                        (User.username.ilike(user_name)) | (User.telegram_username.ilike(user_name))
                    ).first()

                # Guardar en memoria de conversación
                msg_user = TelegramConversationMessage(
                    telegram_chat_id=str(telegram_chat_id),
                    telegram_user_id=str(telegram_user_id) if telegram_user_id else None,
                    user_id=db_user.id if db_user else None,
                    role="user",
                    content_type="voice" if is_voice else "text",
                    content=final_prompt,
                    transcription=transcription,
                    duration_seconds=audio_duration
                )
                db.add(msg_user)

                msg_assistant = TelegramConversationMessage(
                    telegram_chat_id=str(telegram_chat_id),
                    telegram_user_id=str(telegram_user_id) if telegram_user_id else None,
                    user_id=db_user.id if db_user else None,
                    role="assistant",
                    content_type="query_result",
                    content=response_text
                )
                db.add(msg_assistant)

                # Guardar en repositorio de Consultas & Alertas
                matched_ids = [o.get("id") for o in matched_opps[:20]]
                consultation = SavedConsultation(
                    user_id=db_user.id if db_user else None,
                    user_name=user_name,
                    telegram_chat_id=str(telegram_chat_id),
                    title=title,
                    description=final_prompt,
                    query_type=criteria.get("query_type", "SEARCH_OPPORTUNITIES"),
                    criteria_json=json.dumps(criteria, ensure_ascii=False),
                    matched_opportunity_ids_json=json.dumps(matched_ids),
                    matched_count=len(matched_opps),
                    ai_summary=ai_summary,
                    is_alert=criteria.get("is_alert", False),
                    alert_frequency="DAILY" if criteria.get("is_alert") else None,
                    is_active=True
                )
                db.add(consultation)
                db.commit()
                db.refresh(consultation)
                saved_consultation_id = consultation.id
                logger.info(f"Consulta persistida con éxito en BD con ID #{saved_consultation_id}")
            except Exception as e_save:
                logger.error(f"Error al persistir consulta y conversación en BD: {e_save}")
                db.rollback()

        return {
            "success": True,
            "title": title,
            "response_text": response_text,
            "ai_summary": ai_summary,
            "criteria": criteria,
            "matched_count": len(matched_opps),
            "matched_opportunities": matched_opps[:20],
            "saved_consultation_id": saved_consultation_id,
            "transcription": transcription,
            "is_voice": is_voice
        }

advisor_engine = AdvisorEngine()
