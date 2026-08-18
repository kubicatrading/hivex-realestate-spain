import logging
from typing import Dict, Any
from app.db.models import StrategyType

logger = logging.getLogger(__name__)

class KPICalculator:
    """
    Módulo de cálculo de KPIs para oportunidades de inversión en España.
    
    KPI 1: Precio Real de Mercado (Baseline €/m2)
    KPI 2: Presión de Oferta y Demanda (Evolución poblacional)
    KPI 3: Nivel Adquisitivo (Renta por Hogar INE)
    KPI 4: Servicios y POIs (Conexión transporte y equipamientos OSM)
    """

    @staticmethod
    def determine_strategy(property_type: str) -> StrategyType:
        """Determina la estrategia inversora principal."""
        pt_lower = property_type.lower()
        if "solar" in pt_lower or "terreno" in pt_lower or "parcela" in pt_lower or "suelo" in pt_lower:
            return StrategyType.LAND_DEVELOPMENT
        return StrategyType.HOUSE_FLIPPING

    @staticmethod
    def calculate_estimated_market_value(
        surface_m2: float,
        reference_price_m2: float,
        strategy: StrategyType
    ) -> float:
        """
        Calcula el valor teórico total de mercado del activo.
        Para House Flipping: Superficie * Precio Referencia m2
        Para Land/Solar: Superficie parcelaria * Precio Suelo m2 (edificabilidad)
        """
        if surface_m2 <= 0:
            surface_m2 = 90.0 # Fallback estándar vivienda en España

        if strategy == StrategyType.LAND_DEVELOPMENT:
            # En suelo se aplica ratio de repercusión de edificabilidad habitual (~1.1 a 1.25)
            estimated_value = surface_m2 * reference_price_m2 * 1.15
        else:
            estimated_value = surface_m2 * reference_price_m2

        return round(estimated_value, 2)

    @staticmethod
    def calculate_discount_percentage(listing_price: float, estimated_market_value: float) -> float:
        """
        Calcula el porcentaje de descuento / margen bruto frente al mercado.
        Ejemplo: Salida = 190.000€, Mercado = 361.000€ -> Descuento = 0.4737 (47.37%)
        """
        if estimated_market_value <= 0 or listing_price <= 0:
            return 0.0

        discount = (estimated_market_value - listing_price) / estimated_market_value
        return round(discount, 4)

    @staticmethod
    def calculate_overall_opportunity_score(
        discount_percentage: float,
        poi_score: float,
        income_amount: float,
        population_growth: float
    ) -> float:
        """
        Algoritmo de puntuación ponderado (0 - 100 puntos):
        - 50% Peso: Porcentaje de Descuento
        - 20% Peso: Densidad de POIs (OSM)
        - 15% Peso: Renta Media de la Sección Censal (INE)
        - 15% Peso: Crecimiento Poblacional (INE)
        """
        # Score por descuento (0% desc = 0 pts, 50%+ desc = 100 pts)
        discount_score = min(100.0, max(0.0, (discount_percentage / 0.50) * 100.0))

        # Score por renta (Renta media nacional ~32.000€)
        income_score = min(100.0, max(0.0, (income_amount / 45000.0) * 100.0))

        # Score por crecimiento poblacional (> 2% es excelente)
        demographic_score = min(100.0, max(0.0, (population_growth / 3.0) * 100.0))

        # Ponderación final
        overall = (
            (discount_score * 0.50) +
            (poi_score * 0.20) +
            (income_score * 0.15) +
            (demographic_score * 0.15)
        )

        return round(overall, 2)
