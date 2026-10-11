"""
Motor de Estrategia y Ponderación Dinámica de Portales Inmobiliarios en España para HIVEX.
Determina la cuota de búsqueda y distribución proporcional de oportunidades por portal
en función de la tipología de inmueble, el ámbito geográfico y la estrategia de inversión
especificada en las consultas del Asesor de Telegram y búsquedas Out-of-HIVEX.
"""

import re
import unicodedata
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


class PortalStrategyEngine:
    """
    Despachador Inteligente de Prospección Multi-Portal (Context-Aware Multi-Portal Dispatcher).
    Aplica matrices de ponderación empíricas basadas en la penetración de mercado
    y riqueza de datos de cada portal inmobiliario en España:
    - Idealista: Líder urbano indiscutible en grandes capitales, residencial y rebajas.
    - Fotocasa: Líder en costa, segunda residencia, alquiler y obra nueva.
    - Habitaclia: Muy fuerte en suelo, fincas periféricas, Cataluña y Baleares.
    - Pisos.com: Muy fuerte en carteras de servicers bancarios y España interior.
    - Milanuncios: Rey indiscutible en fincas rústicas, parcelas y venta directa C2C (particular).
    - YaEncontré: Excelente nicho urbano en Cataluña, Madrid y carteras de agencias medianas.
    """

    PORTALS = [
        "Idealista",
        "Fotocasa",
        "Habitaclia",
        "Pisos.com",
        "Milanuncios",
        "YaEncontré"
    ]

    # Matriz 1: Pesos por Tipología de Inmueble y Objetivo de Inversión (W_tipo)
    ASSET_TYPE_WEIGHTS: Dict[str, Dict[str, float]] = {
        "RUSTICO_TERRENOS": {
            "Idealista": 0.15,
            "Fotocasa": 0.15,
            "Habitaclia": 0.25,
            "Pisos.com": 0.10,
            "Milanuncios": 0.30,
            "YaEncontré": 0.05
        },
        "PISO_URBANO": {
            "Idealista": 0.45,
            "Fotocasa": 0.25,
            "Habitaclia": 0.15,
            "Pisos.com": 0.10,
            "Milanuncios": 0.00,
            "YaEncontré": 0.05
        },
        "CHALET_UNIFAMILIAR": {
            "Idealista": 0.35,
            "Fotocasa": 0.25,
            "Habitaclia": 0.20,
            "Pisos.com": 0.10,
            "Milanuncios": 0.05,
            "YaEncontré": 0.05
        },
        "BTL_ALQUILER": {
            "Idealista": 0.35,
            "Fotocasa": 0.25,
            "Habitaclia": 0.15,
            "Pisos.com": 0.20,
            "Milanuncios": 0.00,
            "YaEncontré": 0.05
        },
        "GANGAS_DESCUENTO": {
            "Idealista": 0.20,
            "Fotocasa": 0.15,
            "Habitaclia": 0.15,
            "Pisos.com": 0.30,
            "Milanuncios": 0.15,
            "YaEncontré": 0.05
        },
        "PARTICULAR_DIRECTO": {
            "Idealista": 0.10,
            "Fotocasa": 0.05,
            "Habitaclia": 0.10,
            "Pisos.com": 0.10,
            "Milanuncios": 0.60,
            "YaEncontré": 0.05
        },
        "COMERCIAL_LOCALES": {
            "Idealista": 0.40,
            "Fotocasa": 0.20,
            "Habitaclia": 0.15,
            "Pisos.com": 0.15,
            "Milanuncios": 0.05,
            "YaEncontré": 0.05
        },
        "GENERICO": {
            "Idealista": 0.35,
            "Fotocasa": 0.25,
            "Habitaclia": 0.20,
            "Pisos.com": 0.12,
            "Milanuncios": 0.05,
            "YaEncontré": 0.03
        }
    }

    # Matriz 2: Pesos por Ámbito Geográfico (W_geo)
    GEOGRAPHY_WEIGHTS: Dict[str, Dict[str, float]] = {
        "GRANDES_CAPITALES": {  # Madrid, Barcelona
            "Idealista": 0.45,
            "Fotocasa": 0.25,
            "Habitaclia": 0.15,
            "Pisos.com": 0.10,
            "Milanuncios": 0.00,
            "YaEncontré": 0.05
        },
        "CORONA_METROPOLITANA": {  # Móstoles, Leganés, Terrassa, Badalona...
            "Idealista": 0.35,
            "Fotocasa": 0.25,
            "Habitaclia": 0.20,
            "Pisos.com": 0.10,
            "Milanuncios": 0.05,
            "YaEncontré": 0.05
        },
        "CIUDADES_MEDIAS": {  # Zaragoza, Valladolid, Santander, Córdoba...
            "Idealista": 0.30,
            "Fotocasa": 0.25,
            "Habitaclia": 0.15,
            "Pisos.com": 0.20,
            "Milanuncios": 0.05,
            "YaEncontré": 0.05
        },
        "RURAL_SIERRA": {  # Sierra de Madrid, pueblos, zonas de montaña, campo
            "Idealista": 0.15,
            "Fotocasa": 0.10,
            "Habitaclia": 0.20,
            "Pisos.com": 0.15,
            "Milanuncios": 0.35,
            "YaEncontré": 0.05
        },
        "COSTA_ISLAS": {  # Alicante, Málaga, Costa Brava, Baleares, Canarias
            "Idealista": 0.25,
            "Fotocasa": 0.35,
            "Habitaclia": 0.20,
            "Pisos.com": 0.10,
            "Milanuncios": 0.05,
            "YaEncontré": 0.05
        },
        "CATALUNA": {  # Cataluña en general
            "Idealista": 0.25,
            "Fotocasa": 0.20,
            "Habitaclia": 0.35,
            "Pisos.com": 0.10,
            "Milanuncios": 0.05,
            "YaEncontré": 0.05
        },
        "INTERIOR_CASTILLA": {  # Castilla y León, Castilla-La Mancha, Extremadura
            "Idealista": 0.25,
            "Fotocasa": 0.15,
            "Habitaclia": 0.10,
            "Pisos.com": 0.30,
            "Milanuncios": 0.15,
            "YaEncontré": 0.05
        },
        "NACIONAL_GENERICO": {
            "Idealista": 0.35,
            "Fotocasa": 0.25,
            "Habitaclia": 0.20,
            "Pisos.com": 0.12,
            "Milanuncios": 0.05,
            "YaEncontré": 0.03
        }
    }

    @staticmethod
    def _normalize_text(text: str) -> str:
        if not text:
            return ""
        nfd = unicodedata.normalize('NFKD', text)
        return "".join(c for c in nfd if not unicodedata.combining(c)).lower().strip()

    @classmethod
    def detect_asset_type(cls, query_text: str, property_type: Optional[str] = None) -> str:
        """
        Infiere la categoría de activo a partir del texto y metadatos.
        """
        combined = cls._normalize_text(f"{query_text} {property_type or ''}")

        # 1. Rústico / Terrenos / Suelo
        if any(w in combined for w in [
            "rustico", "rustica", "finca", "terreno", "parcela", "suelo", "olivar",
            "vinedo", "recreo", "campo", "agrario", "agricola", "dehesa", "huerto"
        ]):
            return "RUSTICO_TERRENOS"

        # 2. Particular directo / Sin agencia
        if any(w in combined for w in ["particular", "sin agencia", "sin comision", "directo"]):
            return "PARTICULAR_DIRECTO"

        # 3. Gangas / Descuento alto / Reposeídos / Banco
        if any(w in combined for w in ["ganga", "banco", "bancario", "embargo", "rebaja", "descuento", "reposeido", "oportunidad de banco"]):
            return "GANGAS_DESCUENTO"

        # 4. Alquiler / Buy-to-let / Yield
        if any(w in combined for w in ["alquilar", "alquiler", "rentabilidad", "yield", "btl", "renta"]):
            return "BTL_ALQUILER"

        # 5. Chalets / Unifamiliares
        if any(w in combined for w in ["chalet", "unifamiliar", "adosado", "independiente", "pareado", "villa"]):
            return "CHALET_UNIFAMILIAR"

        # 6. Comercial / Locales / Naves
        if any(w in combined for w in ["local", "comercial", "nave", "oficina", "edificio"]):
            return "COMERCIAL_LOCALES"

        # 7. Pisos / Áticos (Residencial urbano estándar)
        if any(w in combined for w in ["piso", "atico", "apartamento", "estudio", "vivienda"]):
            return "PISO_URBANO"

        return "GENERICO"

    @classmethod
    def detect_geography(cls, query_text: str, province: Optional[str] = None, zone: Optional[str] = None) -> str:
        """
        Infiere la clasificación geográfica de la consulta.
        """
        combined = cls._normalize_text(f"{query_text} {province or ''} {zone or ''}")

        # Cataluña
        if any(w in combined for w in ["barcelona", "girona", "gerona", "tarragona", "lleida", "lerida", "cataluna"]):
            if "barcelona capital" in combined or "barcelona ciudad" in combined or re.search(r'\bbarcelona\b', combined):
                return "GRANDES_CAPITALES"
            return "CATALUNA"

        # Sierra / Rural
        if any(w in combined for w in [
            "sierra", "pueblo", "guadalix", "soto del real", "manzanares", "torrelaguna",
            "bustarviejo", "miraflores", "pedrezuela", "buitrago", "rascafria", "el berrueco",
            "zarzalejo", "escorial", "navacerrada", "cercedilla", "moralzarzal", "collado",
            "campo", "valle", "montana", "espana vaciada"
        ]):
            return "RURAL_SIERRA"

        # Grandes Capitales (Madrid Centro/Distritos)
        if any(w in combined for w in [
            "madrid capital", "madrid centro", "chamberi", "salamanca", "retiro", "chamartin",
            "tetuan", "centro", "vallecas", "carabanchel", "malasana", "chueca", "arguelles",
            "recoletos", "almagro", "goya", "barcelona capital"
        ]) or (re.search(r'\bmadrid\b', combined) and not any(w in combined for w in ["sierra", "pueblo", "finca", "terreno"])):
            return "GRANDES_CAPITALES"

        # Corona Metropolitana
        if any(w in combined for w in [
            "mostoles", "alcorcon", "leganes", "getafe", "fuenlabrada", "parla", "pinto", "valdemoro",
            "alcobendas", "san sebastian de los reyes", "majadahonda", "las rozas", "pozuelo", "boadilla",
            "alcala de henares", "torrejon", "coslada", "san fernando", "rivas", "arganda",
            "hospitalet", "badalona", "santa coloma", "terrassa", "sabadell", "sant cugat"
        ]):
            return "CORONA_METROPOLITANA"

        # Costa e Islas
        if any(w in combined for w in [
            "costa", "playa", "alicante", "malaga", "marbella", "benidorm", "torrevieja",
            "palma", "mallorca", "ibiza", "menorca", "baleares", "tenerife", "las palmas",
            "canarias", "cadiz", "almeria", "valencia", "castellon"
        ]):
            return "COSTA_ISLAS"

        # Interior y Castilla
        if any(w in combined for w in [
            "toledo", "ciudad real", "guadalajara", "cuenca", "albacete",
            "valladolid", "burgos", "leon", "salamanca", "segovia", "avila", "soria", "palencia", "zamora",
            "badajoz", "caceres", "extremadura", "castilla"
        ]):
            return "INTERIOR_CASTILLA"

        # Ciudades Medias
        if any(w in combined for w in [
            "zaragoza", "sevilla", "bilbao", "donostia", "san sebastian", "vitoria", "pamplona",
            "oviedo", "gijon", "santander", "coruna", "vigo", "santiago", "murcia", "cordoba", "granada"
        ]):
            return "CIUDADES_MEDIAS"

        return "NACIONAL_GENERICO"

    @classmethod
    def calculate_weights(
        cls,
        query_text: str = "",
        property_type: Optional[str] = None,
        province: Optional[str] = None,
        zone: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Calcula la ponderación óptima de portales combinando:
        W_final(p) = 0.60 * W_tipo(p) + 0.40 * W_geo(p)
        """
        asset_cat = cls.detect_asset_type(query_text, property_type)
        geo_cat = cls.detect_geography(query_text, province, zone)

        w_tipo = cls.ASSET_TYPE_WEIGHTS.get(asset_cat, cls.ASSET_TYPE_WEIGHTS["GENERICO"])
        w_geo = cls.GEOGRAPHY_WEIGHTS.get(geo_cat, cls.GEOGRAPHY_WEIGHTS["NACIONAL_GENERICO"])

        # Ponderación 60% tipo + 40% geo
        final_weights: Dict[str, float] = {}
        for p in cls.PORTALS:
            val = (0.60 * w_tipo.get(p, 0.0)) + (0.40 * w_geo.get(p, 0.0))
            final_weights[p] = round(val, 4)

        # Normalizar para asegurar suma 1.0 exacta
        tot = sum(final_weights.values())
        if tot > 0:
            final_weights = {p: round(v / tot, 4) for p, v in final_weights.items()}

        return {
            "asset_category": asset_cat,
            "geography_category": geo_cat,
            "weights": final_weights
        }

    @classmethod
    def allocate_portal_quotas(
        cls,
        total_count: int = 20,
        query_text: str = "",
        property_type: Optional[str] = None,
        province: Optional[str] = None,
        zone: Optional[str] = None
    ) -> Dict[str, int]:
        """
        Reparte el cupo total (ej: 20 oportunidades) de forma entera entre los 6 portales
        respetando las fortalezas del mercado y garantizando que el total sume exactamente total_count.
        """
        calc = cls.calculate_weights(query_text, property_type, province, zone)
        weights = calc["weights"]

        # 1. Asignación inicial proporcional
        allocations: Dict[str, int] = {}
        for p, w in weights.items():
            allocations[p] = int(round(total_count * w))

        # 2. Ajuste de residuo
        diff = total_count - sum(allocations.values())
        if diff != 0:
            # Asignar residuo al portal con mayor peso
            sorted_portals = sorted(weights.items(), key=lambda x: x[1], reverse=True)
            top_portal = sorted_portals[0][0]
            allocations[top_portal] += diff

        # 3. Si el cupo es significativo (>= 15), asegurar al menos 1 oportunidad
        # en portales relevantes con peso >= 0.08
        if total_count >= 15:
            for p, w in weights.items():
                if w >= 0.08 and allocations[p] < 1:
                    allocations[p] = 1

            # Reajustar residuo si varió
            diff_adj = total_count - sum(allocations.values())
            if diff_adj != 0:
                sorted_portals = sorted(weights.items(), key=lambda x: x[1], reverse=True)
                top_portal = sorted_portals[0][0]
                allocations[top_portal] += diff_adj

        logger.info(
            f"[PortalStrategyEngine] Asignación para N={total_count} "
            f"({calc['asset_category']} / {calc['geography_category']}): {allocations}"
        )
        return allocations
