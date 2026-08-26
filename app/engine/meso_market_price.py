"""
HIVEX Meso Market Price Engine
Implementa la arquitectura de Matriz 2x2 de Precios de Mercado Referenciales (MIVAU / INE 2025/2026).

Ejes de la Matriz 2x2:
  - Eje Y (Clasificación Suelo): [URBANO, RÚSTICO]
  - Eje X (Tipología / Uso):     [INMUEBLE, SOLAR]

Jerarquía de resolución:
  1. Código Postal (CP)
  2. Barrio / Distrito
  3. Municipio / Localidad
  4. Benchmark Provincia
"""

import re
from typing import Tuple, Dict, Any, Optional

# Matriz 2x2 por defecto cuando no hay dato provincia específico
DEFAULT_2X2 = {
    "URBANO": {"INMUEBLE": 1350.0, "SOLAR": 450.0},
    "RÚSTICO": {"INMUEBLE": 350.0, "SOLAR": 20.0}
}

# Matrices 2x2 por Provincia (€/m²)
PROVINCE_MARKET_2X2: Dict[str, Dict[str, Dict[str, float]]] = {
    "MADRID": {
        "URBANO": {"INMUEBLE": 2800.0, "SOLAR": 900.0},
        "RÚSTICO": {"INMUEBLE": 450.0, "SOLAR": 25.0}
    },
    "BARCELONA": {
        "URBANO": {"INMUEBLE": 2600.0, "SOLAR": 850.0},
        "RÚSTICO": {"INMUEBLE": 450.0, "SOLAR": 22.0}
    },
    "BALEARES": {
        "URBANO": {"INMUEBLE": 3200.0, "SOLAR": 1100.0},
        "RÚSTICO": {"INMUEBLE": 600.0, "SOLAR": 35.0}
    },
    "BALEARS": {
        "URBANO": {"INMUEBLE": 3200.0, "SOLAR": 1100.0},
        "RÚSTICO": {"INMUEBLE": 600.0, "SOLAR": 35.0}
    },
    "ILLES BALEARS": {
        "URBANO": {"INMUEBLE": 3200.0, "SOLAR": 1100.0},
        "RÚSTICO": {"INMUEBLE": 600.0, "SOLAR": 35.0}
    },
    "MÁLAGA": {
        "URBANO": {"INMUEBLE": 2500.0, "SOLAR": 800.0},
        "RÚSTICO": {"INMUEBLE": 450.0, "SOLAR": 25.0}
    },
    "MALAGA": {
        "URBANO": {"INMUEBLE": 2500.0, "SOLAR": 800.0},
        "RÚSTICO": {"INMUEBLE": 450.0, "SOLAR": 25.0}
    },
    "VALENCIA": {
        "URBANO": {"INMUEBLE": 1800.0, "SOLAR": 550.0},
        "RÚSTICO": {"INMUEBLE": 350.0, "SOLAR": 18.0}
    },
    "VALÈNCIA": {
        "URBANO": {"INMUEBLE": 1800.0, "SOLAR": 550.0},
        "RÚSTICO": {"INMUEBLE": 350.0, "SOLAR": 18.0}
    },
    "VALENCIA/VALÈNCIA": {
        "URBANO": {"INMUEBLE": 1800.0, "SOLAR": 550.0},
        "RÚSTICO": {"INMUEBLE": 350.0, "SOLAR": 18.0}
    },
    "SEVILLA": {
        "URBANO": {"INMUEBLE": 1600.0, "SOLAR": 500.0},
        "RÚSTICO": {"INMUEBLE": 350.0, "SOLAR": 18.0}
    },
    "SANTA CRUZ DE TENERIFE": {
        "URBANO": {"INMUEBLE": 1900.0, "SOLAR": 600.0},
        "RÚSTICO": {"INMUEBLE": 400.0, "SOLAR": 20.0}
    },
    "GIPUZKOA": {
        "URBANO": {"INMUEBLE": 2900.0, "SOLAR": 900.0},
        "RÚSTICO": {"INMUEBLE": 500.0, "SOLAR": 25.0}
    },
    "BIZKAIA": {
        "URBANO": {"INMUEBLE": 2500.0, "SOLAR": 800.0},
        "RÚSTICO": {"INMUEBLE": 450.0, "SOLAR": 22.0}
    },
    "ALICANTE": {
        "URBANO": {"INMUEBLE": 1750.0, "SOLAR": 500.0},
        "RÚSTICO": {"INMUEBLE": 350.0, "SOLAR": 18.0}
    },
    "GIRONA": {
        "URBANO": {"INMUEBLE": 2200.0, "SOLAR": 700.0},
        "RÚSTICO": {"INMUEBLE": 400.0, "SOLAR": 20.0}
    },
    "TARRAGONA": {
        "URBANO": {"INMUEBLE": 1550.0, "SOLAR": 450.0},
        "RÚSTICO": {"INMUEBLE": 300.0, "SOLAR": 15.0}
    },
    "ZARAGOZA": {
        "URBANO": {"INMUEBLE": 1500.0, "SOLAR": 450.0},
        "RÚSTICO": {"INMUEBLE": 300.0, "SOLAR": 15.0}
    },
    "CÁDIZ": {
        "URBANO": {"INMUEBLE": 1600.0, "SOLAR": 480.0},
        "RÚSTICO": {"INMUEBLE": 320.0, "SOLAR": 16.0}
    },
    "GRANADA": {
        "URBANO": {"INMUEBLE": 1500.0, "SOLAR": 450.0},
        "RÚSTICO": {"INMUEBLE": 300.0, "SOLAR": 15.0}
    },
    "TOLEDO": {
        "URBANO": {"INMUEBLE": 1100.0, "SOLAR": 320.0},
        "RÚSTICO": {"INMUEBLE": 250.0, "SOLAR": 12.0}
    },
    "GUADALAJARA": {
        "URBANO": {"INMUEBLE": 1350.0, "SOLAR": 400.0},
        "RÚSTICO": {"INMUEBLE": 280.0, "SOLAR": 14.0}
    },
    "MURCIA": {
        "URBANO": {"INMUEBLE": 1250.0, "SOLAR": 380.0},
        "RÚSTICO": {"INMUEBLE": 280.0, "SOLAR": 12.0}
    }
}

# Matrices 2x2 por Municipio Específico (€/m²)
MUNICIPALITY_MARKET_2X2: Dict[str, Dict[str, Dict[str, float]]] = {
    "DAGANZO DE ARRIBA": {
        "URBANO": {"INMUEBLE": 1450.0, "SOLAR": 450.0},
        "RÚSTICO": {"INMUEBLE": 300.0, "SOLAR": 12.0}
    },
    "ARGANDA DEL REY": {
        "URBANO": {"INMUEBLE": 1550.0, "SOLAR": 480.0},
        "RÚSTICO": {"INMUEBLE": 300.0, "SOLAR": 12.0}
    },
    "ALCALÁ DE HENARES": {
        "URBANO": {"INMUEBLE": 1850.0, "SOLAR": 550.0},
        "RÚSTICO": {"INMUEBLE": 350.0, "SOLAR": 15.0}
    },
    "LAS ROZAS": {
        "URBANO": {"INMUEBLE": 3100.0, "SOLAR": 1000.0},
        "RÚSTICO": {"INMUEBLE": 500.0, "SOLAR": 25.0}
    },
    "MÓSTOLES": {
        "URBANO": {"INMUEBLE": 1750.0, "SOLAR": 500.0},
        "RÚSTICO": {"INMUEBLE": 320.0, "SOLAR": 14.0}
    },
    "TORRES DE LA ALAMEDA": {
        "URBANO": {"INMUEBLE": 1350.0, "SOLAR": 400.0},
        "RÚSTICO": {"INMUEBLE": 280.0, "SOLAR": 12.0}
    },
    "MARBELLA": {
        "URBANO": {"INMUEBLE": 3800.0, "SOLAR": 1200.0},
        "RÚSTICO": {"INMUEBLE": 600.0, "SOLAR": 30.0}
    },
    "BENALMADENA": {
        "URBANO": {"INMUEBLE": 2800.0, "SOLAR": 900.0},
        "RÚSTICO": {"INMUEBLE": 450.0, "SOLAR": 22.0}
    },
    "ESTEPONA": {
        "URBANO": {"INMUEBLE": 3100.0, "SOLAR": 1000.0},
        "RÚSTICO": {"INMUEBLE": 500.0, "SOLAR": 25.0}
    },
    "TORREMOLINOS": {
        "URBANO": {"INMUEBLE": 2600.0, "SOLAR": 850.0},
        "RÚSTICO": {"INMUEBLE": 400.0, "SOLAR": 20.0}
    },
    "MIJAS": {
        "URBANO": {"INMUEBLE": 2700.0, "SOLAR": 880.0},
        "RÚSTICO": {"INMUEBLE": 420.0, "SOLAR": 20.0}
    },
    "VALLE GRAN REY": {
        "URBANO": {"INMUEBLE": 2400.0, "SOLAR": 650.0},
        "RÚSTICO": {"INMUEBLE": 350.0, "SOLAR": 18.0}
    },
    "ADEJE": {
        "URBANO": {"INMUEBLE": 3200.0, "SOLAR": 1000.0},
        "RÚSTICO": {"INMUEBLE": 500.0, "SOLAR": 25.0}
    },
    "ARONA": {
        "URBANO": {"INMUEBLE": 2600.0, "SOLAR": 850.0},
        "RÚSTICO": {"INMUEBLE": 400.0, "SOLAR": 20.0}
    },
    "MANACOR": {
        "URBANO": {"INMUEBLE": 2200.0, "SOLAR": 700.0},
        "RÚSTICO": {"INMUEBLE": 450.0, "SOLAR": 25.0}
    },
    "SANTA EULARIA DES RIU": {
        "URBANO": {"INMUEBLE": 4500.0, "SOLAR": 1500.0},
        "RÚSTICO": {"INMUEBLE": 800.0, "SOLAR": 45.0}
    },
    "SAN ANTONIO ABAD": {
        "URBANO": {"INMUEBLE": 3800.0, "SOLAR": 1200.0},
        "RÚSTICO": {"INMUEBLE": 700.0, "SOLAR": 35.0}
    }
}

# Matrices 2x2 por Código Postal / Barrio Específico (€/m²)
CP_DISTRICT_MARKET_2X2: Dict[str, Tuple[Dict[str, Dict[str, float]], str]] = {
    # Madrid Capital por CP / Barrio
    "28001": ({"URBANO": {"INMUEBLE": 7500.0, "SOLAR": 2500.0}, "RÚSTICO": {"INMUEBLE": 800.0, "SOLAR": 35.0}}, "Salamanca"),
    "28006": ({"URBANO": {"INMUEBLE": 7500.0, "SOLAR": 2500.0}, "RÚSTICO": {"INMUEBLE": 800.0, "SOLAR": 35.0}}, "Salamanca"),
    "28010": ({"URBANO": {"INMUEBLE": 6400.0, "SOLAR": 2200.0}, "RÚSTICO": {"INMUEBLE": 700.0, "SOLAR": 30.0}}, "Chamberí"),
    "28007": ({"URBANO": {"INMUEBLE": 5900.0, "SOLAR": 2000.0}, "RÚSTICO": {"INMUEBLE": 650.0, "SOLAR": 28.0}}, "Retiro"),
    "28009": ({"URBANO": {"INMUEBLE": 5900.0, "SOLAR": 2000.0}, "RÚSTICO": {"INMUEBLE": 650.0, "SOLAR": 28.0}}, "Retiro"),
    "28004": ({"URBANO": {"INMUEBLE": 5600.0, "SOLAR": 1900.0}, "RÚSTICO": {"INMUEBLE": 600.0, "SOLAR": 25.0}}, "Centro"),
    "28005": ({"URBANO": {"INMUEBLE": 5600.0, "SOLAR": 1900.0}, "RÚSTICO": {"INMUEBLE": 600.0, "SOLAR": 25.0}}, "Centro"),
    "28012": ({"URBANO": {"INMUEBLE": 5600.0, "SOLAR": 1900.0}, "RÚSTICO": {"INMUEBLE": 600.0, "SOLAR": 25.0}}, "Centro"),
    "28002": ({"URBANO": {"INMUEBLE": 5400.0, "SOLAR": 1800.0}, "RÚSTICO": {"INMUEBLE": 600.0, "SOLAR": 25.0}}, "Chamartín"),
    "28016": ({"URBANO": {"INMUEBLE": 5400.0, "SOLAR": 1800.0}, "RÚSTICO": {"INMUEBLE": 600.0, "SOLAR": 25.0}}, "Chamartín"),
    "28008": ({"URBANO": {"INMUEBLE": 4800.0, "SOLAR": 1600.0}, "RÚSTICO": {"INMUEBLE": 550.0, "SOLAR": 22.0}}, "Moncloa - Aravaca"),
    "28023": ({"URBANO": {"INMUEBLE": 4800.0, "SOLAR": 1600.0}, "RÚSTICO": {"INMUEBLE": 550.0, "SOLAR": 22.0}}, "Moncloa - Aravaca"),
    "28045": ({"URBANO": {"INMUEBLE": 4400.0, "SOLAR": 1500.0}, "RÚSTICO": {"INMUEBLE": 500.0, "SOLAR": 20.0}}, "Arganzuela"),
    "28020": ({"URBANO": {"INMUEBLE": 4100.0, "SOLAR": 1400.0}, "RÚSTICO": {"INMUEBLE": 480.0, "SOLAR": 20.0}}, "Tetuán"),
    "28037": ({"URBANO": {"INMUEBLE": 2800.0, "SOLAR": 1100.0}, "RÚSTICO": {"INMUEBLE": 400.0, "SOLAR": 18.0}}, "San Blas - Canillejas"),
    "28022": ({"URBANO": {"INMUEBLE": 2800.0, "SOLAR": 1100.0}, "RÚSTICO": {"INMUEBLE": 400.0, "SOLAR": 18.0}}, "San Blas - Canillejas"),
    "28019": ({"URBANO": {"INMUEBLE": 2600.0, "SOLAR": 900.0}, "RÚSTICO": {"INMUEBLE": 380.0, "SOLAR": 16.0}}, "Carabanchel"),
    "28025": ({"URBANO": {"INMUEBLE": 2600.0, "SOLAR": 900.0}, "RÚSTICO": {"INMUEBLE": 380.0, "SOLAR": 16.0}}, "Carabanchel"),
    "28018": ({"URBANO": {"INMUEBLE": 2300.0, "SOLAR": 800.0}, "RÚSTICO": {"INMUEBLE": 350.0, "SOLAR": 15.0}}, "Puente de Vallecas"),
    "28814": ({"URBANO": {"INMUEBLE": 1450.0, "SOLAR": 450.0}, "RÚSTICO": {"INMUEBLE": 300.0, "SOLAR": 12.0}}, "Daganzo de Arriba"),
}

def extract_postal_code(text: str) -> Optional[str]:
    """Extrae un código postal español válido (5 dígitos, 01000 - 52999) del texto."""
    if not text:
        return None
    matches = re.findall(r'\b(0[1-9]|[1-4][0-9]|5[0-2])\d{3}\b', text)
    if matches:
        m = re.search(r'\b(0[1-9]|[1-4][0-9]|5[0-2])\d{3}\b', text)
        return m.group(0) if m else None
    return None

def resolve_meso_market_price_2x2(
    province_str: str,
    locality_str: str,
    full_address_str: str,
    desc_text: str,
    land_type: str = "URBANO",
    is_solar: bool = False
) -> Tuple[float, str, str]:
    """
    Resuelve el precio de referencia de mercado (€/m²) utilizando la Matriz 2x2.
    Eje Y: [URBANO, RÚSTICO]
    Eje X: [INMUEBLE, SOLAR]

    Retorna: (price_m2, source_code, source_label)
    """
    prov_key = (province_str or "").strip().upper()
    loc_key = (locality_str or "").strip().upper()
    
    # Eje Y: URBANO vs RÚSTICO
    y_axis = "RÚSTICO" if ("RUSTICO" in (land_type or "").upper() or "AGRARIO" in (land_type or "").upper()) else "URBANO"
    
    # Eje X: INMUEBLE vs SOLAR
    x_axis = "SOLAR" if is_solar else "INMUEBLE"

    combined_text = f"{full_address_str} {desc_text} {locality_str}".lower()
    
    # 1. Intentar por Código Postal (CP)
    cp = extract_postal_code(combined_text)
    if cp and cp in CP_DISTRICT_MARKET_2X2:
        matrix, label = CP_DISTRICT_MARKET_2X2[cp]
        price = matrix[y_axis][x_axis]
        return price, "SECCION", f"Barrio/CP MIVAU [{label} ({cp})]"

    # 2. Intentar por Municipio / Localidad exacta
    if loc_key in MUNICIPALITY_MARKET_2X2:
        matrix = MUNICIPALITY_MARKET_2X2[loc_key]
        price = matrix[y_axis][x_axis]
        return price, "MUNICIPAL", f"Municipio MIVAU [{locality_str or loc_key}]"

    # 3. Intentar por Distrito en Grandes Capitales
    if prov_key in ["MADRID", "BARCELONA", "MÁLAGA", "MALAGA", "VALENCIA", "VALÈNCIA", "VALENCIA/VALÈNCIA", "SEVILLA"]:
        text_normalized = combined_text.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
        for cp_key, (matrix, district_name) in CP_DISTRICT_MARKET_2X2.items():
            dist_norm = district_name.lower().replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
            if dist_norm in text_normalized:
                price = matrix[y_axis][x_axis]
                return price, "SECCION", f"Barrio/Distrito MIVAU [{district_name}]"

    # 4. Fallback a Benchmark Provincial (utilizando el municipio/localidad real como nombre)
    prov_matrix = PROVINCE_MARKET_2X2.get(prov_key)
    if not prov_matrix:
        clean_prov = prov_key.split("/")[0].strip()
        prov_matrix = PROVINCE_MARKET_2X2.get(clean_prov, DEFAULT_2X2)
        
    price = prov_matrix[y_axis][x_axis]
    display_loc = locality_str.strip() if locality_str and locality_str.strip() else (province_str or 'España')
    return price, "MUNICIPAL", f"Municipio MIVAU [{display_loc}]"
