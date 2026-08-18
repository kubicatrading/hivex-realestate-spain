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
