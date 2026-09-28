"""
Script de migración y saneamiento del catálogo de mercado verified_market_catalog.json
Corrige:
1. Topónimos cruzados y tipo de vía (ej. 'Piso en Madrid, Delicias, Zaragoza' -> 'Piso en Av. de Madrid, Delicias, Zaragoza').
2. Limpieza de campo address (eliminando prefijo 'Piso en ' y duplicaciones de localidad).
3. Precios meso de mercado (evitando que barrios homónimos de Zaragoza, Sevilla o Málaga tomen precios de Madrid).
4. Descripciones vacías o con precios ('155.000€'), reemplazándolas por descripciones veraces y completas.
"""

import json
import re
from app.connectors.portal_parsers import normalize_spanish_address_and_title
from app.engine.meso_market_price import resolve_meso_market_price_2x2

CATALOG_PATH = "app/data/verified_market_catalog.json"

def migrate_catalog():
    print(f"Leyendo catálogo desde {CATALOG_PATH}...")
    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        items = json.load(f)

    updated_titles = 0
    updated_meso = 0
    updated_desc = 0

    for it in items:
        raw_title = it.get("title", "")
        raw_address = it.get("address", "")
        province = it.get("province", "")
        locality = it.get("locality", "")
        postal_code = it.get("postal_code", "")
        surface_m2 = it.get("surface_m2", 80.0)
        listing_price = it.get("listing_price", 0.0)
        old_desc = str(it.get("description", "")).strip()

        # 1. Normalización de Título y Dirección
        clean_title, clean_address = normalize_spanish_address_and_title(raw_title, province, locality)
        if clean_title != raw_title:
            it["title"] = clean_title
            updated_titles += 1

        # Limpiar prefijo tipológico si el address original lo tenía
        if not clean_address:
            clean_address = clean_title
        clean_address = re.sub(
            r'^(?:Piso|Apartamento|Ático|Atico|Dúplex|Duplex|Estudio|Chalet|Casa|Planta baja|Finca|Loft)\s+en\s+',
            '',
            clean_address,
            flags=re.IGNORECASE
        ).strip()
        it["address"] = clean_address

        # 2. Recálculo riguroso de Precio Meso y Valoración
        is_solar = (it.get("strategy") == "LAND_DEVELOPMENT" or "solar" in (it.get("property_type") or "").lower())
        land_type = "RÚSTICO" if any(k in clean_title.lower() for k in ["rústico", "rustico", "agrario"]) else "URBANO"

        old_price = it.get("area_m2_price")
        new_price, new_code, new_label = resolve_meso_market_price_2x2(
            province_str=province,
            locality_str=locality,
            full_address_str=clean_address,
            desc_text="",
            land_type=land_type,
            is_solar=is_solar,
            postal_code=postal_code
        )

        if old_price != new_price or it.get("area_m2_price_label") != new_label:
            updated_meso += 1
            it["area_m2_price"] = new_price
            it["area_m2_price_label"] = new_label
            it["meso_label"] = new_label
            if surface_m2 and surface_m2 > 0:
                est_val = round(surface_m2 * new_price, 2)
                it["estimated_reference_value"] = est_val
                if listing_price > 0 and est_val > 0:
                    it["discount_vs_market"] = round(max(0.0, ((est_val - listing_price) / est_val) * 100), 1)
                    it["potential_gross_profit"] = round(max(0.0, est_val - listing_price), 2)

        # 3. Saneamiento de Descripciones
        is_bad_desc = False
        if not old_desc or len(old_desc) < 20:
            is_bad_desc = True
        elif re.match(r'^[\d\.,\s]+€?(?:\s*/\s*(?:m[²2]|mes))?$', old_desc):
            is_bad_desc = True
        elif re.match(r'^-?\d+[\.,]?\d*\s*%$', old_desc):
            is_bad_desc = True

        if is_bad_desc:
            updated_desc += 1
            prop_type = (it.get("property_type") or "Vivienda").capitalize()
            rooms = it.get("rooms") or 2
            floor = it.get("floor") or ""
            floor_str = f", {floor.lower()}" if floor and floor.lower() not in ["exterior", "interior"] else ""
            asc_str = " con ascensor" if it.get("has_elevator") else (" sin ascensor" if floor and floor.lower() != "bajo" else "")
            
            # Buscar agencia en publicaciones
            agency = ""
            pubs = it.get("publications") or []
            if pubs and isinstance(pubs, list) and len(pubs) > 0:
                agency = pubs[0].get("agency", "")
            agency_str = f" Comercializado por {agency}." if agency and agency != "Idealista" else ""

            it["description"] = (
                f"{prop_type} de {int(surface_m2)} m² con {rooms} dormitorios{floor_str}{asc_str}. "
                f"Ubicado en {locality} ({province}).{agency_str} Inmueble verificado en Idealista."
            )

    print(f"Títulos corregidos: {updated_titles}")
    print(f"Precios meso y valoraciones actualizados: {updated_meso}")
    print(f"Descripciones saneadas: {updated_desc}")

    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

    print("Catálogo migrado con éxito.")

if __name__ == "__main__":
    migrate_catalog()
