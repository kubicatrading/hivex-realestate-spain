"""
Módulos de parseo estructurado de contenido Markdown extraído por Supadata
procedente de los portales inmobiliarios: Idealista, Habitaclia, Fotocasa y Pisos.com.
Transforma texto y enlaces Markdown en objetos de oportunidad estructurados para HIVEX.
"""

import re
import logging
from typing import List, Dict, Any, Optional

from app.engine.rental_reference import RentalReferenceEngine
from app.engine.kpi_calculator import KPICalculator

logger = logging.getLogger(__name__)


# Centroides de coordenadas y datos socioeconómicos de referencia por distrito/localidad
DISTRICT_COORDINATES: Dict[str, Dict[str, Any]] = {
    # MADRID
    "salamanca": {"lat": 40.4297, "lon": -3.6822, "income": 58000, "m2_price": 6800.0, "growth": 1.2},
    "goya": {"lat": 40.4245, "lon": -3.6765, "income": 56000, "m2_price": 6500.0, "growth": 1.1},
    "recoletos": {"lat": 40.4225, "lon": -3.6885, "income": 69000, "m2_price": 8500.0, "growth": 0.9},
    "el viso": {"lat": 40.4465, "lon": -3.6820, "income": 72000, "m2_price": 7200.0, "growth": 0.7},
    "chamartin": {"lat": 40.4625, "lon": -3.6765, "income": 54200, "m2_price": 5400.0, "growth": 1.9},
    "castilla": {"lat": 40.4725, "lon": -3.6845, "income": 53000, "m2_price": 5200.0, "growth": 1.8},
    "chamberi": {"lat": 40.4350, "lon": -3.7020, "income": 58900, "m2_price": 6300.0, "growth": 0.8},
    "trafalgar": {"lat": 40.4320, "lon": -3.7015, "income": 57000, "m2_price": 6100.0, "growth": 0.9},
    "almagro": {"lat": 40.4310, "lon": -3.6920, "income": 64000, "m2_price": 7100.0, "growth": 0.8},
    "centro": {"lat": 40.4180, "lon": -3.7060, "income": 42000, "m2_price": 5200.0, "growth": 1.5},
    "malasaña": {"lat": 40.4265, "lon": -3.7045, "income": 44500, "m2_price": 5300.0, "growth": 1.6},
    "chueca": {"lat": 40.4230, "lon": -3.6980, "income": 46000, "m2_price": 5500.0, "growth": 1.4},
    "retiro": {"lat": 40.4110, "lon": -3.6780, "income": 53500, "m2_price": 5900.0, "growth": 1.0},
    "ibiza": {"lat": 40.4185, "lon": -3.6760, "income": 52000, "m2_price": 5800.0, "growth": 1.0},
    "vallecas": {"lat": 40.3850, "lon": -3.6600, "income": 28500, "m2_price": 2400.0, "growth": 3.2},
    "ensanche de vallecas": {"lat": 40.3620, "lon": -3.6010, "income": 37200, "m2_price": 3350.0, "growth": 3.8},
    "vicalvaro": {"lat": 40.4020, "lon": -3.6080, "income": 34500, "m2_price": 2800.0, "growth": 3.9},
    "el cañaveral": {"lat": 40.4150, "lon": -3.5600, "income": 38000, "m2_price": 3200.0, "growth": 4.8},
    "los berrocales": {"lat": 40.3685, "lon": -3.5890, "income": 36500, "m2_price": 3100.0, "growth": 4.5},
    "carabanchel": {"lat": 40.3850, "lon": -3.7400, "income": 28500, "m2_price": 2750.0, "growth": 2.1},
    "vista alegre": {"lat": 40.3885, "lon": -3.7420, "income": 29000, "m2_price": 2700.0, "growth": 2.0},
    "tetuan": {"lat": 40.4580, "lon": -3.7020, "income": 37000, "m2_price": 4100.0, "growth": 2.2},
    "moncloa": {"lat": 40.4350, "lon": -3.7250, "income": 51000, "m2_price": 4900.0, "growth": 1.1},
    "fuencarral": {"lat": 40.4950, "lon": -3.7050, "income": 49000, "m2_price": 4400.0, "growth": 2.6},
    "hortaleza": {"lat": 40.4700, "lon": -3.6550, "income": 47000, "m2_price": 4200.0, "growth": 2.1},

    # BARCELONA
    "eixample": {"lat": 41.3880, "lon": 2.1620, "income": 49800, "m2_price": 5100.0, "growth": 0.6},
    "gracia": {"lat": 41.4030, "lon": 2.1580, "income": 44100, "m2_price": 4900.0, "growth": 1.1},
    "poblenou": {"lat": 41.4020, "lon": 2.2020, "income": 48200, "m2_price": 4600.0, "growth": 2.9},
    "sant marti": {"lat": 41.4150, "lon": 2.2000, "income": 42000, "m2_price": 4100.0, "growth": 2.4},
    "sarria": {"lat": 41.4010, "lon": 2.1220, "income": 68000, "m2_price": 6200.0, "growth": 0.5},
    "ciutat vella": {"lat": 41.3820, "lon": 2.1750, "income": 33000, "m2_price": 4400.0, "growth": 1.2},
    "sants": {"lat": 41.3750, "lon": 2.1380, "income": 38500, "m2_price": 3800.0, "growth": 1.4},

    # VALENCIA
    "ruzafa": {"lat": 41.4625, "lon": -0.3735, "income": 38900, "m2_price": 3600.0, "growth": 1.7},
    "el grau": {"lat": 39.4605, "lon": -0.3370, "income": 33400, "m2_price": 2950.0, "growth": 3.4},
    "ciutat vella valencia": {"lat": 39.4750, "lon": -0.3780, "income": 41000, "m2_price": 3700.0, "growth": 1.2},
    "campanar": {"lat": 39.4830, "lon": -0.3950, "income": 36000, "m2_price": 2800.0, "growth": 2.2},

    # MALAGA
    "soho": {"lat": 36.7170, "lon": -4.4230, "income": 41800, "m2_price": 4200.0, "growth": 2.5},
    "teatinos": {"lat": 36.7190, "lon": -4.4750, "income": 38000, "m2_price": 3100.0, "growth": 3.6},
    "cortijo merino": {"lat": 36.7020, "lon": -4.4810, "income": 31200, "m2_price": 2650.0, "growth": 3.9},
    "cruz de humilladero": {"lat": 36.7120, "lon": -4.4450, "income": 30500, "m2_price": 2550.0, "growth": 2.8},
}


class IdealistaMarkdownParser:
    """
    Parser especializado para extraer oportunidades estructuradas
    del Markdown generado por Supadata al consultar Idealista.com.
    """

    @classmethod
    def parse_listings(cls, markdown_content: str, default_province: str = "Madrid") -> List[Dict[str, Any]]:
        listings: List[Dict[str, Any]] = []
        if not markdown_content:
            return listings

        # En Idealista cada inmueble se identifica por un enlace de formato:
        # [Título](https://www.idealista.com/inmueble/112270818/ "...")
        link_pattern = re.compile(
            r'\[(?P<title>[^\]]+)\]\((?P<url>https?://(?:www\.)?idealista\.com/inmueble/(?P<id>\d+)/?)(?:\s+"[^"]*")?\)',
            re.IGNORECASE
        )

        matches = list(link_pattern.finditer(markdown_content))
        if not matches:
            logger.warning("No se encontraron enlaces a inmuebles en el Markdown de Idealista.")
            return listings

        for i, match in enumerate(matches):
            try:
                item_id = match.group("id")
                title = match.group("title").strip()
                url = match.group("url")

                # Contexto previo (para fotos y comercializadora)
                start_prev = matches[i - 1].end() if i > 0 else max(0, match.start() - 1500)
                prev_text = markdown_content[start_prev:match.start()]

                # Contexto posterior (para precios, características y descripción)
                end_post = matches[i + 1].start() if i + 1 < len(matches) else min(len(markdown_content), match.end() + 2000)
                post_text = markdown_content[match.end():end_post]

                # 1. Comercializadora / Agencia
                agency = "Agencia Inmobiliaria"
                agency_matches = list(re.finditer(r'\[(?:Comercializa)?(?P<agency>[^\]]+)\]\(https?://(?:www\.)?idealista\.com/pro/[^\)]+\)', prev_text))
                if agency_matches:
                    agency = agency_matches[-1].group("agency").replace("Comercializa", "").strip()

                # 2. Imágenes del inmueble
                images = []
                img_matches = re.findall(r'!\[[^\]]*\]\((https?://img\d*\.idealista\.com/[^\)]+)\)', prev_text)
                for img_url in img_matches:
                    clean_img = img_url.replace("/blur/189_120_mq/", "/blur/591_420_mq/")
                    if clean_img not in images:
                        images.append(clean_img)

                # 3. Precios y Descuento
                # En Idealista aparece:
                # 750.000€
                # 798.000 €
                # 6%
                # Excluir precios por metro cuadrado (€/m²) o alquiler mensual (€/mes)
                price_matches = re.findall(r'(\d{1,3}(?:\.\d{3})+)\s*€(?!\s*/\s*m[²2]|\s*/\s*mes)', post_text[:400])
                if not price_matches:
                    continue

                clean_prices = [float(p.replace(".", "")) for p in price_matches if float(p.replace(".", "")) > 10000]
                if not clean_prices:
                    continue

                listing_price = clean_prices[0]
                original_listing_price = listing_price
                discount_percentage = 0.0

                if len(clean_prices) > 1 and clean_prices[1] > listing_price:
                    original_listing_price = clean_prices[1]
                    discount_percentage = round(((original_listing_price - listing_price) / original_listing_price) * 100, 1)
                else:
                    pct_match = re.search(r'(\d{1,2})\s*%', post_text[:300])
                    if pct_match:
                        discount_percentage = float(pct_match.group(1))
                        original_listing_price = round(listing_price / (1 - (discount_percentage / 100.0)), 2)

                # 4. Características: "Garaje incluido 3 hab.131 m²3ª planta exterior con ascensor"
                rooms = 2
                rooms_match = re.search(r'(\d+)\s*hab(?:\.|\b)', post_text[:400])
                if rooms_match:
                    rooms = int(rooms_match.group(1))

                surface_m2 = 80.0
                surf_match = re.search(r'(\d+(?:\.\d+)?)\s*m[²2]', post_text[:400])
                if surf_match:
                    surface_m2 = float(surf_match.group(1).replace(".", ""))

                floor = "Exterior"
                floor_match = re.search(r'(\d+[ªº]?\s*planta\s*(?:exterior|interior)?|bajo|ático|entreplanta)', post_text[:400], re.IGNORECASE)
                if floor_match:
                    floor = floor_match.group(1).strip()

                has_elevator = True
                post_snippet = post_text[:400].lower()
                if "sin ascensor" in post_snippet:
                    has_elevator = False
                elif "con ascensor" in post_snippet:
                    has_elevator = True

                # 5. Descripción
                desc_lines = [line.strip() for line in post_text.split("\n") if line.strip() and not line.strip().startswith(("[", "!", "#", "Contactar", "Llamar", "Top+"))]
                description = desc_lines[0] if desc_lines else f"{title}. Inmueble comercializado por {agency}."

                # 6. Ubicación y Geocodificación
                location_data = cls._resolve_location_and_kpis(title, default_province)

                opportunity = {
                    "id": f"MKT-IDEALISTA-{item_id}",
                    "title": title,
                    "address": location_data.get("address") or title,
                    "locality": location_data.get("locality", default_province),
                    "province": location_data.get("province", default_province),
                    "postal_code": location_data.get("postal_code", "28001"),
                    "lat": location_data.get("lat"),
                    "lon": location_data.get("lon"),
                    "property_type": "PISO" if "chalet" not in title.lower() else "CHALET",
                    "strategy": "HOUSE_FLIPPING" if surface_m2 < 140 else "BUY_AND_HOLD",
                    "surface_m2": surface_m2,
                    "rooms": rooms,
                    "bathrooms": max(1, rooms - 1),
                    "floor": floor,
                    "has_elevator": has_elevator,
                    "energy_certificate": "D",
                    "original_listing_price": original_listing_price,
                    "listing_price": listing_price,
                    "first_published_date": "2026-03-01",
                    "publications": [
                        {
                            "portal": "Idealista",
                            "price": listing_price,
                            "url": url,
                            "agency": agency,
                            "published_date": "2026-03-01"
                        }
                    ],
                    "census_tract_data": {
                        "district": location_data.get("district_label", default_province),
                        "avg_household_income": location_data.get("avg_household_income", 42000),
                        "avg_person_income": round(location_data.get("avg_household_income", 42000) / 2.2),
                        "area_m2_price": location_data.get("area_m2_price", 3800.0),
                        "population_growth_rate": location_data.get("population_growth_rate", 2.0)
                    },
                    "images": images,
                    "description": description
                }

                is_solar = (opportunity.get("strategy") == "LAND_DEVELOPMENT" or "solar" in (opportunity.get("property_type") or "").lower() or "terreno" in (opportunity.get("property_type") or "").lower())

                if is_solar:
                    monthly_rent = 0.0
                    rental_yield = 0.0
                    yield_score = 0.0
                    yield_color = "rojo"
                    btl_score = None
                else:
                    # Cálculo de Rentabilidad Bruta Anual de Alquiler (+10% gastos adquisición)
                    monthly_rent = RentalReferenceEngine.estimate_monthly_rent(
                        surface_m2=surface_m2,
                        postal_code=opportunity["postal_code"],
                        province=opportunity["province"],
                        floor=floor,
                        has_elevator=has_elevator
                    )
                    rental_yield = RentalReferenceEngine.calculate_rental_yield(
                        listing_price=listing_price,
                        monthly_rent=monthly_rent
                    )
                    yield_score, yield_color = RentalReferenceEngine.evaluate_yield(rental_yield)
                    btl_score = yield_score

                area_m2_price = float(location_data.get("area_m2_price", 3800.0))
                est_market_val = surface_m2 * area_m2_price
                discount_vs_market = round(max(0.0, ((est_market_val - listing_price) / est_market_val) * 100), 1) if est_market_val > 0 else 0.0

                overall_score = KPICalculator.calculate_overall_opportunity_score(
                    discount_percentage=discount_vs_market / 100.0,
                    poi_score=85.0,
                    income_amount=location_data.get("avg_household_income", 42000),
                    population_growth=location_data.get("population_growth_rate", 2.0),
                    rental_yield=rental_yield,
                    is_solar=is_solar
                )

                opportunity["estimated_monthly_rent"] = monthly_rent if not is_solar else None
                opportunity["rental_yield"] = rental_yield if not is_solar else None
                opportunity["yield_score"] = yield_score if not is_solar else 0.0
                opportunity["yield_color"] = yield_color if not is_solar else None
                opportunity["btl_score"] = btl_score
                opportunity["btl_color"] = yield_color if not is_solar else None
                opportunity["discount_vs_market"] = discount_vs_market
                opportunity["overall_score"] = overall_score
                opportunity["final_score"] = overall_score

                listings.append(opportunity)
            except Exception as e_item:
                logger.warning(f"Error parseando item individual de Idealista: {e_item}")

        # Ordenar oportunidades por new primero, luego max(score/descuento, btl) descendente
        listings.sort(
            key=lambda x: (
                1 if x.get("is_new") else 0,
                max(x.get("overall_score") or x.get("discount_score") or 0.0, x.get("btl_score") or 0.0),
                x.get("discount_vs_market") or x.get("discount_percentage") or 0.0
            ),
            reverse=True
        )

        logger.info(f"[Idealista Parser] Extraídos {len(listings)} inmuebles estructurados y ordenados por max(score, btl).")
        return listings

    @classmethod
    def _resolve_location_and_kpis(cls, title: str, default_province: str) -> Dict[str, Any]:
        """Resuelve coordenadas y KPIs meso a partir del título o dirección."""
        t_lower = title.lower()
        
        # Buscar coincidencias con distritos conocidos
        for district_key, data in DISTRICT_COORDINATES.items():
            if district_key in t_lower:
                return {
                    "address": title,
                    "locality": default_province,
                    "province": default_province,
                    "postal_code": "28001" if default_province.lower() == "madrid" else "08001",
                    "lat": data["lat"],
                    "lon": data["lon"],
                    "district_label": district_key.capitalize(),
                    "avg_household_income": data["income"],
                    "area_m2_price": data["m2_price"],
                    "population_growth_rate": data["growth"]
                }

        # Fallbacks estándar por provincia y mercados estratégicos
        prov_lower = default_province.lower()
        if "talavera" in t_lower or ("toledo" in prov_lower and "talavera" in t_lower):
            return {
                "address": title, "locality": "Talavera de la Reina", "province": "Toledo",
                "postal_code": "45600", "lat": 39.9635, "lon": -4.8308, "district_label": "Talavera Centro",
                "avg_household_income": 28000, "area_m2_price": 950.0, "population_growth_rate": 2.8
            }
        elif "toledo" in prov_lower:
            return {
                "address": title, "locality": "Toledo", "province": "Toledo",
                "postal_code": "45001", "lat": 39.8628, "lon": -4.0273, "district_label": "Toledo Casco",
                "avg_household_income": 34000, "area_m2_price": 1600.0, "population_growth_rate": 1.6
            }
        elif "barcelona" in prov_lower:
            return {
                "address": title, "locality": "Barcelona", "province": "Barcelona",
                "postal_code": "08001", "lat": 41.3879, "lon": 2.1699, "district_label": "Barcelona Centro",
                "avg_household_income": 45000, "area_m2_price": 4500.0, "population_growth_rate": 1.2
            }
        elif "valencia" in prov_lower:
            return {
                "address": title, "locality": "Valencia", "province": "Valencia",
                "postal_code": "46001", "lat": 39.4699, "lon": -0.3763, "district_label": "Valencia Centro",
                "avg_household_income": 36000, "area_m2_price": 3200.0, "population_growth_rate": 2.4
            }
        elif "malaga" in prov_lower or "málaga" in prov_lower:
            return {
                "address": title, "locality": "Málaga", "province": "Málaga",
                "postal_code": "29001", "lat": 36.7213, "lon": -4.4214, "district_label": "Málaga Centro",
                "avg_household_income": 35000, "area_m2_price": 3400.0, "population_growth_rate": 3.1
            }
        elif "alicante" in prov_lower:
            return {
                "address": title, "locality": "Alicante", "province": "Alicante",
                "postal_code": "03001", "lat": 38.3452, "lon": -0.4810, "district_label": "Alicante Centro",
                "avg_household_income": 32000, "area_m2_price": 2200.0, "population_growth_rate": 2.2
            }
        elif "tarragona" in prov_lower:
            return {
                "address": title, "locality": "Tarragona", "province": "Tarragona",
                "postal_code": "43001", "lat": 41.1189, "lon": 1.2445, "district_label": "Tarragona Centro",
                "avg_household_income": 34000, "area_m2_price": 2100.0, "population_growth_rate": 1.5
            }
        elif "guipuzcoa" in prov_lower or "guipúzcoa" in prov_lower or "gipuzkoa" in prov_lower or "san sebastian" in prov_lower or "donostia" in prov_lower:
            return {
                "address": title, "locality": "San Sebastián", "province": "Guipúzcoa",
                "postal_code": "20001", "lat": 43.3183, "lon": -1.9812, "district_label": "Donostia Centro",
                "avg_household_income": 48000, "area_m2_price": 5400.0, "population_growth_rate": 1.0
            }
        elif "vizcaya" in prov_lower or "bizkaia" in prov_lower or "bilbao" in prov_lower:
            return {
                "address": title, "locality": "Bilbao", "province": "Vizcaya",
                "postal_code": "48001", "lat": 43.2630, "lon": -2.9350, "district_label": "Bilbao Abando",
                "avg_household_income": 45000, "area_m2_price": 3600.0, "population_growth_rate": 1.1
            }
        elif "alava" in prov_lower or "álava" in prov_lower or "araba" in prov_lower or "vitoria" in prov_lower:
            return {
                "address": title, "locality": "Vitoria-Gasteiz", "province": "Álava",
                "postal_code": "01001", "lat": 42.8467, "lon": -2.6716, "district_label": "Vitoria Centro",
                "avg_household_income": 42000, "area_m2_price": 2600.0, "population_growth_rate": 1.3
            }
        elif "navarra" in prov_lower or "pamplona" in prov_lower:
            return {
                "address": title, "locality": "Pamplona", "province": "Navarra",
                "postal_code": "31001", "lat": 42.8125, "lon": -1.6458, "district_label": "Pamplona Ensanche",
                "avg_household_income": 43000, "area_m2_price": 2700.0, "population_growth_rate": 1.4
            }
        elif "cantabria" in prov_lower or "santander" in prov_lower:
            return {
                "address": title, "locality": "Santander", "province": "Cantabria",
                "postal_code": "39001", "lat": 43.4623, "lon": -3.8099, "district_label": "Santander Centro",
                "avg_household_income": 38000, "area_m2_price": 2400.0, "population_growth_rate": 0.9
            }
        elif "baleares" in prov_lower or "palma" in prov_lower or "mallorca" in prov_lower or "ibiza" in prov_lower:
            return {
                "address": title, "locality": "Palma de Mallorca", "province": "Baleares",
                "postal_code": "07001", "lat": 39.5696, "lon": 2.6502, "district_label": "Palma Casco Antiguo",
                "avg_household_income": 44000, "area_m2_price": 4200.0, "population_growth_rate": 2.1
            }
        elif "las palmas" in prov_lower or "canaria" in prov_lower:
            return {
                "address": title, "locality": "Las Palmas de Gran Canaria", "province": "Las Palmas",
                "postal_code": "35001", "lat": 28.1248, "lon": -15.4300, "district_label": "Vegueta / Triana",
                "avg_household_income": 33000, "area_m2_price": 2300.0, "population_growth_rate": 1.5
            }
        elif "tenerife" in prov_lower:
            return {
                "address": title, "locality": "Santa Cruz de Tenerife", "province": "Santa Cruz de Tenerife",
                "postal_code": "38001", "lat": 28.4636, "lon": -16.2518, "district_label": "Santa Cruz Centro",
                "avg_household_income": 32000, "area_m2_price": 2200.0, "population_growth_rate": 1.4
            }
        elif "sevilla" in prov_lower:
            return {
                "address": title, "locality": "Sevilla", "province": "Sevilla",
                "postal_code": "41001", "lat": 37.3891, "lon": -5.9845, "district_label": "Sevilla Centro",
                "avg_household_income": 34000, "area_m2_price": 2300.0, "population_growth_rate": 1.2
            }
        elif "zaragoza" in prov_lower:
            return {
                "address": title, "locality": "Zaragoza", "province": "Zaragoza",
                "postal_code": "50001", "lat": 41.6488, "lon": -0.8891, "district_label": "Zaragoza Centro",
                "avg_household_income": 37000, "area_m2_price": 2000.0, "population_growth_rate": 1.1
            }
        elif "cadiz" in prov_lower or "cádiz" in prov_lower:
            return {
                "address": title, "locality": "Cádiz", "province": "Cádiz",
                "postal_code": "11001", "lat": 36.5271, "lon": -6.2886, "district_label": "Cádiz Casco",
                "avg_household_income": 31000, "area_m2_price": 2500.0, "population_growth_rate": 0.8
            }
        elif "coruña" in prov_lower or "coruna" in prov_lower:
            return {
                "address": title, "locality": "A Coruña", "province": "A Coruña",
                "postal_code": "15001", "lat": 43.3623, "lon": -8.4115, "district_label": "A Coruña Ciudad Vieja",
                "avg_household_income": 36000, "area_m2_price": 2400.0, "population_growth_rate": 1.1
            }
        elif "asturias" in prov_lower or "oviedo" in prov_lower or "gijon" in prov_lower or "gijón" in prov_lower:
            return {
                "address": title, "locality": "Oviedo", "province": "Asturias",
                "postal_code": "33001", "lat": 43.3619, "lon": -5.8494, "district_label": "Oviedo Centro",
                "avg_household_income": 35000, "area_m2_price": 1900.0, "population_growth_rate": 0.7
            }
        elif "murcia" in prov_lower:
            return {
                "address": title, "locality": "Murcia", "province": "Murcia",
                "postal_code": "30001", "lat": 37.9922, "lon": -1.1307, "district_label": "Murcia Centro",
                "avg_household_income": 31000, "area_m2_price": 1400.0, "population_growth_rate": 1.7
            }
        elif "valladolid" in prov_lower:
            return {
                "address": title, "locality": "Valladolid", "province": "Valladolid",
                "postal_code": "47001", "lat": 41.6523, "lon": -4.7245, "district_label": "Valladolid Centro",
                "avg_household_income": 36000, "area_m2_price": 1700.0, "population_growth_rate": 0.8
            }
        elif "granada" in prov_lower:
            return {
                "address": title, "locality": "Granada", "province": "Granada",
                "postal_code": "18001", "lat": 37.1773, "lon": -3.5986, "district_label": "Granada Centro",
                "avg_household_income": 32000, "area_m2_price": 2100.0, "population_growth_rate": 1.4
            }
        elif "cordoba" in prov_lower or "córdoba" in prov_lower:
            return {
                "address": title, "locality": "Córdoba", "province": "Córdoba",
                "postal_code": "14001", "lat": 37.8882, "lon": -4.7794, "district_label": "Córdoba Centro",
                "avg_household_income": 31000, "area_m2_price": 1500.0, "population_growth_rate": 0.9
            }
        elif "girona" in prov_lower:
            return {
                "address": title, "locality": "Girona", "province": "Girona",
                "postal_code": "17001", "lat": 41.9794, "lon": 2.8214, "district_label": "Girona Barri Vell",
                "avg_household_income": 41000, "area_m2_price": 2600.0, "population_growth_rate": 1.6
            }
        elif "pontevedra" in prov_lower or "vigo" in prov_lower:
            return {
                "address": title, "locality": "Vigo", "province": "Pontevedra",
                "postal_code": "36201", "lat": 42.2406, "lon": -8.7207, "district_label": "Vigo Centro",
                "avg_household_income": 35000, "area_m2_price": 2000.0, "population_growth_rate": 1.2
            }
        elif "almeria" in prov_lower or "almería" in prov_lower:
            return {
                "address": title, "locality": "Almería", "province": "Almería",
                "postal_code": "04001", "lat": 36.8340, "lon": -2.4637, "district_label": "Almería Centro",
                "avg_household_income": 30000, "area_m2_price": 1300.0, "population_growth_rate": 1.5
            }
        elif "castellon" in prov_lower or "castellón" in prov_lower:
            return {
                "address": title, "locality": "Castellón de la Plana", "province": "Castellón",
                "postal_code": "12001", "lat": 39.9864, "lon": -0.0513, "district_label": "Castellón Centro",
                "avg_household_income": 32000, "area_m2_price": 1400.0, "population_growth_rate": 1.3
            }
        elif "salamanca" in prov_lower:
            return {
                "address": title, "locality": "Salamanca", "province": "Salamanca",
                "postal_code": "37001", "lat": 40.9701, "lon": -5.6635, "district_label": "Salamanca Casco",
                "avg_household_income": 33000, "area_m2_price": 1850.0, "population_growth_rate": 0.8
            }
        elif "burgos" in prov_lower:
            return {
                "address": title, "locality": "Burgos", "province": "Burgos",
                "postal_code": "09001", "lat": 42.3440, "lon": -3.6969, "district_label": "Burgos Centro",
                "avg_household_income": 36000, "area_m2_price": 1750.0, "population_growth_rate": 0.9
            }
        
        # Default Madrid
        return {
            "address": title, "locality": "Madrid", "province": "Madrid",
            "postal_code": "28001",
            "lat": 40.4168, "lon": -3.7038, "district_label": "Madrid Centro",
            "avg_household_income": 46000, "area_m2_price": 4800.0, "population_growth_rate": 2.0
        }


class HabitacliaMarkdownParser:
    """
    Parser especializado para extraer oportunidades de Habitaclia.
    """

    @classmethod
    def parse_listings(cls, markdown_content: str, default_province: str = "Barcelona") -> List[Dict[str, Any]]:
        listings: List[Dict[str, Any]] = []
        if not markdown_content:
            return listings

        # Habitaclia: [Ático con ascensor en venta en...](https://www.habitaclia.com/comprar-...)
        # o enlaces con /inmueble/ o /viviendas/
        link_pattern = re.compile(
            r'\[(?P<title>[^\]]+)\]\((?P<url>https?://(?:www\.)?habitaclia\.com/(?:comprar|viviendas)[^\)]*-(?:i(?P<id>\d+)|(?P<alt_id>\d{6,}))\.htm[^\)]*)\)',
            re.IGNORECASE
        )

        matches = list(link_pattern.finditer(markdown_content))
        for i, match in enumerate(matches):
            try:
                item_id = match.group("id") or match.group("alt_id") or str(100000 + i)
                title = match.group("title").strip()
                url = match.group("url")

                # Contexto posterior para precio
                end_post = min(len(markdown_content), match.end() + 800)
                post_text = markdown_content[match.end():end_post]

                price_match = re.search(r'(\d{1,3}(?:\.\d{3})+)\s*€', post_text)
                if not price_match:
                    continue

                listing_price = float(price_match.group(1).replace(".", ""))
                if listing_price < 20000:
                    continue

                # Localización
                loc_data = IdealistaMarkdownParser._resolve_location_and_kpis(title, default_province)

                opportunity = {
                    "id": f"MKT-HABITACLIA-{item_id}",
                    "title": title,
                    "address": title,
                    "locality": loc_data.get("locality", default_province),
                    "province": loc_data.get("province", default_province),
                    "postal_code": loc_data.get("postal_code", "08001"),
                    "lat": loc_data.get("lat"),
                    "lon": loc_data.get("lon"),
                    "property_type": "PISO",
                    "strategy": "HOUSE_FLIPPING",
                    "surface_m2": 85.0,
                    "rooms": 3,
                    "bathrooms": 1,
                    "floor": "3º",
                    "has_elevator": True,
                    "energy_certificate": "E",
                    "original_listing_price": listing_price,
                    "listing_price": listing_price,
                    "first_published_date": "2026-03-01",
                    "publications": [
                        {
                            "portal": "Habitaclia",
                            "price": listing_price,
                            "url": url,
                            "agency": "Inmobiliaria Habitaclia",
                            "published_date": "2026-03-01"
                        }
                    ],
                    "census_tract_data": {
                        "district": loc_data.get("district_label", default_province),
                        "avg_household_income": loc_data.get("avg_household_income", 40000),
                        "avg_person_income": 18000,
                        "area_m2_price": loc_data.get("area_m2_price", 3900.0),
                        "population_growth_rate": 1.5
                    },
                    "images": [],
                    "description": f"{title}. Anuncio verificado en Habitaclia."
                }

                is_solar = (opportunity.get("strategy") == "LAND_DEVELOPMENT" or "solar" in (opportunity.get("property_type") or "").lower() or "terreno" in (opportunity.get("property_type") or "").lower())

                if is_solar:
                    monthly_rent = 0.0
                    rental_yield = 0.0
                    yield_score = 0.0
                    yield_color = "rojo"
                    btl_score = None
                else:
                    # Cálculo de Rentabilidad Bruta Anual de Alquiler (+10% gastos adquisición)
                    monthly_rent = RentalReferenceEngine.estimate_monthly_rent(
                        surface_m2=opportunity["surface_m2"],
                        postal_code=opportunity["postal_code"],
                        province=opportunity["province"],
                        floor=opportunity["floor"],
                        has_elevator=opportunity["has_elevator"]
                    )
                    rental_yield = RentalReferenceEngine.calculate_rental_yield(
                        listing_price=listing_price,
                        monthly_rent=monthly_rent
                    )
                    yield_score, yield_color = RentalReferenceEngine.evaluate_yield(rental_yield)
                    btl_score = yield_score

                area_m2_price = float(loc_data.get("area_m2_price", 3900.0))
                est_market_val = opportunity["surface_m2"] * area_m2_price
                discount_vs_market = round(max(0.0, ((est_market_val - listing_price) / est_market_val) * 100), 1) if est_market_val > 0 else 0.0

                overall_score = KPICalculator.calculate_overall_opportunity_score(
                    discount_percentage=discount_vs_market / 100.0,
                    poi_score=82.0,
                    income_amount=loc_data.get("avg_household_income", 40000),
                    population_growth=loc_data.get("population_growth_rate", 1.5),
                    rental_yield=rental_yield,
                    is_solar=is_solar
                )

                opportunity["estimated_monthly_rent"] = monthly_rent if not is_solar else None
                opportunity["rental_yield"] = rental_yield if not is_solar else None
                opportunity["yield_score"] = yield_score if not is_solar else 0.0
                opportunity["yield_color"] = yield_color if not is_solar else None
                opportunity["btl_score"] = btl_score
                opportunity["btl_color"] = yield_color if not is_solar else None
                opportunity["discount_vs_market"] = discount_vs_market
                opportunity["overall_score"] = overall_score
                opportunity["final_score"] = overall_score

                listings.append(opportunity)
            except Exception as e_hab:
                logger.warning(f"Error parseando item Habitaclia: {e_hab}")

        # Ordenar oportunidades por new primero, luego max(score/descuento, btl) descendente
        listings.sort(
            key=lambda x: (
                1 if x.get("is_new") else 0,
                max(x.get("overall_score") or x.get("discount_score") or 0.0, x.get("btl_score") or 0.0),
                x.get("discount_vs_market") or x.get("discount_percentage") or 0.0
            ),
            reverse=True
        )

        logger.info(f"[Habitaclia Parser] Extraídos {len(listings)} inmuebles con éxito y ordenados por max(score, btl).")
        return listings
