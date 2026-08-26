import pytest
from app.engine.kpi_calculator import KPICalculator
from app.db.models import StrategyType

def test_strategy_determination():
    assert KPICalculator.determine_strategy("Vivienda residencial") == StrategyType.HOUSE_FLIPPING
    assert KPICalculator.determine_strategy("Solar urbano edificable") == StrategyType.LAND_DEVELOPMENT
    assert KPICalculator.determine_strategy("Terreno rústico / Parcela") == StrategyType.LAND_DEVELOPMENT

def test_discount_calculation():
    listing_price = 190000.0
    market_value = 350000.0
    discount = KPICalculator.calculate_discount_percentage(listing_price, market_value)
    assert round(discount, 4) == 0.4571 # 45.71% discount

def test_overall_opportunity_score():
    score = KPICalculator.calculate_overall_opportunity_score(
        discount_percentage=0.45,
        poi_score=90.0,
        income_amount=48000.0,
        population_growth=2.5
    )
    assert 70.0 <= score <= 100.0

def test_2x2_market_price_resolution():
    from app.engine.meso_market_price import resolve_meso_market_price_2x2
    
    # Daganzo de Arriba (Solar Urbano)
    price, source, label = resolve_meso_market_price_2x2(
        province_str="Madrid",
        locality_str="DAGANZO DE ARRIBA",
        full_address_str="CALLE CUESTA DEL REY, Nº 13, DAGANZO DE ARRIBA, Madrid",
        desc_text="Subasta de Solar en Daganzo de Arriba",
        land_type="URBANO",
        is_solar=True
    )
    assert price == 450.0
    assert "DAGANZO DE ARRIBA" in label
    assert "Madrid" not in label or "DAGANZO" in label

    # San Blas Madrid (Inmueble Urbano CP 28037)
    price_sb, source_sb, label_sb = resolve_meso_market_price_2x2(
        province_str="Madrid",
        locality_str="Madrid",
        full_address_str="Calle Tejedores, 21 - CP: 28037, Madrid",
        desc_text="LOCAL COMERCIAL LC-3",
        land_type="URBANO",
        is_solar=False
    )
    assert price_sb == 2800.0
    assert "San Blas" in label_sb

def test_surface_extraction_written_m2():
    from app.connectors.boe_scraper import BOESubastasScraper
    scraper = BOESubastasScraper()
    text = "CIENTO DIECIOCHO.- LOCAL COMERCIAL LC-3, situado en planta baja del portal número 21 de la calle Tejedores, San Blas, término municipal de Madrid. Tiene una superficie construida de treinta y dos metros cuadrados -32,00 m2- y una superficie útil de veintitrés metros cuarenta decímetros cuadrados -23,40 m2-."
    extracted = scraper.extract_surface_m2(text)
    assert extracted == 32.0
