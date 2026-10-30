import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.engine.meso_market_price import (
    calculate_composite_market_value_2x2,
    extract_plot_surface_m2,
    resolve_meso_market_price_2x2,
)

logger = logging.getLogger("hivex.plot_valuation_backfill")

AUCTION_PLOTS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data",
    "verified_auction_plots.json",
)

CATALOG_JSON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data",
    "verified_market_catalog.json",
)


class PlotValuationEnricher:
    """
    Motor de enriquecimiento semántico con Gemini y valoración F3 (Orden ECO/805/2003)
    para poblar `plot_surface_m2` (m² Terreno) y `solar_m2_price` (Precio €/m² Terreno)
    tanto en oportunidades nuevas como en el backfill histórico de hoy hacia atrás.
    """

    _AUCTION_PLOTS_CACHE: Optional[Dict[str, Dict[str, Any]]] = None

    @classmethod
    def get_api_key(cls) -> str:
        key = (
            os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or ""
        ).strip()
        if not key:
            try:
                from app.core.config import settings
                key = (settings.GEMINI_API_KEY or settings.GOOGLE_API_KEY or "").strip()
            except Exception:
                pass
        return key

    @classmethod
    def load_auction_plots_map(cls, force_reload: bool = False) -> Dict[str, Dict[str, Any]]:
        if cls._AUCTION_PLOTS_CACHE is not None and not force_reload:
            return cls._AUCTION_PLOTS_CACHE
        if os.path.exists(AUCTION_PLOTS_PATH):
            try:
                with open(AUCTION_PLOTS_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    cls._AUCTION_PLOTS_CACHE = data
                    return data
            except Exception as e:
                logger.warning(f"No se pudo leer {AUCTION_PLOTS_PATH}: {e}")
        cls._AUCTION_PLOTS_CACHE = {}
        return cls._AUCTION_PLOTS_CACHE

    @classmethod
    def save_auction_plots_map(cls, data: Dict[str, Dict[str, Any]]) -> None:
        os.makedirs(os.path.dirname(AUCTION_PLOTS_PATH), exist_ok=True)
        with open(AUCTION_PLOTS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        cls._AUCTION_PLOTS_CACHE = data

    @classmethod
    def is_single_family_or_land_candidate(cls, item: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Detecta si un inmueble es un solar/finca o una vivienda unifamiliar/chalet/casa
        (incluso cuando el portal lo etiquetó erróneamente como 'PISO' en una urbanización de chalets).
        Devuelve (es_candidato, subtipo_detectado).
        """
        title = str(item.get("title") or "").lower()
        desc = str(item.get("description") or "").lower()
        prop_type = str(item.get("property_type") or "").lower()
        addr = str(item.get("address") or "").lower()
        loc = str(item.get("locality") or "").lower()
        combined = f"{title} {prop_type} {addr} {loc} {desc}"

        if item.get("is_rustic") or str(item.get("land_type") or "").upper() in ("RÚSTICO", "RUSTICO"):
            return True, "RUSTICO"
        if item.get("is_solar") or "solar" in prop_type or "terreno" in prop_type:
            return True, "SOLAR"
        if any(k in title for k in ("solar ", "terreno ", "parcela ", "finca rústica", "finca rustica", "suelo urbano", "suelo urbanizable")):
            return True, "SOLAR"

        # Chalets / Casas / Unifamiliares
        if any(k in combined for k in ("chalet independiente", "vivienda unifamiliar aislada", "unifamiliar independiente", "villa independiente", "torre independiente")):
            return True, "CHALET_INDEPENDIENTE"
        if any(k in combined for k in ("masía", "masia", "cortijo", "caserío", "caserio", "pazo", "cigarral", "quinta", "casa de campo", "casa rústica", "casa rustica", "finca con casa", "finca recreo")):
            return True, "MASIA_FINCA"
        if any(k in combined for k in ("chalet pareado", "unifamiliar pareada", "casa pareada", "pareado en venta", "pareado de")):
            return True, "CHALET_PAREADO"
        if any(k in combined for k in ("chalet adosado", "casa adosada", "unifamiliar adosada", "adosado en venta", "adosado de", "bungalow")):
            return True, "CHALET_ADOSADO"
        if any(k in combined for k in ("casa de pueblo", "casa tradicional", "casa terrera", "casa mata", "casa solariega", "casa con patio", "casa con jardín", "casa con jardin")):
            return True, "CASA_PUEBLO"
        if any(k in combined for k in ("chalet", "unifamiliar", "villa en venta", "casa en venta", "casa independiente", "casa aislada", "torre en venta")):
            return True, "CHALET_GENERICO"

        # Urbanizaciones de chalets donde algún portal clasifica como "Piso" inmuebles de >180 m²
        single_family_urbs = (
            "urbanización las vegas",
            "urbanizacion las vegas",
            "las vegas - santa maría",
            "las vegas - santa maria",
            "la moraleja",
            "ciudalcampo",
            "santo domingo",
            "fuente del fresno",
            "valdelagua",
            "montepríncipe",
            "monteprincipe",
            "prado largo",
            "las lomas",
            "bonanza",
            "monteclaro",
            "somosaguas",
            "la finca",
            "los peñascales",
            "los penascales",
            "molino de la hoz",
            "nuevo club de golf",
            "parque boadilla",
            "el bosque",
            "campodón",
            "campodon",
            "villafranca del castillo",
            "sotogrande",
            "la zagaleta",
            "sierra blanca",
        )
        surf = float(item.get("surface_m2") or item.get("built_area") or 0.0)
        if any(u in combined for u in single_family_urbs) and surf >= 180.0 and "piso" not in desc[:80]:
            return True, "CHALET_URBANIZACION"

        return False, "NONE"

    @classmethod
    def resolve_plot_surface_fallback(
        cls,
        item: Dict[str, Any],
    ) -> Tuple[float, Optional[str]]:
        """
        Resuelve `plot_surface_m2` combinando extracción literal y estimación pericial
        determinista cuando el texto del portal está truncado o Gemini no está disponible.
        Devuelve (plot_surface_m2, normalized_property_type_or_None).
        """
        title = str(item.get("title") or "")
        desc = str(item.get("description") or "")
        addr = str(item.get("address") or "")
        loc = str(item.get("locality") or "")
        combined_text = f"{title} {addr} {loc} {desc}"

        raw_explicit = float(
            item.get("plot_surface_m2")
            or item.get("plot_m2")
            or item.get("parcel_m2")
            or 0.0
        )
        extracted = extract_plot_surface_m2(
            text=combined_text,
            explicit_plot_m2=raw_explicit if raw_explicit > 0 else None,
        )
        built_m2 = float(item.get("surface_m2") or item.get("built_area") or 0.0)

        is_cand, subtype = cls.is_single_family_or_land_candidate(item)
        norm_prop_type: Optional[str] = None
        if subtype in (
            "CHALET_INDEPENDIENTE",
            "CHALET_PAREADO",
            "CHALET_ADOSADO",
            "CHALET_GENERICO",
            "CHALET_URBANIZACION",
            "MASIA_FINCA",
            "CASA_PUEBLO",
        ):
            cur_pt = str(item.get("property_type") or "").upper()
            if cur_pt in ("", "PISO", "VIVIENDA"):
                norm_prop_type = "Chalet / Casa"

        if extracted > 0:
            return round(extracted, 2), norm_prop_type

        if subtype in ("RUSTICO", "SOLAR"):
            return round(max(built_m2, 100.0), 2), norm_prop_type

        if not is_cand:
            return 0.0, None

        # Estimación pericial urbanística según tipología, municipio/urbanización y m² construidos
        comb_low = combined_text.lower()
        effective_built = built_m2 if built_m2 >= 75.0 else 210.0

        # Urbanizaciones de parcela amplia (1.000 - 2.500 m²)
        large_plot_zones = (
            "la moraleja", "ciudalcampo", "fuente del fresno", "santo domingo",
            "las lomas", "prado largo", "montepríncipe", "monteprincipe",
            "bonanza", "somosaguas", "la finca", "parque boadilla", "el bosque",
            "villafranca del castillo", "molino de la hoz", "los peñascales",
            "los penascales", "torrelodones", "galapagar", "alpedrete",
            "sotogrande", "la zagaleta", "sierra blanca", "pedralbes", "vallvidrera",
        )
        # Urbanizaciones de parcela media residencial (450 - 950 m²)
        medium_plot_zones = (
            "las vegas", "santa maría", "santa maria", "villanueva del pardillo",
            "villanueva de la cañada", "villanueva de la canada", "majadahonda",
            "las rozas", "pozuelo", "valdemarín", "valdemarin", "aravaca",
            "mirasierra", "conde de orgaz", "piovera", "puerta de hierro",
            "arturo soria", "el viso", "boadilla", "tres cantos", "colmenar viejo",
            "san sebastián de los reyes", "alcobendas", "rivas", "villaviciosa",
            " Castelldefels".lower(), "gavà", "gava", "sitges", "sant cugat",
            "matadepera", "marbella", "benahavís", "benahavis", "estepona",
            "mijas", "jávea", "javea", "xàbia", "denia", "dénia", "altea",
            "moraira", "benissa", "calpe", "campello", "san juan", "rocafort",
            "godella", "l'eliana", "la eliana", "bétera", "betera", "paterna",
            "chiclana", "el puerto de santa maría", "mairena", "espartinas",
        )

        is_large_zone = any(z in comb_low for z in large_plot_zones)
        is_medium_zone = any(z in comb_low for z in medium_plot_zones)

        if subtype == "MASIA_FINCA":
            est_plot = max(effective_built * 8.0, 2500.0)
        elif subtype == "CHALET_INDEPENDIENTE":
            if is_large_zone:
                est_plot = max(effective_built * 2.8, 1000.0)
            elif is_medium_zone:
                est_plot = max(effective_built * 2.0, 550.0)
            else:
                est_plot = max(effective_built * 1.85, 450.0)
        elif subtype == "CHALET_URBANIZACION":
            if is_large_zone:
                est_plot = max(effective_built * 2.4, 850.0)
            else:
                est_plot = max(effective_built * 1.9, 500.0)
        elif subtype == "CHALET_PAREADO":
            if is_large_zone:
                est_plot = max(effective_built * 1.65, 450.0)
            elif is_medium_zone:
                est_plot = max(effective_built * 1.4, 340.0)
            else:
                est_plot = max(effective_built * 1.3, 280.0)
        elif subtype == "CHALET_ADOSADO":
            if is_large_zone or is_medium_zone:
                est_plot = max(effective_built * 1.15, 220.0)
            else:
                est_plot = max(effective_built * 1.05, 160.0)
        elif subtype == "CASA_PUEBLO":
            est_plot = max(effective_built * 1.1, 140.0)
        else:
            # CHALET_GENERICO
            if is_large_zone:
                est_plot = max(effective_built * 2.3, 800.0)
            elif is_medium_zone:
                est_plot = max(effective_built * 1.75, 450.0)
            else:
                est_plot = max(effective_built * 1.5, 320.0)

        # Redondear a múltiplos de 5 m² para rigor pericial
        est_plot = round(est_plot / 5.0) * 5.0
        return float(est_plot), norm_prop_type

    @classmethod
    def apply_2x2_plot_valuation_to_item(
        cls,
        item: Dict[str, Any],
        gemini_plot_m2: Optional[float] = None,
        gemini_built_m2: Optional[float] = None,
        gemini_property_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Aplica la superficie de terreno (extraída/estimada por Gemini o respaldo pericial)
        y recalcula el Precio €/m² Terreno (`solar_m2_price`) y la valoración compuesta F3
        (Orden ECO/805/2003) sobre un diccionario de oportunidad.
        """
        if gemini_property_type and gemini_property_type.strip():
            cur_pt = str(item.get("property_type") or "").upper()
            if cur_pt in ("", "PISO", "VIVIENDA") or "CHALET" in gemini_property_type.upper():
                item["property_type"] = gemini_property_type.strip()

        if gemini_built_m2 and gemini_built_m2 > 0:
            cur_surf = float(item.get("surface_m2") or item.get("built_area") or 0.0)
            if cur_surf <= 0:
                item["surface_m2"] = round(float(gemini_built_m2), 2)
                item["built_area"] = round(float(gemini_built_m2), 2)

        fallback_plot_m2, fallback_pt = cls.resolve_plot_surface_fallback(item)
        if fallback_pt and not gemini_property_type:
            item["property_type"] = fallback_pt

        if gemini_plot_m2 is not None and gemini_plot_m2 > 0:
            final_plot_m2 = round(float(gemini_plot_m2), 2)
        else:
            final_plot_m2 = round(float(fallback_plot_m2), 2)

        province = str(item.get("province") or "España")
        locality = str(item.get("locality") or province)
        address = str(item.get("address") or locality)
        postal_code = str(item.get("postal_code") or "")
        desc_full = f"{item.get('title', '')} {item.get('description', '')}"
        land_type = str(item.get("land_type") or "URBANO").upper()
        is_rustic = bool(item.get("is_rustic") or land_type in ("RÚSTICO", "RUSTICO"))
        is_solar = bool(
            item.get("is_solar")
            or str(item.get("property_type") or "").lower() in ("solar", "terreno", "finca rústica", "finca rustica")
        )

        surface_m2 = float(item.get("surface_m2") or item.get("built_area") or 0.0)
        inm_price_m2 = float(item.get("area_m2_price") or item.get("inm_m2_price") or 0.0)
        if inm_price_m2 <= 0:
            inm_price_m2, _, _ = resolve_meso_market_price_2x2(
                province_str=province,
                locality_str=locality,
                full_address_str=address,
                desc_text=desc_full,
                land_type=land_type,
                is_solar=is_solar,
                postal_code=postal_code,
            )
            item["area_m2_price"] = inm_price_m2

        if is_rustic:
            solar_m2_price, _, _ = resolve_meso_market_price_2x2(
                province_str=province,
                locality_str=locality,
                full_address_str=address,
                desc_text=desc_full,
                land_type="RÚSTICO",
                is_solar=True,
                postal_code=postal_code,
            )
            plot_surface_m2 = final_plot_m2 if final_plot_m2 > 0 else max(surface_m2, 1000.0)
            has_house = any(
                k in desc_full.lower()
                for k in ("casa", "chalet", "vivienda", "edificación", "edificacion", "masía", "masia", "cortijo")
            )
            house_sqm = float(item.get("built_area") or item.get("house_m2") or 140.0) if has_house else 0.0
            base_building_value = round(house_sqm * 650.0, 2)
            plot_added_value = round(plot_surface_m2 * solar_m2_price, 2)
            comp_market_val = round(base_building_value + plot_added_value, 2)
            has_plot_valuation = True
        elif is_solar:
            solar_m2_price, _, _ = resolve_meso_market_price_2x2(
                province_str=province,
                locality_str=locality,
                full_address_str=address,
                desc_text=desc_full,
                land_type=land_type,
                is_solar=True,
                postal_code=postal_code,
            )
            plot_surface_m2 = final_plot_m2 if final_plot_m2 > 0 else max(surface_m2, 100.0)
            base_building_value = 0.0
            plot_added_value = round(plot_surface_m2 * solar_m2_price, 2)
            comp_market_val = plot_added_value
            has_plot_valuation = True
        else:
            comp_val = calculate_composite_market_value_2x2(
                built_m2=surface_m2,
                inm_price_m2=inm_price_m2,
                province_str=province,
                locality_str=locality,
                full_address_str=address,
                desc_text=desc_full,
                land_type=land_type,
                is_solar=False,
                postal_code=postal_code,
                explicit_plot_m2=final_plot_m2 if final_plot_m2 > 0 else None,
            )
            plot_surface_m2 = comp_val["plot_m2"]
            solar_m2_price = comp_val["solar_price_m2"]
            base_building_value = comp_val["base_building_value"]
            plot_added_value = comp_val["plot_added_value"]
            comp_market_val = comp_val["estimated_market_value"]
            has_plot_valuation = comp_val["has_plot_valuation"]

        item["plot_surface_m2"] = round(float(plot_surface_m2), 2)
        item["solar_m2_price"] = round(float(solar_m2_price), 2)
        item["base_building_value"] = round(float(base_building_value), 2)
        item["plot_added_value"] = round(float(plot_added_value), 2)
        item["has_plot_valuation"] = bool(has_plot_valuation)

        if isinstance(item.get("census_data"), dict):
            item["census_data"]["plot_surface_m2"] = item["plot_surface_m2"]
            item["census_data"]["solar_m2_price"] = item["solar_m2_price"]
            item["census_data"]["base_building_value"] = item["base_building_value"]
            item["census_data"]["plot_added_value"] = item["plot_added_value"]
            item["census_data"]["has_plot_valuation"] = item["has_plot_valuation"]

        # Actualizar valoración de referencia y descuento si el vuelo+suelo supera o ajusta la referencia
        listing_price = float(item.get("listing_price") or item.get("price") or 0.0)
        current_ref = float(
            item.get("estimated_market_value")
            or item.get("estimated_reference_value")
            or item.get("market_reference_price")
            or 0.0
        )
        if comp_market_val > 0 and (has_plot_valuation or current_ref <= 0 or comp_market_val > current_ref):
            new_ref = round(max(comp_market_val, listing_price * 1.05 if listing_price > 0 else comp_market_val), 2)
            item["estimated_market_value"] = new_ref
            item["estimated_reference_value"] = new_ref
            item["market_reference_price"] = new_ref
            if listing_price > 0 and new_ref > listing_price:
                disc_pct = round(((new_ref - listing_price) / new_ref) * 100.0, 1)
                item["discount_vs_market"] = disc_pct
                item["discount_percentage"] = disc_pct
                item["discount_pct"] = disc_pct
                item["potential_gross_profit"] = round(new_ref - listing_price, 2)

        return item

    @classmethod
    def call_gemini_plot_batch_sync(
        cls,
        batch_items: List[Dict[str, Any]],
        timeout_sec: float = 25.0,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Invoca Gemini para un lote de oportunidades y devuelve un diccionario
        `{id: {"plot_surface_m2": float, "built_surface_m2": float, "property_type": str}}`.
        """
        if not batch_items or "PYTEST_CURRENT_TEST" in os.environ:
            return {}

        api_key = cls.get_api_key()
        if not api_key:
            return {}

        compact_payload = []
        for it in batch_items:
            oid = str(it.get("id") or "").strip()
            if not oid:
                continue
            compact_payload.append({
                "id": oid,
                "title": str(it.get("title") or "")[:160],
                "property_type": str(it.get("property_type") or ""),
                "locality": str(it.get("locality") or ""),
                "province": str(it.get("province") or ""),
                "address": str(it.get("address") or "")[:120],
                "postal_code": str(it.get("postal_code") or ""),
                "surface_m2": float(it.get("surface_m2") or it.get("built_area") or 0.0),
                "price": float(it.get("listing_price") or it.get("price") or 0.0),
                "description": str(it.get("description") or "")[:350],
            })

        if not compact_payload:
            return {}

        sys_inst = (
            "Eres un perito tasador inmobiliario colegiado en España (Orden ECO/805/2003). "
            "Para cada activo de la lista, debes determinar su superficie de parcela/terreno (`plot_surface_m2`), "
            "su superficie construida (`built_surface_m2`) y su tipología corregida (`property_type`).\n"
            "REGLAS OBLIGATORIAS:\n"
            "1. EXTRACCIÓN LITERAL: Si el título o descripción menciona metros de parcela, terreno, solar, finca, "
            "jardín o patio (en cifras, en palabras, o en hectáreas/áreas/centiáreas/tahúllas: 1 ha = 10000 m2, 1 área = 100 m2, 1 ca = 1 m2), "
            "extrae el valor exacto en m2 para `plot_surface_m2`.\n"
            "2. SOLARES Y FINCAS: Si el activo es un Solar, Terreno o Finca Rústica sin vivienda principal, "
            "`plot_surface_m2` es la superficie total del terreno/solar.\n"
            "3. ESTIMACIÓN PERICIAL EN CHALETS / UNIFAMILIARES / CASAS: Si el activo es un chalet (independiente, pareado o adosado), "
            "vivienda unifamiliar, casa, villa, masía, cortijo, caserío, casa de pueblo, o está en una urbanización de chalets "
            "(ej. Urbanización Las Vegas en Villanueva del Pardillo, La Moraleja, Valdemarín, Aravaca, Pozuelo, Boadilla, Majadahonda, "
            "Las Rozas, Torrelodones, Sotogrande, etc.) y el extracto corto del anuncio no indica explícitamente los m2 de parcela, "
            "DEBES estimar pericialmente `plot_surface_m2` (> 0) de acuerdo con el planeamiento urbanístico típico de esa urbanización/municipio "
            "y los m2 construidos (ej. chalet independiente 450-1500 m2; chalet pareado 300-500 m2; chalet adosado 180-300 m2; casa de pueblo 140-250 m2). "
            "Además, si estaba etiquetado como 'PISO' siendo un chalet o casa, corrige `property_type` a 'Chalet / Casa'.\n"
            "4. PISOS EN BLOQUE Y LOCALES COMERCIALES: Si es un piso en bloque plurifamiliar, apartamento, ático o local comercial en planta baja "
            "SIN parcela ni jardín privativo sobre suelo, devuelve `plot_surface_m2`: 0.\n"
            "Devuelve EXCLUSIVAMENTE un objeto JSON con la clave `items`, donde cada elemento tenga: "
            '`{"id": "...", "plot_surface_m2": <numero>, "built_surface_m2": <numero>, "property_type": "..."}`.'
        )

        request_body = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": json.dumps({"candidates": compact_payload}, ensure_ascii=False)
                        }
                    ]
                }
            ],
            "system_instruction": {"parts": [{"text": sys_inst}]},
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json",
            },
        }

        models = [
            "gemini-4-argon",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-3-flash-preview",
            "gemini-2.5-flash",
            "gemini-flash-latest",
            "gemini-2.5-pro",
        ]
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                resp = httpx.post(url, json=request_body, timeout=timeout_sec)
                if resp.status_code == 200:
                    data = resp.json()
                    parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
                    if parts and "text" in parts[0]:
                        parsed = json.loads(parts[0]["text"].strip())
                        items_list = parsed.get("items") if isinstance(parsed, dict) else (parsed if isinstance(parsed, list) else [])
                        if isinstance(items_list, list):
                            out: Dict[str, Dict[str, Any]] = {}
                            for row in items_list:
                                if isinstance(row, dict) and row.get("id"):
                                    oid_k = str(row["id"]).strip()
                                    try:
                                        pm2 = float(row.get("plot_surface_m2") or 0.0)
                                    except Exception:
                                        pm2 = 0.0
                                    try:
                                        bm2 = float(row.get("built_surface_m2") or 0.0)
                                    except Exception:
                                        bm2 = 0.0
                                    pt_str = str(row.get("property_type") or "").strip()
                                    out[oid_k] = {
                                        "plot_surface_m2": max(0.0, pm2),
                                        "built_surface_m2": max(0.0, bm2),
                                        "property_type": pt_str,
                                    }
                            return out
            except Exception as e:
                logger.warning(f"[PlotValuationEnricher] Error en {model}: {e}")

        return {}

    @classmethod
    def enrich_items_with_gemini(
        cls,
        items: List[Dict[str, Any]],
        batch_size: int = 35,
        only_candidates_for_gemini: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Enriquece una lista de oportunidades con `plot_surface_m2` y `solar_m2_price`
        utilizando Gemini en lotes + valoración compuesta 2x2 F3.
        """
        if not items:
            return items

        # Seleccionar aquellos ítems donde Gemini aporta extracción/inferencia de parcela o corrección tipológica
        to_query_gemini: List[Dict[str, Any]] = []
        for it in items:
            if not only_candidates_for_gemini:
                to_query_gemini.append(it)
                continue
            cur_plot = float(it.get("plot_surface_m2") or 0.0)
            is_cand, _ = cls.is_single_family_or_land_candidate(it)
            desc_low = f"{it.get('title', '')} {it.get('description', '')}".lower()
            mentions_land = any(
                w in desc_low
                for w in (
                    "parcela", "terreno", "solar", "finca", "jardín", "jardin",
                    "patio", "hectárea", "hectarea", "áreas", "areas", "centiáreas",
                    "chalet", "unifamiliar", "adosad", "paread", "villa", "masía",
                    "masia", "cortijo", "caserío", "caserio", "casa ", "urbanización las vegas",
                )
            )
            if cur_plot <= 0 and (is_cand or mentions_land):
                to_query_gemini.append(it)

        gemini_results: Dict[str, Dict[str, Any]] = {}
        for idx in range(0, len(to_query_gemini), batch_size):
            batch = to_query_gemini[idx : idx + batch_size]
            batch_res = cls.call_gemini_plot_batch_sync(batch)
            gemini_results.update(batch_res)

        for it in items:
            oid = str(it.get("id") or "").strip()
            g_info = gemini_results.get(oid) or {}
            cls.apply_2x2_plot_valuation_to_item(
                it,
                gemini_plot_m2=g_info.get("plot_surface_m2"),
                gemini_built_m2=g_info.get("built_surface_m2"),
                gemini_property_type=g_info.get("property_type"),
            )

        return items

    @classmethod
    async def async_enrich_items_with_gemini(
        cls,
        items: List[Dict[str, Any]],
        batch_size: int = 35,
        only_candidates_for_gemini: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Versión asíncrona para flujos en vivo (`sync_portal_opportunities_on_demand`, etc.).
        """
        if not items:
            return items
        return await asyncio.to_thread(
            cls.enrich_items_with_gemini,
            items,
            batch_size,
            only_candidates_for_gemini,
        )

    @classmethod
    def backfill_company_knowledge_base(cls, db_session: Any, label: str = "DB") -> int:
        """
        Hace backfill de todas las oportunidades en `CompanyKnowledgeBase` (`market_opp:%`)
        ordenadas de hoy hacia atrás (`updated_at DESC, created_at DESC`).
        """
        from app.db.models import CompanyKnowledgeBase

        rows = (
            db_session.query(CompanyKnowledgeBase)
            .filter(CompanyKnowledgeBase.query_key.like("market_opp:%"))
            .order_by(
                CompanyKnowledgeBase.updated_at.desc(),
                CompanyKnowledgeBase.created_at.desc(),
                CompanyKnowledgeBase.id.desc(),
            )
            .all()
        )
        if not rows:
            logger.info(f"[{label}] No hay filas market_opp:% en CompanyKnowledgeBase.")
            return 0

        # Mapa rápido desde verified_market_catalog.json para no repetir llamadas Gemini si ya se enriqueció
        catalog_plot_by_id: Dict[str, Dict[str, Any]] = {}
        if os.path.exists(CATALOG_JSON_PATH):
            try:
                with open(CATALOG_JSON_PATH, "r", encoding="utf-8") as f_cat:
                    cat_raw = json.load(f_cat)
                cat_list = cat_raw if isinstance(cat_raw, list) else (cat_raw.get("items") or [])
                for c_it in cat_list:
                    if isinstance(c_it, dict) and c_it.get("id"):
                        catalog_plot_by_id[str(c_it["id"]).strip()] = c_it
            except Exception:
                pass

        items_with_rows: List[Tuple[Any, Dict[str, Any]]] = []
        for r in rows:
            if r.source == "PURGED_MARKET_OPP":
                continue
            try:
                raw_str = getattr(r, "raw_payload_json", None) or "{}"
                payload = json.loads(raw_str)
                if isinstance(payload, dict) and payload.get("id"):
                    oid_k = str(payload["id"]).strip()
                    cat_match = catalog_plot_by_id.get(oid_k)
                    if cat_match and float(payload.get("plot_surface_m2") or 0.0) <= 0:
                        if float(cat_match.get("plot_surface_m2") or 0.0) > 0:
                            payload["plot_surface_m2"] = float(cat_match["plot_surface_m2"])
                        if float(cat_match.get("solar_m2_price") or 0.0) > 0:
                            payload["solar_m2_price"] = float(cat_match["solar_m2_price"])
                    items_with_rows.append((r, payload))
            except Exception:
                continue

        all_payloads = [p for _, p in items_with_rows]
        logger.info(f"[{label}] Enriqueciendo {len(all_payloads)} oportunidades de CompanyKnowledgeBase (de hoy hacia atrás)...")
        cls.enrich_items_with_gemini(all_payloads, batch_size=35, only_candidates_for_gemini=True)

        updated_count = 0
        for r, payload in items_with_rows:
            r.raw_payload_json = json.dumps(payload, ensure_ascii=False)
            updated_count += 1

        db_session.commit()
        logger.info(f"[{label}] Backfill completado en CompanyKnowledgeBase: {updated_count} filas actualizadas.")
        return updated_count

    @classmethod
    def backfill_verified_market_catalog_json(cls) -> int:
        """
        Hace backfill del catálogo `app/data/verified_market_catalog.json`
        procesando las oportunidades de hoy/más recientes hacia atrás.
        """
        if not os.path.exists(CATALOG_JSON_PATH):
            return 0

        with open(CATALOG_JSON_PATH, "r", encoding="utf-8") as f:
            catalog_data = json.load(f)

        is_list_root = isinstance(catalog_data, list)
        items = catalog_data if is_list_root else (catalog_data.get("items") or [])
        if not items:
            return 0

        # Invertir para procesar de más reciente a más antiguo (hoy hacia atrás) y luego restaurar orden
        reversed_items = list(reversed(items))
        logger.info(f"[Catalog JSON] Enriqueciendo {len(reversed_items)} oportunidades de hoy hacia atrás...")
        cls.enrich_items_with_gemini(reversed_items, batch_size=40, only_candidates_for_gemini=True)

        restored_items = list(reversed(reversed_items))
        if is_list_root:
            out_data = restored_items
        else:
            catalog_data["items"] = restored_items
            catalog_data["generated_at"] = datetime.now(timezone.utc).isoformat()
            out_data = catalog_data

        with open(CATALOG_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(out_data, f, ensure_ascii=False, indent=2)

        try:
            with open("/tmp/verified_market_catalog.json", "w", encoding="utf-8") as f_tmp:
                json.dump(out_data, f_tmp, ensure_ascii=False, indent=2)
        except Exception:
            pass

        with_plot = sum(1 for x in restored_items if (x.get("plot_surface_m2") or 0) > 0)
        with_solar_price = sum(1 for x in restored_items if (x.get("solar_m2_price") or 0) > 0)
        logger.info(
            f"[Catalog JSON] Actualizado: {len(restored_items)} total, "
            f"{with_plot} con plot_surface_m2 > 0, {with_solar_price} con solar_m2_price > 0."
        )
        return len(restored_items)

    @classmethod
    def backfill_auctions_and_opportunities(cls, db_session: Any, label: str = "DB") -> int:
        """
        Hace backfill de las subastas BOE (`Auction` + `Opportunity`) de hoy hacia atrás (`id DESC`),
        extrayendo/estimando con Gemini `plot_surface_m2` y `built_surface_m2`, guardando en
        `verified_auction_plots.json` y actualizando `Opportunity.estimated_reference_value` y
        `Opportunity.discount_percentage`.
        """
        from app.db.models import Auction, Opportunity

        auctions = (
            db_session.query(Auction)
            .order_by(Auction.created_at.desc(), Auction.id.desc())
            .all()
        )
        if not auctions:
            return 0

        opps_by_auc_id: Dict[int, Any] = {}
        for o in db_session.query(Opportunity).all():
            if o.auction_id is not None:
                opps_by_auc_id[o.auction_id] = o

        auction_plots_map = cls.load_auction_plots_map()
        pseudo_items: List[Dict[str, Any]] = []
        auc_by_oid: Dict[str, Any] = {}

        for auc in auctions:
            oid = str(auc.id_subasta or f"BOE-{auc.id}").strip()
            auc_by_oid[oid] = auc
            desc_str = f"{auc.title or ''} {auc.description or ''}"
            # Extraer m2 construidos básicos si están en descripción
            m_surf = re.search(
                r'(\d+(?:[.,]\d+)?)\s*(?:m2|m²|metros\s*cuadrados)',
                desc_str.lower(),
            )
            raw_surf = 0.0
            if m_surf:
                raw_surf = float(m_surf.group(1).replace(".", "").replace(",", "."))
                if raw_surf < 15 or raw_surf > 100000:
                    raw_surf = 0.0

            prev_plot = float((auction_plots_map.get(oid) or {}).get("plot_surface_m2") or 0.0)
            pseudo_items.append({
                "id": oid,
                "title": auc.title or f"Subasta {oid}",
                "property_type": auc.property_type or "Vivienda",
                "locality": auc.locality or auc.province or "España",
                "province": auc.province or "España",
                "address": auc.address or "",
                "postal_code": getattr(auc, "postal_code", None) or "",
                "surface_m2": raw_surf,
                "plot_surface_m2": prev_plot,
                "listing_price": float(auc.starting_bid or 0.0),
                "price": float(auc.starting_bid or 0.0),
                "estimated_reference_value": float(auc.appraisal_value or 0.0),
                "description": auc.description or "",
            })

        logger.info(f"[{label}] Enriqueciendo {len(pseudo_items)} subastas BOE de hoy hacia atrás con Gemini...")
        cls.enrich_items_with_gemini(pseudo_items, batch_size=40, only_candidates_for_gemini=True)

        updated_opps = 0
        for p_item in pseudo_items:
            oid = p_item["id"]
            auc = auc_by_oid.get(oid)
            plot_m2 = float(p_item.get("plot_surface_m2") or 0.0)
            solar_price = float(p_item.get("solar_m2_price") or 0.0)
            built_m2 = float(p_item.get("surface_m2") or 0.0)
            auction_plots_map[oid] = {
                "plot_surface_m2": round(plot_m2, 2),
                "solar_m2_price": round(solar_price, 2),
                "surface_m2": round(built_m2, 2),
                "base_building_value": round(float(p_item.get("base_building_value") or 0.0), 2),
                "plot_added_value": round(float(p_item.get("plot_added_value") or 0.0), 2),
                "has_plot_valuation": bool(p_item.get("has_plot_valuation")),
                "property_type": str(p_item.get("property_type") or ""),
            }
            if auc and auc.id in opps_by_auc_id:
                opp_row = opps_by_auc_id[auc.id]
                new_ref = float(p_item.get("estimated_reference_value") or 0.0)
                if new_ref > float(opp_row.estimated_reference_value or 0.0) and plot_m2 > 0:
                    opp_row.estimated_reference_value = round(new_ref, 2)
                    bid = float(auc.starting_bid or 0.0)
                    if bid > 0 and new_ref > bid:
                        opp_row.discount_percentage = round(((new_ref - bid) / new_ref) * 100.0, 2)
                    updated_opps += 1

        db_session.commit()
        cls.save_auction_plots_map(auction_plots_map)
        logger.info(
            f"[{label}] Subastas BOE enriquecidas: {len(pseudo_items)} mapeadas en verified_auction_plots.json, "
            f"{updated_opps} filas Opportunity actualizadas en BD."
        )
        return len(pseudo_items)

    @classmethod
    def run_full_backfill_from_today_backwards(cls) -> Dict[str, Any]:
        """
        Ejecuta el backfill integral de hoy hacia atrás en:
        1. Supabase PostgreSQL (`CompanyKnowledgeBase` + `Auction`/`Opportunity`)
        2. SQLite local `hivex_local.db` (`CompanyKnowledgeBase` + `Auction`/`Opportunity`)
        3. `app/data/verified_market_catalog.json`
        """
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.db.session import SessionLocal

        summary: Dict[str, Any] = {}

        # 1. Catálogo JSON verificado
        summary["catalog_json_items"] = cls.backfill_verified_market_catalog_json()

        # 2. Sesión principal configurada (Supabase PostgreSQL si DATABASE_URL apunta a Supabase)
        db_main = SessionLocal()
        try:
            summary["main_db_ckb"] = cls.backfill_company_knowledge_base(db_main, label="Main-DB")
            summary["main_db_auctions"] = cls.backfill_auctions_and_opportunities(db_main, label="Main-DB")
        except Exception as e_main:
            logger.warning(f"Error en backfill Main-DB: {e_main}")
            summary["main_db_error"] = str(e_main)
        finally:
            db_main.close()

        # 3. Réplica SQLite local (`hivex_local.db`) si existe y es distinta de Main-DB
        sqlite_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "hivex_local.db",
        )
        if os.path.exists(sqlite_path):
            try:
                eng_sqlite = create_engine(
                    f"sqlite:///{sqlite_path}",
                    connect_args={"check_same_thread": False},
                )
                SqliteSession = sessionmaker(bind=eng_sqlite)
                db_sq = SqliteSession()
                try:
                    summary["sqlite_ckb"] = cls.backfill_company_knowledge_base(db_sq, label="SQLite-Local")
                    summary["sqlite_auctions"] = cls.backfill_auctions_and_opportunities(db_sq, label="SQLite-Local")
                finally:
                    db_sq.close()
            except Exception as e_sq:
                logger.warning(f"Error en backfill SQLite-Local: {e_sq}")
                summary["sqlite_error"] = str(e_sq)

        return summary
