import logging
from typing import Dict, Any, Optional
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
        if not surface_m2 or surface_m2 <= 0:
            surface_m2 = 90.0 # Fallback estándar vivienda en España

        if not reference_price_m2 or reference_price_m2 <= 0:
            reference_price_m2 = 1850.0 # Fallback precio medio España m2

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
        return max(0.0, round(discount, 4))

    @staticmethod
    def calculate_yield_score(rental_yield: float) -> float:
        """
        Escala oficial HIVEX:
        1. >= 7.0% -> 100 puntos (verde)
        2. >= 6.0% y < 7.0% -> 90 puntos (amarillo)
        3. >= 5.0% y < 6.0% -> 80 puntos (naranja)
        4. >= 4.0% y < 5.0% -> 50 puntos (naranja_rojizo - degradado hacia rojo)
        5. < 4.0% -> 0 puntos (rojo)
        """
        if rental_yield >= 7.0:
            return 100.0
        elif rental_yield >= 6.0:
            return 90.0
        elif rental_yield >= 5.0:
            return 80.0
        elif rental_yield >= 4.0:
            return 50.0
        else:
            return 0.0

    @staticmethod
    def get_yield_color(rental_yield: float) -> str:
        """Color semafórico oficial para rentabilidad de alquiler."""
        if rental_yield >= 7.0:
            return "verde"
        elif rental_yield >= 6.0:
            return "amarillo"
        elif rental_yield >= 5.0:
            return "naranja"
        elif rental_yield >= 4.0:
            return "naranja_rojizo"
        else:
            return "rojo"

    @staticmethod
    def calculate_btl_score(rental_yield: float, is_solar: bool = False) -> Optional[float]:
        """Calcula el score BTL (Buy To Let). Para solares se obvia devolviendo None."""
        if is_solar:
            return None
        return KPICalculator.calculate_yield_score(rental_yield)

    @staticmethod
    def get_btl_color(rental_yield: float, is_solar: bool = False) -> Optional[str]:
        """Retorna el color semafórico BTL. Para solares se obvia devolviendo None."""
        if is_solar:
            return None
        return KPICalculator.get_yield_color(rental_yield)

    @staticmethod
    def calculate_detailed_scores(
        discount_percentage: float,
        poi_score: float,
        income_amount: float,
        population_growth: float,
        has_property_m2_price: bool = True,
        rental_yield: float = 0.0,
        is_solar: bool = False
    ) -> Dict[str, Any]:
        """
        Calcula el desglose completo de puntuaciones (0 - 100 pts) para cada dimensión:
        - discount_score (50%) - Pondera 0 si no hay precio de inmueble por m2
        - poi_score (20%)
        - income_score (15%)
        - demographic_score (15%)
        - overall_score (Total) = 0.50*descuento + 0.20*POI + 0.15*Renta + 0.15*Demografía
        - btl_score (Buy to Let): evaluado por separado según rendimiento de alquiler (None para solares)
        """
        if not has_property_m2_price or discount_percentage <= 0:
            discount_score = 0.0
        else:
            discount_score = min(100.0, max(0.0, (discount_percentage / 0.50) * 100.0))

        income_score = min(100.0, max(0.0, (income_amount / 45000.0) * 100.0))
        demographic_score = min(100.0, max(0.0, (population_growth / 3.0) * 100.0))
        
        # BTL Score independiente (None si es solar)
        btl_score = KPICalculator.calculate_btl_score(rental_yield, is_solar=is_solar)
        btl_color = KPICalculator.get_btl_color(rental_yield, is_solar=is_solar)

        overall = (
            (discount_score * 0.50) +
            (poi_score * 0.20) +
            (income_score * 0.15) +
            (demographic_score * 0.15)
        )

        return {
            "discount_score": round(discount_score, 1),
            "income_score": round(income_score, 1),
            "demographic_score": round(demographic_score, 1),
            "poi_score": round(poi_score, 1),
            "yield_score": round(btl_score, 1) if btl_score is not None else 0.0,
            "btl_score": round(btl_score, 1) if btl_score is not None else None,
            "yield_color": btl_color or "rojo",
            "btl_color": btl_color,
            "rental_yield": round(rental_yield, 2) if not is_solar else None,
            "overall_score": round(overall, 1)
        }

    @staticmethod
    def calculate_overall_opportunity_score(
        discount_percentage: float,
        poi_score: float,
        income_amount: float,
        population_growth: float,
        rental_yield: float = 0.0,
        is_solar: bool = False
    ) -> float:
        """
        Algoritmo de puntuación ponderado original (0 - 100 puntos):
        Score = 0.50*descuento + 0.20*POI + 0.15*Renta + 0.15*Demografía
        """
        scores = KPICalculator.calculate_detailed_scores(
            discount_percentage,
            poi_score,
            income_amount,
            population_growth,
            rental_yield=rental_yield,
            is_solar=is_solar
        )
        return scores["overall_score"]


