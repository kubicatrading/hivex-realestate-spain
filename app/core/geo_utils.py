import unicodedata
import random
from typing import Tuple, Optional

# Coordenadas geográficas oficiales WGS84 para las 52 provincias y principales municipios de España
PROVINCE_COORDS_MAP = {
    # Andalucía
    "almeria": (36.8340, -2.4637),
    "cadiz": (36.5271, -6.2886),
    "cordoba": (37.8882, -4.7794),
    "granada": (37.1773, -3.5986),
    "huelva": (37.2614, -6.9447),
    "jaen": (37.7796, -3.7849),
    "malaga": (36.7213, -4.4214),
    "sevilla": (37.3891, -5.9845),
    # Aragón
    "huesca": (42.1361, -0.4087),
    "teruel": (40.3456, -1.1072),
    "zaragoza": (41.6488, -0.8891),
    # Asturias
    "asturias": (43.3614, -5.8593),
    "oviedo": (43.3614, -5.8593),
    "gijon": (43.5357, -5.6615),
    # Baleares
    "baleares": (39.5696, 2.6502),
    "balears": (39.5696, 2.6502),
    "palma": (39.5696, 2.6502),
    "ibiza": (38.9067, 1.4206),
    "eivissa": (38.9067, 1.4206),
    "menorca": (39.8885, 4.2658),
    # Canarias
    "las palmas": (28.1235, -15.4363),
    "gran canaria": (28.1235, -15.4363),
    "lanzarote": (28.9630, -13.5477),
    "fuerteventura": (28.5008, -13.8627),
    "santa cruz de tenerife": (28.4636, -16.2518),
    "tenerife": (28.4636, -16.2518),
    "la palma": (28.6835, -17.7642),
    "la gomera": (28.0916, -17.1133),
    "el hierro": (27.8073, -17.9158),
    # Cantabria
    "cantabria": (43.4647, -3.8044),
    "santander": (43.4647, -3.8044),
    # Castilla-La Mancha
    "albacete": (38.9942, -1.8585),
    "ciudad real": (38.9863, -3.9271),
    "cuenca": (40.0704, -2.1374),
    "guadalajara": (40.6327, -3.1601),
    "toledo": (39.8628, -4.0273),
    # Castilla y León
    "avila": (40.6565, -4.6818),
    "burgos": (42.3408, -3.6997),
    "leon": (42.5987, -5.5671),
    "palencia": (42.0095, -4.5283),
    "salamanca": (40.9701, -5.6635),
    "segovia": (40.9429, -4.1088),
    "soria": (41.7640, -2.4688),
    "valladolid": (41.6523, -4.7245),
    "zamora": (41.5063, -5.7445),
    # Cataluña
    "barcelona": (41.3851, 2.1734),
    "girona": (41.9794, 2.8214),
    "gerona": (41.9794, 2.8214),
    "lleida": (41.6176, 0.6200),
    "lerida": (41.6176, 0.6200),
    "tarragona": (41.1189, 1.2445),
    # Extremadura
    "badajoz": (38.8794, -6.9707),
    "caceres": (39.4765, -6.3722),
    # Galicia
    "a coruna": (43.3623, -8.4115),
    "coruna": (43.3623, -8.4115),
    "la coruna": (43.3623, -8.4115),
    "lugo": (43.0097, -7.5568),
    "ourense": (42.3358, -7.8639),
    "orense": (42.3358, -7.8639),
    "pontevedra": (42.4336, -8.6480),
    "vigo": (42.2406, -8.7207),
    # Madrid
    "madrid": (40.4168, -3.7038),
    # Murcia
    "murcia": (37.9922, -1.1307),
    # Navarra
    "navarra": (42.8125, -1.6458),
    "pamplona": (42.8125, -1.6458),
    # País Vasco
    "alava": (42.8467, -2.6716),
    "araba": (42.8467, -2.6716),
    "vitoria": (42.8467, -2.6716),
    "bizkaia": (43.2630, -2.9350),
    "vizcaya": (43.2630, -2.9350),
    "bilbao": (43.2630, -2.9350),
    "gipuzkoa": (43.3183, -1.9812),
    "guipuzcoa": (43.3183, -1.9812),
    "san sebastian": (43.3183, -1.9812),
    # La Rioja
    "la rioja": (42.4650, -2.4456),
    "logrono": (42.4650, -2.4456),
    # Comunitat Valenciana
    "alicante": (38.3452, -0.4810),
    "alacant": (38.3452, -0.4810),
    "castellon": (39.9864, -0.0513),
    "castello": (39.9864, -0.0513),
    "valencia": (39.4699, -0.3763),
    # Ceuta & Melilla
    "ceuta": (35.8894, -5.3213),
    "melilla": (35.2923, -2.9381)
}

def normalize_text(text: Optional[str]) -> str:
    """Normaliza texto eliminando acentos y espacios adicionales."""
    if not text:
        return ""
    text = text.lower().strip()
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')

def get_spanish_province_coords(province_str: Optional[str], locality_str: Optional[str] = None, apply_jitter: bool = False) -> Tuple[float, float]:
    """
    Geolocaliza de forma precisa una provincia/localidad en España.
    Aplica micro-desplazamiento opcional para evitar superposición de chinchetas en la misma ciudad.
    """
    p_norm = normalize_text(province_str)
    l_norm = normalize_text(locality_str)

    base_lat, base_lon = (40.4168, -3.7038) # Default Madrid si no se encuentra
    found = False

    # 1. Comprobar primero en la localidad (ordenado por longitud descendente)
    if l_norm:
        for key in sorted(PROVINCE_COORDS_MAP.keys(), key=len, reverse=True):
            if key in l_norm:
                base_lat, base_lon = PROVINCE_COORDS_MAP[key]
                found = True
                break

    # 2. Si no coincide la localidad, comprobar partes de la provincia (ej. "Valencia/València" -> "valencia")
    if not found and p_norm:
        parts = [p.strip() for p in p_norm.replace('/', ' ').replace('-', ' ').split()]
        for part in parts:
            if part in PROVINCE_COORDS_MAP:
                base_lat, base_lon = PROVINCE_COORDS_MAP[part]
                found = True
                break

    # 3. Comprobar subcadena completa en provincia
    if not found and p_norm:
        for key in sorted(PROVINCE_COORDS_MAP.keys(), key=len, reverse=True):
            if key in p_norm:
                base_lat, base_lon = PROVINCE_COORDS_MAP[key]
                found = True
                break

    if apply_jitter:
        jitter_lat = random.uniform(-0.02, 0.02)
        jitter_lon = random.uniform(-0.02, 0.02)
        return (round(base_lat + jitter_lat, 6), round(base_lon + jitter_lon, 6))

    return (base_lat, base_lon)
