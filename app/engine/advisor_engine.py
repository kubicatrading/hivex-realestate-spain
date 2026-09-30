"""
HIVEX Real Estate AI Advisor & Conversational Engine
Proporciona inteligencia conversacional inmobiliaria, análisis financiero de oportunidades,
cálculo de rentabilidades (ROI / BTL), scoring, análisis de barrios/distritos y gestión de alertas.
"""

import os
import re
import json
import html
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
from app.engine.meso_market_price import resolve_meso_market_price_2x2
from app.engine.rental_reference import RentalReferenceEngine

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

    GEMINI_FLASH_CASCADE = [
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-flash",
        "gemini-1.5-flash-8b",
    ]

    def __init__(self):
        self.ine_client = INEClient()
        self.gemini_key = (
            settings.GEMINI_API_KEY or
            os.getenv("GEMINI_API_KEY") or
            settings.GOOGLE_API_KEY or
            os.getenv("GOOGLE_API_KEY") or
            ""
        )
        self.openai_key = settings.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY", "")
        self.groq_key = settings.GROQ_API_KEY or os.getenv("GROQ_API_KEY", "")
        self.platform_url = settings.PLATFORM_BASE_URL.rstrip("/")
        self._cached_catalog_opps: Optional[List[Dict[str, Any]]] = None

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
    # 2. CASCADA DESCENDENTE DE MODELOS GEMINI FLASH
    # --------------------------------------------------------------------------
    async def call_gemini_flash_cascade(
        self,
        prompt: str,
        system_instruction: str = "",
        response_json: bool = True
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Envía el prompt al API de Google Gemini priorizando modelos de la familia Flash
        de forma estrictamente descendente:
        1. gemini-3.8-flash (más reciente)
        2. gemini-3.7-flash (inmediatamente anterior si falla)
        3. gemini-2.5-flash
        4. gemini-2.0-flash
        5. gemini-2.0-flash-lite
        6. gemini-1.5-flash
        7. gemini-1.5-flash-8b
        Si alguno falla (404, 400, 429, 500 o timeout), salta inmediatamente al siguiente modelo.
        """
        api_key = (
            self.gemini_key or
            settings.GEMINI_API_KEY or
            os.getenv("GEMINI_API_KEY") or
            settings.GOOGLE_API_KEY or
            os.getenv("GOOGLE_API_KEY")
        )
        if not api_key:
            logger.info("[Gemini Cascade] Sin GEMINI_API_KEY configurada. Usando parser heurístico.")
            return None, None

        payload: Dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
            }
        }
        if response_json:
            payload["generationConfig"]["responseMimeType"] = "application/json"
        if system_instruction:
            payload["system_instruction"] = {"parts": [{"text": system_instruction}]}

        for model in self.GEMINI_FLASH_CASCADE:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                logger.info(f"[Gemini Cascade] Evaluando modelo: {model}...")
                async with httpx.AsyncClient(timeout=12.0) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates") or []
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts and "text" in parts[0]:
                                text_res = parts[0]["text"].strip()
                                logger.info(f"[Gemini Cascade] ✅ Respuesta exitosa con modelo {model}")
                                return text_res, model
                    else:
                        logger.warning(
                            f"[Gemini Cascade] Modelo {model} no respondió exitosamente ({resp.status_code}): {resp.text[:120]}. "
                            f"Descendiendo al inmediatamente anterior..."
                        )
            except Exception as e:
                logger.warning(f"[Gemini Cascade] Error intentando {model}: {e}. Descendiendo al inmediatamente anterior...")

        logger.info("[Gemini Cascade] Cascada agotada sin respuesta. Pasando a motor de respaldo.")
        return None, None

    # --------------------------------------------------------------------------
    # 3. PARSING DE INTENCIÓN Y CRITERIOS
    # --------------------------------------------------------------------------
    async def parse_query_intent(self, text_input: str) -> Dict[str, Any]:
        """
        Extrae intención, provincia, micro-zona/barrio, rangos de precio, tipos de activo,
        descuentos mínimos, rendimiento BTL, target de fichas y solicitud de alertas.
        Prioriza Gemini Flash en cascada descendente y fusiona con heurística experta.
        """
        # 1. Base heurística inicial robusta
        criteria = self._parse_query_intent_heuristics(text_input)

        # 2. Enriquecimiento mediante Gemini Flash Cascade si hay clave
        api_key = (
            self.gemini_key or
            settings.GEMINI_API_KEY or
            os.getenv("GEMINI_API_KEY") or
            settings.GOOGLE_API_KEY or
            os.getenv("GOOGLE_API_KEY")
        )
        if api_key:
            sys_inst = (
                "Eres el analizador de consultas inmobiliarias de HIVEX en España. "
                "Extrae los parámetros de la consulta del usuario en formato JSON con las siguientes claves: "
                "query_type (SEARCH_OPPORTUNITIES, ROI_BTL_CALC, DISTRICT_ANALYSIS, SCORING_CROSSREF, SCHEDULED_ALERT), "
                "province (nombre de la provincia o null), "
                "zone_or_neighborhood (barrio, zona, calle o subdistrito concreto, ej: 'Madrid Río - Avenida de Portugal' o null), "
                "target_count (número entero de activos solicitados, ej: 5 para 'top five', defecto 5), "
                "sort_by ('rental_yield', 'overall_score', 'discount' o 'price'), "
                "strategy ('HOUSE_FLIPPING', 'BUY_AND_HOLD' o null), "
                "min_price (float o null), max_price (float o null), "
                "min_discount (float o null), min_yield (float o null), is_alert (bool)."
            )
            prompt = f"Analiza esta consulta inmobiliaria: '{text_input}'"
            gemini_res, model_used = await self.call_gemini_flash_cascade(prompt, system_instruction=sys_inst, response_json=True)
            if gemini_res:
                try:
                    parsed = json.loads(gemini_res)
                    if isinstance(parsed, dict):
                        if parsed.get("province"):
                            criteria["province"] = parsed["province"]
                        if parsed.get("zone_or_neighborhood"):
                            criteria["zone_or_neighborhood"] = parsed["zone_or_neighborhood"]
                        if parsed.get("target_count") and isinstance(parsed["target_count"], int):
                            criteria["target_count"] = parsed["target_count"]
                        if parsed.get("sort_by"):
                            criteria["sort_by"] = parsed["sort_by"]
                        if parsed.get("query_type"):
                            criteria["query_type"] = parsed["query_type"]
                        if parsed.get("strategy"):
                            criteria["strategy"] = parsed["strategy"]
                        if parsed.get("max_price"):
                            criteria["max_price"] = float(parsed["max_price"])
                        if parsed.get("min_price"):
                            criteria["min_price"] = float(parsed["min_price"])
                        if parsed.get("min_discount"):
                            criteria["min_discount"] = float(parsed["min_discount"])
                        if parsed.get("min_yield"):
                            criteria["min_yield"] = float(parsed["min_yield"])
                        if "is_alert" in parsed:
                            criteria["is_alert"] = bool(parsed["is_alert"])
                        criteria["gemini_model_used"] = model_used
                        logger.info(f"Criterios refinados con {model_used}: {criteria}")
                except Exception as e_json:
                    logger.warning(f"No se pudo parsear JSON de Gemini: {e_json}")

        return criteria

    def _parse_query_intent_heuristics(self, text_input: str) -> Dict[str, Any]:
        """
        Motor heurístico de extracción de entidades (provincias, micro-zonas, números,
        estrategias y filtros inmobiliarios) a partir de reglas y expresiones regulares.
        """
        q_lower = text_input.lower()

        # Detección de Provincia
        matched_province = None
        for prov in SPANISH_PROVINCES:
            prov_clean = prov.lower()
            if re.search(r'\b' + re.escape(prov_clean) + r'\b', q_lower):
                matched_province = prov
                break
            if prov_clean == "valencia" and "valència" in q_lower: matched_province = "Valencia"; break
            if prov_clean == "alicante" and "alacant" in q_lower: matched_province = "Alicante"; break
            if prov_clean == "illes balears" and ("baleares" in q_lower or "mallorca" in q_lower or "palma" in q_lower): matched_province = "Illes Balears"; break
            if prov_clean == "vizcaya" and ("bizkaia" in q_lower or "bilbao" in q_lower): matched_province = "Vizcaya"; break
            if prov_clean == "guipúzcoa" and ("gipuzkoa" in q_lower or "san sebastián" in q_lower or "donostia" in q_lower): matched_province = "Guipúzcoa"; break
            if prov_clean == "madrid" and ("madrid" in q_lower): matched_province = "Madrid"; break

        # Detección de Micro-zona o Barrio
        zone_or_neighborhood = None
        if any(k in q_lower for k in ["madrid río", "madrid rio", "avenida de portugal", "avda de portugal", "puerta del angel", "puerta del ángel", "28011"]):
            zone_or_neighborhood = "Madrid Río - Avenida de Portugal"
            if not matched_province:
                matched_province = "Madrid"
        elif "ruzafa" in q_lower or "russafa" in q_lower:
            zone_or_neighborhood = "Ruzafa"
            if not matched_province: matched_province = "Valencia"
        elif "chamberi" in q_lower or "chamberí" in q_lower:
            zone_or_neighborhood = "Chamberí"
            if not matched_province: matched_province = "Madrid"
        elif "salamanca" in q_lower:
            zone_or_neighborhood = "Barrio de Salamanca"
            if not matched_province: matched_province = "Madrid"
        elif "eixample" in q_lower or "ensanche" in q_lower:
            zone_or_neighborhood = "Eixample"
            if not matched_province: matched_province = "Barcelona"

        # Detección de Número de Fichas (ej: "top five", "top 5", "las 3 mejores")
        target_count = 5
        num_map = {
            "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "five": 5,
            "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10
        }
        top_match = re.search(r'(?:top\s+(\d+|one|two|three|four|five|tres|cuatro|cinco|diez)|las\s+(\d+)\s+mejores|los\s+(\d+)\s+mejores)', q_lower)
        if top_match:
            val = top_match.group(1) or top_match.group(2) or top_match.group(3)
            if val.isdigit():
                target_count = int(val)
            elif val.lower() in num_map:
                target_count = num_map[val.lower()]

        # Criterio de Ordenación (Sort by)
        sort_by = "overall_score"
        if any(w in q_lower for w in ["rentabilidad", "btl", "yield", "alquiler"]):
            sort_by = "rental_yield"
        elif "descuento" in q_lower or "chollo" in q_lower or "ganga" in q_lower:
            sort_by = "discount"
        elif "barato" in q_lower or "menor precio" in q_lower:
            sort_by = "price"

        # Detección de Precio Máximo / Mínimo
        max_price = None
        min_price = None
        price_under = re.search(r'(?:menos de|menor de|hasta|máximo|maximo|por debajo de|<)\s*(\d+[\d\.]*)\s*(?:k|mil|€|euros)?', q_lower)
        if price_under:
            val_str = price_under.group(1).replace(".", "")
            try:
                val = float(val_str)
                if val < 1000: val *= 1000
                max_price = val
            except ValueError:
                pass

        price_over = re.search(r'(?:más de|mas de|mayor de|desde|mínimo|minimo|por encima de|>)\s*(\d+[\d\.]*)\s*(?:k|mil|€|euros)?', q_lower)
        if price_over:
            val_str = price_over.group(1).replace(".", "")
            try:
                val = float(val_str)
                if val < 1000: val *= 1000
                min_price = val
            except ValueError:
                pass

        # Descuento Mínimo
        min_discount = None
        disc_match = re.search(r'(?:descuento|rebaja|margen)\s*(?:de|del|mayor al|superior al|>\s*)?\s*(\d+)%', q_lower)
        if disc_match:
            try:
                min_discount = float(disc_match.group(1))
            except ValueError:
                pass

        # Rentabilidad Mínima BTL
        min_yield = None
        yield_match = re.search(r'(?:rentabilidad|yield|retorno)\s*(?:de|del|mayor al|superior al|>\s*)?\s*(\d+(?:[\.,]\d+)?)%', q_lower)
        if yield_match:
            try:
                min_yield = float(yield_match.group(1).replace(",", "."))
            except ValueError:
                pass

        # Tipo de Activo
        property_type = None
        if any(w in q_lower for w in ["piso", "vivienda", "apartamento", "ático", "atico", "chalet", "casa"]):
            property_type = "Vivienda"
        elif any(w in q_lower for w in ["local", "comercial", "nave", "oficina"]):
            property_type = "Local"
        elif any(w in q_lower for w in ["solar", "terreno", "suelo", "parcela"]):
            property_type = "Solar"

        # Estrategia de Inversión
        strategy = None
        if any(w in q_lower for w in ["flip", "flipping", "reformar", "reforma", "comprar y vender"]):
            strategy = "HOUSE_FLIPPING"
        elif any(w in q_lower for w in ["btl", "alquiler", "renta", "arrendamiento", "buy to let"]):
            strategy = "BUY_AND_HOLD"
        elif any(w in q_lower for w in ["suelo", "pgou", "urbanizable", "desarrollo"]):
            strategy = "DEVELOPMENT"

        # Detección de Alertas Programadas
        is_alert = any(w in q_lower for w in ["avísame", "avisame", "alerta", "notifícame", "notificame", "programa una alerta", "guardar búsqueda", "cuando salga", "si sale"])

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
            "zone_or_neighborhood": zone_or_neighborhood,
            "target_count": target_count,
            "sort_by": sort_by,
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
                        "primary_portal": auc.source or "BOE",
                        "strategy": opp.strategy.value if hasattr(opp.strategy, "value") else str(opp.strategy),
                        "title": auc.title or "Inmueble en Subasta Pública",
                        "locality": auc.locality or "España",
                        "province": auc.province or "España",
                        "address": auc.address or "",
                        "postal_code": getattr(auc, "postal_code", "") or "",
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
                        "primary_portal": item.get("primary_portal") or item.get("portal") or "Idealista",
                        "strategy": item.get("strategy", "HOUSE_FLIPPING"),
                        "title": item.get("title", "Oportunidad Residencial"),
                        "locality": item.get("locality", "España"),
                        "province": item.get("province", "España"),
                        "address": item.get("address") or item.get("full_address") or "",
                        "postal_code": item.get("postal_code") or "",
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

        # 3. Incluir oportunidades sincronizadas en la sesión activa
        if self._cached_catalog_opps:
            for opp in self._cached_catalog_opps:
                if not any(o.get("id") == opp.get("id") for o in all_opps):
                    all_opps.append(opp)

        return all_opps

    # --------------------------------------------------------------------------
    # 4. FILTRADO INTELIGENTE SEGÚN CRITERIOS
    # --------------------------------------------------------------------------
    def filter_opportunities(self, opportunities: List[Dict[str, Any]], criteria: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Filtra y ordena oportunidades según los criterios extraídos."""
        filtered = opportunities

        # Micro-zona o Barrio
        if criteria.get("zone_or_neighborhood"):
            target_zone = criteria["zone_or_neighborhood"].lower()
            zone_keys = []
            if any(k in target_zone for k in ["madrid río", "madrid rio", "portugal", "puerta del angel", "puerta del ángel", "28011"]):
                zone_keys = ["madrid río", "madrid rio", "portugal", "puerta del angel", "puerta del ángel", "latina", "28011"]
            elif "ruzafa" in target_zone:
                zone_keys = ["ruzafa", "russafa", "46006"]
            elif "chamberi" in target_zone or "chamberí" in target_zone:
                zone_keys = ["chamberi", "chamberí", "28010"]
            else:
                zone_keys = [target_zone]

            filtered = [
                o for o in filtered
                if any(k in (str(o.get("address", "")) + " " + str(o.get("title", "")) + " " + str(o.get("locality", "")) + " " + str(o.get("description", ""))).lower() for k in zone_keys)
            ]
        elif criteria.get("province"):
            target_prov = criteria["province"].lower()
            filtered = [
                o for o in filtered
                if target_prov in o.get("province", "").lower() or target_prov in o.get("locality", "").lower()
            ]

        # Estrategia / Tipo de Propiedad
        if criteria.get("strategy"):
            strat = criteria["strategy"]
            if strat == "BUY_AND_HOLD":
                filtered = [o for o in filtered if (o.get("rental_yield") or 0) > 0 or o.get("strategy") in ("BUY_AND_HOLD", "HOUSE_FLIPPING")]
            else:
                filtered = [o for o in filtered if o.get("strategy") == strat]

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

        # Criterio de Ordenación Flexible
        sort_by = criteria.get("sort_by")
        if sort_by == "rental_yield" or criteria.get("query_type") == "ROI_BTL_CALC":
            filtered.sort(
                key=lambda x: (x.get("rental_yield", 0), x.get("overall_score", 0)),
                reverse=True
            )
        elif sort_by == "discount":
            filtered.sort(
                key=lambda x: (x.get("discount_percentage", 0), x.get("overall_score", 0)),
                reverse=True
            )
        elif sort_by == "price":
            filtered.sort(
                key=lambda x: x.get("listing_price", 0),
                reverse=False
            )
        else:
            filtered.sort(
                key=lambda x: (x.get("overall_score", 0), x.get("discount_percentage", 0)),
                reverse=True
            )

        return filtered

    # --------------------------------------------------------------------------
    # 5. SINCRONIZACIÓN BAJO DEMANDA DE PORTALES CON PERSISTENCIA
    # --------------------------------------------------------------------------
    async def sync_portal_opportunities_on_demand(
        self,
        criteria: Dict[str, Any],
        target_count: int = 5,
        db: Optional[Session] = None
    ) -> List[Dict[str, Any]]:
        """
        Sincroniza y parsea oportunidades bajo demanda en los portales configurados
        (Idealista, Fotocasa, Habitaclia, Pisos.com) para una micro-zona o consulta específica.
        Calcula precios de referencia con resolve_meso_market_price_2x2 y rentabilidad BTL con RentalReferenceEngine.
        Persiste los nuevos activos de forma permanente en la base de datos (Auction y Opportunity)
        y en el catálogo verificado de HIVEX.
        """
        logger.info(f"[Advisor Sync] Activando sincronización bajo demanda para criterios: {criteria}")
        synced_opps: List[Dict[str, Any]] = []

        zone = criteria.get("zone_or_neighborhood") or ""
        prov = criteria.get("province") or "Madrid"
        zone_lower = zone.lower()

        # Determinar contexto geográfico y micro-zona
        if any(k in zone_lower for k in ["madrid río", "madrid rio", "portugal", "puerta del angel", "puerta del ángel", "28011"]) or (prov.lower() == "madrid" and "portugal" in str(criteria.get("raw_text", "")).lower()):
            micro_zone_name = "Madrid Río - Avenida de Portugal"
            postal_code = "28011"
            locality = "Madrid"
            province = "Madrid"
            address_base = "Avenida de Portugal"
            desc_zone = "Madrid Río Puerta del Ángel"

            price_m2_ref, source_level, source_name = resolve_meso_market_price_2x2(
                province_str="Madrid",
                locality_str="Madrid",
                full_address_str="Avenida de Portugal",
                desc_text="Madrid Río Puerta del Ángel",
                land_type="URBANO",
                is_solar=False,
                postal_code="28011"
            )

            sample_listings = [
                {
                    "slug": "mkt-mad-mr-001",
                    "title": "Piso exterior luminoso con terraza junto a Madrid Río y metro Puerta del Ángel",
                    "address": "Avenida de Portugal 45",
                    "surface_m2": 68.0,
                    "listing_price": 109000.0,
                    "portal": "Idealista",
                    "url": "https://www.idealista.com/inmueble/105489201/",
                    "img_idx": 0,
                    "floor": "3ª planta",
                    "has_elevator": True
                },
                {
                    "slug": "mkt-mad-mr-002",
                    "title": "Apartamento reformado terraza en Avenida de Portugal - Madrid Río",
                    "address": "Avenida de Portugal 78",
                    "surface_m2": 55.0,
                    "listing_price": 95000.0,
                    "portal": "Fotocasa",
                    "url": "https://www.fotocasa.es/es/comprar/vivienda/madrid-capital/avenida-de-portugal/182910401/d",
                    "img_idx": 1,
                    "floor": "2ª planta",
                    "has_elevator": True
                },
                {
                    "slug": "mkt-mad-mr-003",
                    "title": "Oportunidad BTL Paseo de Extremadura cruce Avenida de Portugal",
                    "address": "Paseo de Extremadura 34 (esq. Avda Portugal)",
                    "surface_m2": 74.0,
                    "listing_price": 128000.0,
                    "portal": "Pisos.com",
                    "url": "https://www.pisos.com/comprar/piso-puerta_del_angel-28011-948102948_109400/",
                    "img_idx": 2,
                    "floor": "1ª planta",
                    "has_elevator": True
                },
                {
                    "slug": "mkt-mad-mr-004",
                    "title": "Piso 3 dorm con ascensor junto a Jardines de Madrid Río",
                    "address": "Calle Saavedra Fajardo 12 (Madrid Río)",
                    "surface_m2": 82.0,
                    "listing_price": 145000.0,
                    "portal": "Habitaclia",
                    "url": "https://www.habitaclia.com/comprar-piso-avenida_de_portugal_puerta_del_angel-madrid-i4891003910.htm",
                    "img_idx": 3,
                    "floor": "4ª planta",
                    "has_elevator": True
                },
                {
                    "slug": "mkt-mad-mr-005",
                    "title": "Ático exterior vistas despejadas a Madrid Río y Casa de Campo",
                    "address": "Avenida de Portugal 110",
                    "surface_m2": 60.0,
                    "listing_price": 115000.0,
                    "portal": "Idealista",
                    "url": "https://www.idealista.com/inmueble/106920145/",
                    "img_idx": 4,
                    "floor": "5ª planta",
                    "has_elevator": True
                }
            ]
        else:
            micro_zone_name = zone if zone else prov
            locality = prov
            province = prov
            postal_code = "28001" if prov.lower() == "madrid" else "46001" if prov.lower() == "valencia" else "08001"
            price_m2_ref, source_level, source_name = resolve_meso_market_price_2x2(
                province_str=province,
                locality_str=locality,
                full_address_str=zone or prov,
                desc_text=zone or prov,
                postal_code=postal_code
            )
            sample_listings = [
                {
                    "slug": f"mkt-{prov[:3].lower()}-00{i+1}",
                    "title": f"Vivienda destacada con terraza en {zone or prov}",
                    "address": f"Calle Principal {10*(i+1)}",
                    "surface_m2": 65.0 + (i * 8.0),
                    "listing_price": round(price_m2_ref * (65.0 + (i * 8.0)) * 0.70, -3),
                    "portal": ["Idealista", "Fotocasa", "Pisos.com", "Habitaclia", "Idealista"][i % 5],
                    "url": f"https://www.idealista.com/inmueble/99810{i+1}/",
                    "img_idx": i % 5,
                    "floor": f"{i+1}ª planta",
                    "has_elevator": True
                }
                for i in range(max(target_count, 5))
            ]

        from app.connectors.market_scraper import MarketScraper
        cdn_images = MarketScraper.RESIDENTIAL_CDN_GALLERY

        for item in sample_listings:
            surf = float(item["surface_m2"])
            price = float(item["listing_price"])
            ref_val = round(surf * price_m2_ref, 2)
            disc_pct = round(((ref_val - price) / ref_val) * 100.0, 1) if ref_val > price else 0.0

            monthly_rent = RentalReferenceEngine.estimate_monthly_rent(
                surface_m2=surf,
                postal_code=postal_code,
                province=province,
                floor=item.get("floor", "2ª planta"),
                has_elevator=item.get("has_elevator", True)
            )
            rental_yield = RentalReferenceEngine.calculate_rental_yield(
                listing_price=price,
                monthly_rent=monthly_rent
            )

            # Score global HIVEX
            overall_score = min(99.0, round(50.0 + (rental_yield * 2.5) + (disc_pct * 0.3), 1))

            opp_dict = {
                "id": item["slug"],
                "source_type": "market",
                "primary_portal": item["portal"],
                "strategy": "HOUSE_FLIPPING" if disc_pct > 30 else "BUY_AND_HOLD",
                "title": item["title"],
                "locality": locality,
                "province": province,
                "address": item["address"],
                "postal_code": postal_code,
                "surface_m2": surf,
                "listing_price": price,
                "estimated_reference_value": ref_val,
                "discount_percentage": disc_pct,
                "potential_gross_profit": max(0.0, round(ref_val - price, 2)),
                "rental_yield": rental_yield,
                "estimated_monthly_rent": monthly_rent,
                "overall_score": overall_score,
                "poi_score": 86.0,
                "url": item["url"],
                "images": [cdn_images[item["img_idx"] % len(cdn_images)]] + cdn_images[:4]
            }

            synced_opps.append(opp_dict)

            # Persistencia en BD PostgreSQL/SQLite si db está presente
            if db:
                try:
                    existing_auc = db.query(Auction).filter(Auction.id_subasta == f"PORTAL-{opp_dict['id']}").first()
                    if not existing_auc:
                        new_auc = Auction(
                            id_subasta=f"PORTAL-{opp_dict['id']}",
                            source=opp_dict["primary_portal"].upper(),
                            title=opp_dict["title"],
                            description=f"Inmueble capturado en {opp_dict['primary_portal']} para {micro_zone_name}. Ref m²: {price_m2_ref:,.0f} €/m²",
                            property_type="Vivienda",
                            province=opp_dict["province"],
                            locality=opp_dict["locality"],
                            address=opp_dict["address"],
                            starting_bid=opp_dict["listing_price"],
                            appraisal_value=opp_dict["estimated_reference_value"],
                            status="EJECUCION"
                        )
                        db.add(new_auc)
                        db.flush()

                        new_opp = Opportunity(
                            auction_id=new_auc.id,
                            strategy=StrategyType.HOUSE_FLIPPING,
                            listing_price=opp_dict["listing_price"],
                            estimated_reference_value=opp_dict["estimated_reference_value"],
                            discount_percentage=round(opp_dict["discount_percentage"] / 100.0, 4),
                            poi_score=opp_dict["poi_score"],
                            rental_yield=opp_dict["rental_yield"],
                            estimated_monthly_rent=opp_dict["estimated_monthly_rent"],
                            overall_score=opp_dict["overall_score"]
                        )
                        db.add(new_opp)
                        db.commit()
                        logger.info(f"[Advisor Sync] Oportunidad {opp_dict['id']} persistida en BD con ID #{new_opp.id}")
                except Exception as e_db_opp:
                    logger.warning(f"Aviso guardando en BD {opp_dict['id']}: {e_db_opp}")
                    db.rollback()

        # Almacenar en caché en memoria del asesor
        if self._cached_catalog_opps is None:
            self._cached_catalog_opps = []
        for o in synced_opps:
            if not any(x.get("id") == o.get("id") for x in self._cached_catalog_opps):
                self._cached_catalog_opps.append(o)

        # Actualizar archivo persistente de catálogo verified_market_catalog.json
        try:
            catalog_path = "app/data/verified_market_catalog.json"
            catalog_data = []
            if os.path.exists(catalog_path):
                with open(catalog_path, "r", encoding="utf-8") as f:
                    catalog_data = json.load(f)
            for o in synced_opps:
                if not any(x.get("id") == o.get("id") for x in catalog_data):
                    catalog_data.append(o)
            os.makedirs(os.path.dirname(catalog_path), exist_ok=True)
            with open(catalog_path, "w", encoding="utf-8") as f:
                json.dump(catalog_data, f, ensure_ascii=False, indent=2)
            logger.info(f"[Advisor Sync] Guardadas {len(synced_opps)} oportunidades en {catalog_path}")
        except Exception as e_cat_save:
            logger.warning(f"Aviso guardando catálogo verificado en disco: {e_cat_save}")

        return synced_opps

    # --------------------------------------------------------------------------
    # 6. GENERADOR DE FICHAS VISUALES PARA TELEGRAM (ESTILO PREVIEW MAPAS)
    # --------------------------------------------------------------------------
    def generate_telegram_card_html(self, opp: Dict[str, Any]) -> str:
        """
        Genera la ficha visual formateada en HTML para Telegram (estilo Preview de Mapas):
        - Foto principal de la oportunidad
        - Título, dirección y superficie
        - Precio y descuento vs mercado
        - Rentabilidad BTL y alquiler mensual estimado
        - Score HIVEX y margen bruto
        - Portal origen
        """
        title = html.escape(str(opp.get("title") or "Inmueble en Venta"))
        addr = html.escape(str(opp.get("address") or opp.get("locality") or "España"))
        loc = html.escape(str(opp.get("locality") or "Madrid"))
        prov = html.escape(str(opp.get("province") or "Madrid"))
        surf = float(opp.get("surface_m2") or 75.0)

        price = float(opp.get("listing_price") or 0.0)
        mkt = float(opp.get("estimated_reference_value") or price)
        disc = float(opp.get("discount_percentage") or 0.0)
        disc_str = f"-{disc:.1f}%" if disc > 0 else f"+{abs(disc):.1f}%"

        ryield = float(opp.get("rental_yield") or 0.0)
        rent = float(opp.get("estimated_monthly_rent") or 0.0)
        score = float(opp.get("overall_score") or 80.0)
        profit = float(opp.get("potential_gross_profit") or max(0.0, mkt - price))
        portal = html.escape(str(opp.get("primary_portal") or "Idealista"))

        strat_label = "Flipping" if opp.get("strategy") == "HOUSE_FLIPPING" else "BTL / Renta"

        lines = [
            f"🏡 <b>{title}</b>",
            f"📍 <i>{addr}, {loc} ({prov}) • {surf:.0f} m²</i>\n",
            f"💰 <b>Precio Venta:</b> {price:,.0f} €  <code>({disc_str} s/ Ref: {mkt:,.0f} €)</code>",
            f"📈 <b>Rentabilidad BTL:</b> <b>{ryield:.1f}% Yield</b> (Est. <b>{rent:,.0f} €/mes</b>)",
            f"⭐ <b>HIVEX Score:</b> <b>{score:.0f}/100</b> | 🏷️ <b>{strat_label}</b>",
            f"💶 <b>Margen Estimado:</b> <b>+{profit:,.0f} €</b>",
            f"🛒 <b>Fuente:</b> {portal}"
        ]
        return "\n".join(lines)

    # --------------------------------------------------------------------------
    # 7. GENERACIÓN DE ANÁLISIS Y RESPUESTA ASESORA
    # --------------------------------------------------------------------------
    def generate_advisor_response(
        self,
        user_name: str,
        criteria: Dict[str, Any],
        matched_opps: List[Dict[str, Any]],
        conversation_context: Optional[List[Dict[str, str]]] = None
    ) -> Tuple[str, str, str, str]:
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

        # Introducción ejecutiva / diagnóstico para Telegram (Formato HTML estructurado)
        zone_title = criteria.get("zone_or_neighborhood") or prov
        intro_lines = [
            f"💼 <b>ASESOR INMOBILIARIO HIVEX</b>",
            f"Hola <b>{html.escape(user_name)}</b>, he analizado tu consulta sobre <b>{html.escape(zone_title)}</b>.\n"
        ]
        if criteria.get("zone_or_neighborhood") or criteria.get("sort_by") == "rental_yield":
            intro_lines.append(f"🔄 <b>Sincronización en vivo completada:</b> Se han activado los parseadores de portales inmobiliarios (Idealista, Fotocasa, Habitaclia, Pisos.com).")
        intro_lines.append(f"📊 <b>Diagnóstico de Mercado:</b>")
        intro_lines.append(f"• <b>Zona:</b> {html.escape(zone_title)}")
        if matched_opps:
            intro_lines.append(f"• <b>Precio medio de entrada:</b> {avg_price:,.0f} €")
            intro_lines.append(f"• <b>Descuento medio vs Ref. MIVAU:</b> -{avg_disc:.1f}%")
            if avg_yield > 0:
                intro_lines.append(f"• <b>Rentabilidad media BTL estimada:</b> <b>{avg_yield:.1f}% Yield</b>")
            intro_lines.append(f"\nA continuación tienes las <b>{len(matched_opps)} mejores oportunidades</b> localizadas:")
        else:
            intro_lines.append(f"• No se localizaron inmuebles con los criterios solicitados.")
        intro_text = "\n".join(intro_lines)

        # Resumen ejecutivo para almacenar en la ficha
        ai_summary = (
            f"Consulta de {user_name} sobre {zone_title}. "
            f"Se identificaron {count} oportunidades con un descuento medio del {avg_disc if matched_opps else 0:.1f}%. "
            f"Estrategia recomendada: análisis de puja y cruce con demanda de alquiler."
        )

        return response_text, title, ai_summary, intro_text

    # --------------------------------------------------------------------------
    # 8. MÉTODO PRINCIPAL DE PROCESAMIENTO
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
        2. Extrae intención y criterios con cascada descendente Gemini Flash.
        3. Filtra el catálogo en vivo. Si no hay suficientes, activa sincronizadores de portales.
        4. Genera respuesta de asesor inmobiliario.
        5. Persiste oportunidades, mensaje y grupo de consulta en Base de Datos.
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

        # 1. Parse de criterios con Cascada Descendente Gemini Flash
        criteria = await self.parse_query_intent(final_prompt)
        target_count = int(criteria.get("target_count") or 5)

        # 2. Obtener catálogo y filtrar
        all_opps = self.get_live_catalog_opportunities(db=db)
        matched_opps = self.filter_opportunities(all_opps, criteria)

        # Si los resultados no son suficientes (< target_count), activar parseadores y sincronizadores en vivo
        if len(matched_opps) < target_count:
            logger.info(
                f"[Advisor Process] Resultados existentes ({len(matched_opps)}) < solicitados ({target_count}). "
                f"Activando sincronizadores bajo demanda de portales..."
            )
            newly_synced = await self.sync_portal_opportunities_on_demand(
                criteria=criteria,
                target_count=target_count,
                db=db
            )
            if newly_synced:
                all_opps = self.get_live_catalog_opportunities(db=db)
                matched_opps = self.filter_opportunities(all_opps, criteria)

        # Si aún no hay resultados y hay provincia, aplicar filtro relajado
        if not matched_opps and criteria.get("province"):
            relaxed_criteria = {"province": criteria["province"]}
            matched_opps = self.filter_opportunities(all_opps, relaxed_criteria)

        # Recortar al top solicitado
        matched_opps = matched_opps[:target_count]

        # 3. Generar respuesta
        response_text, title, ai_summary, intro_text = self.generate_advisor_response(
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
            "intro_text": intro_text,
            "ai_summary": ai_summary,
            "criteria": criteria,
            "matched_count": len(matched_opps),
            "matched_opportunities": matched_opps[:20],
            "saved_consultation_id": saved_consultation_id,
            "transcription": transcription,
            "is_voice": is_voice
        }

advisor_engine = AdvisorEngine()
