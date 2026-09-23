#!/usr/bin/env python3
"""
Script de recalibración masiva del catálogo de mercado verificado (verified_market_catalog.json).
Aplica la matriz MIVAU Tier 1 y Tier 2 por Código Postal y Barrio exacto, corrigiendo precios m2,
valores de mercado, descuentos reales, rentas estimadas y scores.
"""
import json
import logging
from pathlib import Path
from app.connectors.portal_parsers import IdealistaMarkdownParser
from app.engine.rental_reference import RentalReferenceEngine
from app.engine.kpi_calculator import KPICalculator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("recalibrate_catalog")

CATALOG_PATH = Path("app/data/verified_market_catalog.json")

def recalibrate():
    if not CATALOG_PATH.exists():
        logger.error(f"Catálogo {CATALOG_PATH} no encontrado.")
        return

    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        items = json.load(f)

    logger.info(f"Iniciando recalibración de {len(items)} oportunidades...")

    recalibrated_count = 0
    cp_counts = {}

    valid_items = []
    for item in items:
        # Descartar naves industriales según regla de usuario
        prop_type = (item.get("property_type") or "").lower()
        title_lower = (item.get("title") or "").lower()
        if "nave" in prop_type or "nave" in title_lower:
            continue

        title = item.get("title") or item.get("address", "")
        t_check = (title + " " + (item.get("address") or "")).lower()

        prov = item.get("province") or item.get("locality") or "Madrid"
        if "valencia" in t_check or "valència" in t_check:
            prov = "Valencia"
        elif "barcelona" in t_check:
            prov = "Barcelona"
        elif "málaga" in t_check or "malaga" in t_check:
            prov = "Málaga"
        elif "madrid" in t_check:
            prov = "Madrid"

        cp = item.get("postal_code")
        loc_data = IdealistaMarkdownParser._resolve_location_and_kpis(title, prov, cp)

        item["postal_code"] = loc_data["postal_code"]
        item["lat"] = loc_data["lat"]
        item["lon"] = loc_data["lon"]
        item["locality"] = loc_data["locality"]
        item["province"] = loc_data["province"]

        census = item.setdefault("census_tract_data", {})
        census["district"] = loc_data["district_label"]
        census["avg_household_income"] = loc_data["avg_household_income"]
        census["avg_person_income"] = round(loc_data["avg_household_income"] / 2.2)
        census["area_m2_price"] = loc_data["area_m2_price"]
        census["population_growth_rate"] = loc_data["population_growth_rate"]

        surface = float(item.get("surface_m2") or 1.0)
        listing_price = float(item.get("listing_price") or 0.0)
        area_m2_price = loc_data["area_m2_price"]
        est_val = round(surface * area_m2_price, 2)

        discount_vs_market = round(max(0.0, ((est_val - listing_price) / est_val) * 100), 1) if est_val > 0 else 0.0
        item["discount_vs_market"] = discount_vs_market

        # Descuento preferente
        price_drop = item.get("price_drop_percentage") or 0.0
        item["discount_percentage"] = price_drop if price_drop > 0 else discount_vs_market

        # Alquiler y Yield
        strategy = item.get("strategy", "HOUSE_FLIPPING")
        is_solar = (
            strategy == "LAND_DEVELOPMENT"
            or "solar" in prop_type
            or "terreno" in prop_type
            or "parcela" in prop_type
            or "suelo" in prop_type
        )

        if not is_solar:
            monthly_rent = RentalReferenceEngine.estimate_monthly_rent(
                surface, loc_data["postal_code"], loc_data["province"],
                item.get("floor", "Exterior"), item.get("has_elevator", True)
            )
            rental_yield = RentalReferenceEngine.calculate_rental_yield(listing_price, monthly_rent)
            yield_score, yield_color = RentalReferenceEngine.evaluate_yield(rental_yield)

            item["estimated_monthly_rent"] = monthly_rent
            item["rental_yield"] = rental_yield
            item["yield_score"] = yield_score
            item["yield_color"] = yield_color
            item["btl_score"] = yield_score
            item["btl_color"] = yield_color
        else:
            item["estimated_monthly_rent"] = None
            item["rental_yield"] = None
            item["yield_score"] = 0.0
            item["yield_color"] = "rojo"
            item["btl_score"] = None
            item["btl_color"] = None

        overall_score = KPICalculator.calculate_overall_opportunity_score(
            discount_percentage=discount_vs_market / 100.0,
            poi_score=82.0,
            income_amount=loc_data["avg_household_income"],
            population_growth=loc_data["population_growth_rate"],
            rental_yield=item.get("rental_yield") or 0.0,
            is_solar=is_solar
        )
        item["overall_score"] = overall_score
        item["final_score"] = overall_score

        valid_items.append(item)
        recalibrated_count += 1
        cp_counts[item["postal_code"]] = cp_counts.get(item["postal_code"], 0) + 1

    # Ordenar por oportunidad relevante
    valid_items.sort(
        key=lambda x: (
            1 if x.get("is_new") else 0,
            max(x.get("overall_score") or 0.0, x.get("btl_score") or 0.0),
            x.get("discount_percentage") or x.get("discount_vs_market") or 0.0
        ),
        reverse=True
    )

    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(valid_items, f, ensure_ascii=False, indent=2)

    logger.info(f"Recalibración completada con éxito. {recalibrated_count} oportunidades actualizadas.")
    logger.info(f"Distribución de principales CPs: {dict(list(sorted(cp_counts.items(), key=lambda x: x[1], reverse=True))[:15])}")

if __name__ == "__main__":
    recalibrate()
