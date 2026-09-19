"""
Motor de Precios de Alquiler de Referencia y Cálculo de Rental Yield.
Permite estimar el precio de alquiler mensual (€/m2) según código postal, provincia y localidad,
ajustado por la altura/planta del inmueble y presencia de ascensor, calculando la rentabilidad
bruta anual con el +10% de costes de adquisición (notaría, impuestos y escrituras).
"""

import re
import logging
from typing import Dict, Any, Tuple

logger = logging.getLogger(__name__)

# Precios medios de referencia de alquiler (€/m2/mes) por prefijo postal (2 dígitos / 3 dígitos) y localidades clave.
# Fuente: Boletines oficiales de alquiler, MITMA (Sistema Estatal de Referencia del Precio del Alquiler) y mercado.
POSTAL_CODE_RENTAL_PRICES: Dict[str, float] = {
    # MADRID (28)
    "28001": 24.5, "28006": 24.0, "28010": 23.5, "28004": 22.5, "28014": 22.5, # Salamanca / Chamberí / Centro
    "28009": 22.0, "28007": 20.5, "28002": 20.0, "28016": 19.5, "28003": 21.0, # Retiro / Chamartín
    "28015": 20.5, "28005": 19.5, "28008": 20.0, "28045": 18.5, # Arganzuela / Moncloa
    "28028": 18.0, "28020": 19.0, "28033": 17.0, "28043": 16.5, # Tetuán / Hortaleza
    "28019": 15.5, "28025": 15.0, "28047": 14.5, "28044": 14.0, # Carabanchel / Latina
    "28018": 14.5, "28038": 14.0, "28053": 13.5, "28031": 14.5, # Vallecas / Villa de Vallecas
    "28032": 14.0, "28052": 14.5, # Vicálvaro / El Cañaveral
    "28": 17.5, # Resto provincia Madrid media

    # BARCELONA (08)
    "08007": 23.5, "08008": 23.5, "08006": 22.0, "08017": 21.5, "08021": 22.5, # Eixample / Sarrià
    "08001": 20.5, "08002": 21.0, "08003": 21.5, "08005": 22.0, # Ciutat Vella / Poblenou
    "08012": 20.0, "08024": 18.5, "08014": 18.0, "08028": 18.0, # Gràcia / Sants / Les Corts
    "08013": 19.5, "08025": 18.5, "08018": 19.0, "08019": 19.5, # Sant Martí / Sagrada Família
    "08016": 15.5, "08031": 15.0, "08030": 15.0, # Nou Barris / Sant Andreu
    "08": 17.8, # Resto provincia Barcelona media

    # VALENCIA (46)
    "46001": 16.0, "46002": 16.5, "46004": 16.0, "46006": 15.5, # Ciutat Vella / Ruzafa / Ensanche
    "46003": 15.0, "46005": 14.5, "46010": 14.5, "46020": 13.5, # Mestalla / Benimaclet
    "46011": 14.0, "46024": 13.5, "46015": 12.5, # Poblats Marítims / Campanar
    "46": 12.8, # Resto provincia Valencia

    # MÁLAGA (29)
    "29001": 17.5, "29015": 17.0, "29016": 16.5, "29008": 16.0, # Centro Histórico / Soho / Malagueta
    "29010": 14.0, "29005": 13.5, "29006": 13.0, "29004": 13.0, # Teatinos / Carretera de Cádiz
    "29601": 18.0, "29602": 18.5, "29640": 15.5, "29620": 15.0, # Marbella / Fuengirola / Torremolinos
    "29": 14.5, # Resto provincia Málaga

    # ALICANTE (03)
    "03001": 13.0, "03002": 12.5, "03003": 12.0, "03005": 11.5, # Alicante Centro / Ensanche
    "03540": 14.5, "03501": 14.0, "03502": 13.5, # Playa San Juan / Benidorm
    "03": 11.2, # Resto provincia Alicante

    # TARRAGONA (43)
    "43001": 11.5, "43003": 11.0, "43004": 10.5, "43005": 10.0, # Tarragona Capital
    "43840": 12.0, "43850": 11.5, "43201": 9.5, # Salou / Cambrils / Reus
    "43": 10.2, # Resto provincia Tarragona

    # TOLEDO (45) - Talavera y La Sagra
    "45600": 8.0, "45694": 7.5, # Talavera de la Reina (altísimo rendimiento sobre precio de compra)
    "45200": 9.5, "45223": 9.0, # Illescas / Seseña (Corredor de La Sagra)
    "45001": 10.0, "45002": 9.8, "45003": 9.5, # Toledo Capital
    "45": 8.6, # Resto provincia Toledo

    # PAÍS VASCO (20, 48, 01)
    "20001": 19.5, "20002": 19.0, "20004": 20.0, "20005": 21.0, "20": 17.5, # San Sebastián / Guipúzcoa
    "48001": 17.5, "48009": 17.0, "48011": 16.5, "48991": 16.5, "48": 15.5, # Bilbao / Getxo / Vizcaya
    "01001": 13.5, "01002": 13.0, "01003": 12.8, "01": 12.2, # Vitoria-Gasteiz / Álava

    # CANTABRIA (39)
    "39001": 13.5, "39005": 15.0, "39004": 14.0, "39": 11.8, # Santander / Cantabria

    # ISLAS CANARIAS (35, 38)
    "35001": 14.0, "35002": 13.5, "35007": 14.5, "35": 13.2, # Las Palmas de Gran Canaria
    "38001": 13.5, "38002": 13.0, "38660": 16.5, "38": 13.0, # Santa Cruz de Tenerife / Adeje

    # BALEARES (07)
    "07001": 18.5, "07002": 18.0, "07012": 17.5, "07": 16.8, # Palma / Baleares

    # SEVILLA (41)
    "41001": 14.5, "41002": 14.0, "41004": 13.5, "41011": 14.0, "41": 11.5, # Sevilla

    # ZARAGOZA (50)
    "50001": 11.5, "50002": 11.0, "50004": 11.2, "50": 10.0, # Zaragoza

    # CÁDIZ (11)
    "11001": 12.5, "11": 10.8, # Cádiz

    # A CORUÑA (15)
    "15001": 12.0, "15": 10.5, # A Coruña

    # ASTURIAS (33)
    "33001": 10.5, "33201": 11.5, "33": 9.8, # Oviedo / Gijón

    # MURCIA (30)
    "30001": 10.0, "30": 8.8, # Murcia

    # VALLADOLID (47)
    "47001": 10.5, "47": 9.2, # Valladolid

    # GRANADA (18)
    "18001": 11.5, "18": 10.0, # Granada

    # CÓRDOBA (14)
    "14001": 10.0, "14": 8.8, # Córdoba

    # GIRONA (17)
    "17001": 13.0, "17": 12.0, # Girona

    # PONTEVEDRA (36)
    "36201": 11.5, "36": 10.2, # Vigo / Pontevedra

    # NAVARRA (31)
    "31001": 12.5, "31": 11.2, # Pamplona / Navarra

    # ALMERÍA (04)
    "04001": 9.0, "04": 8.2, # Almería

    # CASTELLÓN (12)
    "12001": 8.8, "12": 8.0, # Castellón

    # SALAMANCA (37)
    "37001": 10.5, "37": 9.2, # Salamanca

    # BURGOS (09)
    "09001": 9.8, "09": 8.8, # Burgos
}


class RentalReferenceEngine:
    """
    Motor de valoración de alquiler y rentabilidad bruta para oportunidades en España.
    """

    @classmethod
    def get_rental_price_m2(cls, postal_code: str, province: str = "Madrid") -> float:
        """
        Determina el precio medio de alquiler por m2 mensual según código postal o provincia.
        """
        cp = str(postal_code or "").strip()
        
        # 1. Búsqueda exacta de código postal (5 dígitos)
        if len(cp) == 5 and cp in POSTAL_CODE_RENTAL_PRICES:
            return POSTAL_CODE_RENTAL_PRICES[cp]

        # 2. Búsqueda por prefijo provincial de 2 dígitos
        if len(cp) >= 2:
            prov_prefix = cp[:2]
            if prov_prefix in POSTAL_CODE_RENTAL_PRICES:
                return POSTAL_CODE_RENTAL_PRICES[prov_prefix]

        # 3. Fallback por nombre de provincia
        prov_normalized = province.lower().strip()
        prov_map = {
            "madrid": 17.5, "barcelona": 17.8, "valencia": 12.8, "malaga": 14.5,
            "málaga": 14.5, "alicante": 11.2, "tarragona": 10.2, "toledo": 8.6,
            "baleares": 16.8, "las palmas": 13.2, "tenerife": 13.0, "santa cruz de tenerife": 13.0,
            "guipuzcoa": 17.5, "guipúzcoa": 17.5, "gipuzkoa": 17.5, "vizcaya": 15.5,
            "bizkaia": 15.5, "alava": 12.2, "álava": 12.2, "cantabria": 11.8,
            "sevilla": 11.5, "zaragoza": 10.0, "cadiz": 10.8, "cádiz": 10.8,
            "coruña": 10.5, "a coruña": 10.5, "asturias": 9.8, "murcia": 8.8,
            "valladolid": 9.2, "granada": 10.0, "cordoba": 8.8, "córdoba": 8.8,
            "girona": 12.0, "pontevedra": 10.2, "navarra": 11.2, "almeria": 8.2,
            "almería": 8.2, "castellon": 8.0, "castellón": 8.0, "salamanca": 9.2,
            "burgos": 8.8
        }
        for k, v in prov_map.items():
            if k in prov_normalized:
                return v

        return 11.5 # Media nacional estándar de alquiler €/m2/mes

    @classmethod
    def calculate_height_factor(cls, floor_text: str, has_elevator: bool = True) -> float:
        """
        Calcula el factor de corrección por altura y presencia de ascensor:
        - Bajo / Semisótano: 0.90 (menor intimidad y luz)
        - Entreplanta / 1ª planta: 0.95
        - Plantas intermedias (2ª a 4ª con ascensor): 1.00
        - Plantas altas (5ª o superior con ascensor): 1.08 (vistas y luminosidad)
        - Ático con terraza / ascensor: 1.18 (activo premium)
        - Plantas altas (3ª o superior) SIN ascensor: 0.85 (fuerte penalización de demanda)
        """
        txt = (floor_text or "").lower().strip()

        # Ático
        if "ático" in txt or "atico" in txt:
            return 1.18 if has_elevator else 0.92

        # Bajo / Semisótano / Planta baja
        if "bajo" in txt or "semisótano" in txt or "semisotano" in txt or "planta baja" in txt:
            return 0.90

        # Entreplanta
        if "entreplanta" in txt:
            return 0.95

        # Detectar número de planta
        floor_num = 2 # defecto intermedio
        num_match = re.search(r'(\d+)', txt)
        if num_match:
            try:
                floor_num = int(num_match.group(1))
            except ValueError:
                floor_num = 2

        if not has_elevator and floor_num >= 3:
            return 0.85 # Fuerte penalización sin ascensor

        if floor_num == 1:
            return 0.95
        elif 2 <= floor_num <= 4:
            return 1.00
        else: # 5 o superior
            return 1.08 if has_elevator else 0.80

    @classmethod
    def estimate_monthly_rent(
        cls,
        surface_m2: float,
        postal_code: str,
        province: str = "Madrid",
        floor: str = "2ª planta",
        has_elevator: bool = True
    ) -> float:
        """
        Calcula el alquiler mensual de mercado (€/mes):
        Superficie (m2) * Precio m2 Alquiler (CP) * Factor de Altura/Ascensor
        """
        surf = surface_m2 if surface_m2 and surface_m2 > 0 else 80.0
        ref_price_m2 = cls.get_rental_price_m2(postal_code, province)
        factor = cls.calculate_height_factor(floor, has_elevator)
        monthly_rent = surf * ref_price_m2 * factor
        return round(monthly_rent, 2)

    @classmethod
    def calculate_rental_yield(
        cls,
        listing_price: float,
        monthly_rent: float
    ) -> float:
        """
        Calcula el porcentaje de rentabilidad bruta anual:
        (Alquiler Anual) / (Precio Adquisición + 10% gastos de notaría y escrituras) * 100
        """
        if not listing_price or listing_price <= 0:
            return 0.0

        total_acquisition_cost = listing_price * 1.10 # +10% gastos
        annual_rent = monthly_rent * 12.0
        yield_pct = (annual_rent / total_acquisition_cost) * 100.0
        return round(yield_pct, 2)

    @classmethod
    def evaluate_yield(cls, rental_yield: float) -> Tuple[float, str]:
        """
        Evalúa el yield según la escala oficial de HIVEX:
        1. >= 7.0% -> 100 puntos (verde)
        2. >= 6.0% y < 7.0% -> 90 puntos (amarillo)
        3. >= 5.0% y < 6.0% -> 80 puntos (naranja)
        4. < 5.0% -> 0 puntos (rojo)
        """
        if rental_yield >= 7.0:
            return 100.0, "verde"
        elif rental_yield >= 6.0:
            return 90.0, "amarillo"
        elif rental_yield >= 5.0:
            return 80.0, "naranja"
        else:
            return 0.0, "rojo"
