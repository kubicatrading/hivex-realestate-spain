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

# Matrices 2x2 por Código Postal / Barrio Específico (€/m²) - TIER 1 Y TIER 2 NACIONAL (MIVAU / INE)
CP_DISTRICT_MARKET_2X2: Dict[str, Tuple[Dict[str, Dict[str, float]], str]] = {
    # === MADRID CAPITAL (Todos los CPs y Distritos) ===
    "28001": ({"URBANO": {"INMUEBLE": 7500.0, "SOLAR": 2500.0}, "RÚSTICO": {"INMUEBLE": 800.0, "SOLAR": 35.0}}, "Salamanca - Recoletos"),
    "28002": ({"URBANO": {"INMUEBLE": 5400.0, "SOLAR": 1800.0}, "RÚSTICO": {"INMUEBLE": 600.0, "SOLAR": 25.0}}, "Chamartín - Prosperidad"),
    "28003": ({"URBANO": {"INMUEBLE": 6100.0, "SOLAR": 2100.0}, "RÚSTICO": {"INMUEBLE": 700.0, "SOLAR": 30.0}}, "Chamberí - Vallehermoso"),
    "28004": ({"URBANO": {"INMUEBLE": 5600.0, "SOLAR": 1900.0}, "RÚSTICO": {"INMUEBLE": 600.0, "SOLAR": 25.0}}, "Centro - Justicia / Chueca"),
    "28005": ({"URBANO": {"INMUEBLE": 5400.0, "SOLAR": 1850.0}, "RÚSTICO": {"INMUEBLE": 600.0, "SOLAR": 25.0}}, "Centro - La Latina"),
    "28006": ({"URBANO": {"INMUEBLE": 7500.0, "SOLAR": 2500.0}, "RÚSTICO": {"INMUEBLE": 800.0, "SOLAR": 35.0}}, "Salamanca - Castellana"),
    "28007": ({"URBANO": {"INMUEBLE": 5900.0, "SOLAR": 2000.0}, "RÚSTICO": {"INMUEBLE": 650.0, "SOLAR": 28.0}}, "Retiro - Pacífico"),
    "28008": ({"URBANO": {"INMUEBLE": 5100.0, "SOLAR": 1700.0}, "RÚSTICO": {"INMUEBLE": 550.0, "SOLAR": 22.0}}, "Moncloa - Argüelles"),
    "28009": ({"URBANO": {"INMUEBLE": 6200.0, "SOLAR": 2100.0}, "RÚSTICO": {"INMUEBLE": 650.0, "SOLAR": 28.0}}, "Retiro - Ibiza"),
    "28010": ({"URBANO": {"INMUEBLE": 6600.0, "SOLAR": 2250.0}, "RÚSTICO": {"INMUEBLE": 700.0, "SOLAR": 30.0}}, "Chamberí - Almagro"),
    "28011": ({"URBANO": {"INMUEBLE": 2650.0, "SOLAR": 950.0}, "RÚSTICO": {"INMUEBLE": 380.0, "SOLAR": 16.0}}, "Latina - Puerta del Ángel"),
    "28012": ({"URBANO": {"INMUEBLE": 5300.0, "SOLAR": 1800.0}, "RÚSTICO": {"INMUEBLE": 600.0, "SOLAR": 25.0}}, "Centro - Lavapiés"),
    "28013": ({"URBANO": {"INMUEBLE": 5800.0, "SOLAR": 1950.0}, "RÚSTICO": {"INMUEBLE": 620.0, "SOLAR": 26.0}}, "Centro - Sol / Ópera"),
    "28014": ({"URBANO": {"INMUEBLE": 6200.0, "SOLAR": 2100.0}, "RÚSTICO": {"INMUEBLE": 650.0, "SOLAR": 28.0}}, "Centro - Cortes"),
    "28015": ({"URBANO": {"INMUEBLE": 5900.0, "SOLAR": 2000.0}, "RÚSTICO": {"INMUEBLE": 620.0, "SOLAR": 26.0}}, "Chamberí - Gaztambide"),
    "28016": ({"URBANO": {"INMUEBLE": 5500.0, "SOLAR": 1850.0}, "RÚSTICO": {"INMUEBLE": 600.0, "SOLAR": 25.0}}, "Chamartín - Nueva España"),
    "28017": ({"URBANO": {"INMUEBLE": 3100.0, "SOLAR": 1100.0}, "RÚSTICO": {"INMUEBLE": 420.0, "SOLAR": 18.0}}, "Ciudad Lineal - Ventas"),
    "28018": ({"URBANO": {"INMUEBLE": 2300.0, "SOLAR": 800.0}, "RÚSTICO": {"INMUEBLE": 350.0, "SOLAR": 15.0}}, "Puente de Vallecas - Palomeras"),
    "28019": ({"URBANO": {"INMUEBLE": 2600.0, "SOLAR": 900.0}, "RÚSTICO": {"INMUEBLE": 380.0, "SOLAR": 16.0}}, "Carabanchel - Comillas / Opañel"),
    "28020": ({"URBANO": {"INMUEBLE": 4300.0, "SOLAR": 1450.0}, "RÚSTICO": {"INMUEBLE": 500.0, "SOLAR": 20.0}}, "Tetuán - Cuatro Caminos"),
    "28021": ({"URBANO": {"INMUEBLE": 1950.0, "SOLAR": 650.0}, "RÚSTICO": {"INMUEBLE": 320.0, "SOLAR": 14.0}}, "Villaverde - San Cristóbal"),
    "28022": ({"URBANO": {"INMUEBLE": 2900.0, "SOLAR": 1100.0}, "RÚSTICO": {"INMUEBLE": 400.0, "SOLAR": 18.0}}, "San Blas - Canillejas"),
    "28023": ({"URBANO": {"INMUEBLE": 4900.0, "SOLAR": 1650.0}, "RÚSTICO": {"INMUEBLE": 550.0, "SOLAR": 22.0}}, "Moncloa - Aravaca / Valdemarín"),
    "28024": ({"URBANO": {"INMUEBLE": 2500.0, "SOLAR": 880.0}, "RÚSTICO": {"INMUEBLE": 360.0, "SOLAR": 15.0}}, "Latina - Campamento / Aluche"),
    "28025": ({"URBANO": {"INMUEBLE": 2600.0, "SOLAR": 900.0}, "RÚSTICO": {"INMUEBLE": 380.0, "SOLAR": 16.0}}, "Carabanchel - Vista Alegre"),
    "28026": ({"URBANO": {"INMUEBLE": 2250.0, "SOLAR": 780.0}, "RÚSTICO": {"INMUEBLE": 340.0, "SOLAR": 15.0}}, "Usera - Moscardó / Pradolongo"),
    "28027": ({"URBANO": {"INMUEBLE": 3500.0, "SOLAR": 1200.0}, "RÚSTICO": {"INMUEBLE": 450.0, "SOLAR": 19.0}}, "Ciudad Lineal - Concepción"),
    "28028": ({"URBANO": {"INMUEBLE": 5600.0, "SOLAR": 1900.0}, "RÚSTICO": {"INMUEBLE": 600.0, "SOLAR": 25.0}}, "Salamanca - Guindalera"),
    "28029": ({"URBANO": {"INMUEBLE": 3900.0, "SOLAR": 1350.0}, "RÚSTICO": {"INMUEBLE": 480.0, "SOLAR": 20.0}}, "Tetuán - Valdeacederas"),
    "28030": ({"URBANO": {"INMUEBLE": 2750.0, "SOLAR": 950.0}, "RÚSTICO": {"INMUEBLE": 390.0, "SOLAR": 16.0}}, "Moratalaz - Pavones"),
    "28031": ({"URBANO": {"INMUEBLE": 2400.0, "SOLAR": 850.0}, "RÚSTICO": {"INMUEBLE": 360.0, "SOLAR": 15.0}}, "Villa de Vallecas - Santa Eugenia"),
    "28032": ({"URBANO": {"INMUEBLE": 2600.0, "SOLAR": 900.0}, "RÚSTICO": {"INMUEBLE": 380.0, "SOLAR": 16.0}}, "Vicálvaro - Valdebernardo"),
    "28033": ({"URBANO": {"INMUEBLE": 3800.0, "SOLAR": 1300.0}, "RÚSTICO": {"INMUEBLE": 470.0, "SOLAR": 20.0}}, "Hortaleza - Pinar del Rey"),
    "28034": ({"URBANO": {"INMUEBLE": 4400.0, "SOLAR": 1500.0}, "RÚSTICO": {"INMUEBLE": 520.0, "SOLAR": 21.0}}, "Fuencarral - Mirasierra"),
    "28035": ({"URBANO": {"INMUEBLE": 3800.0, "SOLAR": 1300.0}, "RÚSTICO": {"INMUEBLE": 470.0, "SOLAR": 20.0}}, "Fuencarral - Peñagrande"),
    "28036": ({"URBANO": {"INMUEBLE": 5300.0, "SOLAR": 1800.0}, "RÚSTICO": {"INMUEBLE": 590.0, "SOLAR": 24.0}}, "Chamartín - Castilla"),
    "28037": ({"URBANO": {"INMUEBLE": 2550.0, "SOLAR": 900.0}, "RÚSTICO": {"INMUEBLE": 380.0, "SOLAR": 16.0}}, "San Blas - Simancas"),
    "28038": ({"URBANO": {"INMUEBLE": 2350.0, "SOLAR": 820.0}, "RÚSTICO": {"INMUEBLE": 350.0, "SOLAR": 15.0}}, "Puente de Vallecas - Numancia / Portazgo"),
    "28039": ({"URBANO": {"INMUEBLE": 3800.0, "SOLAR": 1300.0}, "RÚSTICO": {"INMUEBLE": 470.0, "SOLAR": 20.0}}, "Tetuán - Bellas Vistas"),
    "28040": ({"URBANO": {"INMUEBLE": 4500.0, "SOLAR": 1550.0}, "RÚSTICO": {"INMUEBLE": 530.0, "SOLAR": 22.0}}, "Moncloa - Ciudad Universitaria"),
    "28041": ({"URBANO": {"INMUEBLE": 2150.0, "SOLAR": 750.0}, "RÚSTICO": {"INMUEBLE": 330.0, "SOLAR": 14.0}}, "Usera - Orcasitas / San Fermín"),
    "28042": ({"URBANO": {"INMUEBLE": 3400.0, "SOLAR": 1200.0}, "RÚSTICO": {"INMUEBLE": 440.0, "SOLAR": 18.0}}, "Barajas - Alameda de Osuna"),
    "28043": ({"URBANO": {"INMUEBLE": 4600.0, "SOLAR": 1600.0}, "RÚSTICO": {"INMUEBLE": 540.0, "SOLAR": 22.0}}, "Hortaleza - Canillas / Piovera"),
    "28044": ({"URBANO": {"INMUEBLE": 2400.0, "SOLAR": 820.0}, "RÚSTICO": {"INMUEBLE": 350.0, "SOLAR": 15.0}}, "Latina - Las Águilas"),
    "28045": ({"URBANO": {"INMUEBLE": 4400.0, "SOLAR": 1500.0}, "RÚSTICO": {"INMUEBLE": 500.0, "SOLAR": 20.0}}, "Arganzuela - Delicias / Legazpi"),
    "28046": ({"URBANO": {"INMUEBLE": 5600.0, "SOLAR": 1900.0}, "RÚSTICO": {"INMUEBLE": 600.0, "SOLAR": 25.0}}, "Chamartín - Cuatro Torres"),
    "28047": ({"URBANO": {"INMUEBLE": 2500.0, "SOLAR": 850.0}, "RÚSTICO": {"INMUEBLE": 360.0, "SOLAR": 15.0}}, "Latina - Lucero"),
    "28049": ({"URBANO": {"INMUEBLE": 3200.0, "SOLAR": 1100.0}, "RÚSTICO": {"INMUEBLE": 430.0, "SOLAR": 18.0}}, "Fuencarral - El Pardo"),
    "28050": ({"URBANO": {"INMUEBLE": 4600.0, "SOLAR": 1600.0}, "RÚSTICO": {"INMUEBLE": 540.0, "SOLAR": 22.0}}, "Hortaleza - Sanchinarro"),
    "28051": ({"URBANO": {"INMUEBLE": 2750.0, "SOLAR": 950.0}, "RÚSTICO": {"INMUEBLE": 390.0, "SOLAR": 16.0}}, "Villa de Vallecas - Ensanche"),
    "28052": ({"URBANO": {"INMUEBLE": 3100.0, "SOLAR": 1100.0}, "RÚSTICO": {"INMUEBLE": 420.0, "SOLAR": 18.0}}, "Vicálvaro - El Cañaveral"),
    "28053": ({"URBANO": {"INMUEBLE": 2200.0, "SOLAR": 750.0}, "RÚSTICO": {"INMUEBLE": 340.0, "SOLAR": 14.0}}, "Puente de Vallecas - Entrevías / San Diego"),
    "28054": ({"URBANO": {"INMUEBLE": 2700.0, "SOLAR": 950.0}, "RÚSTICO": {"INMUEBLE": 380.0, "SOLAR": 16.0}}, "Carabanchel - PAU / La Peseta"),
    "28055": ({"URBANO": {"INMUEBLE": 4700.0, "SOLAR": 1650.0}, "RÚSTICO": {"INMUEBLE": 550.0, "SOLAR": 22.0}}, "Fuencarral - Las Tablas"),
    "28814": ({"URBANO": {"INMUEBLE": 1450.0, "SOLAR": 450.0}, "RÚSTICO": {"INMUEBLE": 300.0, "SOLAR": 12.0}}, "Daganzo de Arriba"),

    # === BARCELONA CAPITAL (Todos los CPs y Distritos) ===
    "08001": ({"URBANO": {"INMUEBLE": 3800.0, "SOLAR": 1300.0}, "RÚSTICO": {"INMUEBLE": 480.0, "SOLAR": 20.0}}, "Ciutat Vella - El Raval"),
    "08002": ({"URBANO": {"INMUEBLE": 4300.0, "SOLAR": 1500.0}, "RÚSTICO": {"INMUEBLE": 520.0, "SOLAR": 22.0}}, "Ciutat Vella - Barri Gòtic"),
    "08003": ({"URBANO": {"INMUEBLE": 4600.0, "SOLAR": 1600.0}, "RÚSTICO": {"INMUEBLE": 550.0, "SOLAR": 23.0}}, "Ciutat Vella - Born / Barceloneta"),
    "08004": ({"URBANO": {"INMUEBLE": 3600.0, "SOLAR": 1200.0}, "RÚSTICO": {"INMUEBLE": 460.0, "SOLAR": 19.0}}, "Sants-Montjuïc - Poble-sec"),
    "08005": ({"URBANO": {"INMUEBLE": 4900.0, "SOLAR": 1700.0}, "RÚSTICO": {"INMUEBLE": 570.0, "SOLAR": 24.0}}, "Sant Martí - Poblenou / Vila Olímpica"),
    "08006": ({"URBANO": {"INMUEBLE": 5900.0, "SOLAR": 2100.0}, "RÚSTICO": {"INMUEBLE": 650.0, "SOLAR": 28.0}}, "Sarrià-Sant Gervasi - Galvany"),
    "08007": ({"URBANO": {"INMUEBLE": 5300.0, "SOLAR": 1850.0}, "RÚSTICO": {"INMUEBLE": 600.0, "SOLAR": 25.0}}, "Eixample - Dreta"),
    "08008": ({"URBANO": {"INMUEBLE": 5100.0, "SOLAR": 1750.0}, "RÚSTICO": {"INMUEBLE": 580.0, "SOLAR": 24.0}}, "Eixample - Antiga Esquerra"),
    "08009": ({"URBANO": {"INMUEBLE": 4700.0, "SOLAR": 1600.0}, "RÚSTICO": {"INMUEBLE": 550.0, "SOLAR": 23.0}}, "Eixample - Fort Pienc"),
    "08010": ({"URBANO": {"INMUEBLE": 5200.0, "SOLAR": 1800.0}, "RÚSTICO": {"INMUEBLE": 590.0, "SOLAR": 25.0}}, "Eixample - Urquinaona"),
    "08011": ({"URBANO": {"INMUEBLE": 4800.0, "SOLAR": 1650.0}, "RÚSTICO": {"INMUEBLE": 560.0, "SOLAR": 23.0}}, "Eixample - Nova Esquerra"),
    "08012": ({"URBANO": {"INMUEBLE": 4700.0, "SOLAR": 1600.0}, "RÚSTICO": {"INMUEBLE": 550.0, "SOLAR": 23.0}}, "Gràcia - Vila de Gràcia"),
    "08013": ({"URBANO": {"INMUEBLE": 4700.0, "SOLAR": 1600.0}, "RÚSTICO": {"INMUEBLE": 550.0, "SOLAR": 23.0}}, "Eixample - Sagrada Família"),
    "08014": ({"URBANO": {"INMUEBLE": 3600.0, "SOLAR": 1200.0}, "RÚSTICO": {"INMUEBLE": 460.0, "SOLAR": 19.0}}, "Sants-Montjuïc - Sants / Hostafrancs"),
    "08015": ({"URBANO": {"INMUEBLE": 4700.0, "SOLAR": 1600.0}, "RÚSTICO": {"INMUEBLE": 550.0, "SOLAR": 23.0}}, "Eixample - Sant Antoni"),
    "08016": ({"URBANO": {"INMUEBLE": 2400.0, "SOLAR": 800.0}, "RÚSTICO": {"INMUEBLE": 360.0, "SOLAR": 15.0}}, "Nou Barris - Porta / Vilapicina"),
    "08017": ({"URBANO": {"INMUEBLE": 6300.0, "SOLAR": 2200.0}, "RÚSTICO": {"INMUEBLE": 680.0, "SOLAR": 29.0}}, "Sarrià-Sant Gervasi - Sarrià / Tres Torres"),
    "08018": ({"URBANO": {"INMUEBLE": 4400.0, "SOLAR": 1500.0}, "RÚSTICO": {"INMUEBLE": 530.0, "SOLAR": 22.0}}, "Sant Martí - Parc i Llacuna"),
    "08019": ({"URBANO": {"INMUEBLE": 4300.0, "SOLAR": 1500.0}, "RÚSTICO": {"INMUEBLE": 520.0, "SOLAR": 22.0}}, "Sant Martí - Diagonal Mar"),
    "08020": ({"URBANO": {"INMUEBLE": 3100.0, "SOLAR": 1050.0}, "RÚSTICO": {"INMUEBLE": 420.0, "SOLAR": 18.0}}, "Sant Martí - La Verneda"),
    "08021": ({"URBANO": {"INMUEBLE": 6000.0, "SOLAR": 2100.0}, "RÚSTICO": {"INMUEBLE": 660.0, "SOLAR": 28.0}}, "Sarrià-Sant Gervasi - Bonanova"),
    "08022": ({"URBANO": {"INMUEBLE": 5400.0, "SOLAR": 1850.0}, "RÚSTICO": {"INMUEBLE": 600.0, "SOLAR": 25.0}}, "Sarrià-Sant Gervasi - El Putxet"),
    "08023": ({"URBANO": {"INMUEBLE": 3900.0, "SOLAR": 1350.0}, "RÚSTICO": {"INMUEBLE": 490.0, "SOLAR": 20.0}}, "Gràcia - Vallcarca"),
    "08024": ({"URBANO": {"INMUEBLE": 4300.0, "SOLAR": 1500.0}, "RÚSTICO": {"INMUEBLE": 520.0, "SOLAR": 22.0}}, "Gràcia - Camp d'en Grassot"),
    "08025": ({"URBANO": {"INMUEBLE": 3800.0, "SOLAR": 1300.0}, "RÚSTICO": {"INMUEBLE": 480.0, "SOLAR": 20.0}}, "Eixample - Camp de l'Arpa"),
    "08026": ({"URBANO": {"INMUEBLE": 3800.0, "SOLAR": 1300.0}, "RÚSTICO": {"INMUEBLE": 480.0, "SOLAR": 20.0}}, "Sant Martí - El Clot"),
    "08027": ({"URBANO": {"INMUEBLE": 3200.0, "SOLAR": 1100.0}, "RÚSTICO": {"INMUEBLE": 430.0, "SOLAR": 18.0}}, "Sant Andreu - La Sagrera"),
    "08028": ({"URBANO": {"INMUEBLE": 4500.0, "SOLAR": 1550.0}, "RÚSTICO": {"INMUEBLE": 530.0, "SOLAR": 22.0}}, "Les Corts - Maternitat"),
    "08029": ({"URBANO": {"INMUEBLE": 4800.0, "SOLAR": 1650.0}, "RÚSTICO": {"INMUEBLE": 560.0, "SOLAR": 23.0}}, "Les Corts - Les Corts Centro"),
    "08030": ({"URBANO": {"INMUEBLE": 2950.0, "SOLAR": 1000.0}, "RÚSTICO": {"INMUEBLE": 410.0, "SOLAR": 17.0}}, "Sant Andreu - Casco"),
    "08031": ({"URBANO": {"INMUEBLE": 2800.0, "SOLAR": 950.0}, "RÚSTICO": {"INMUEBLE": 390.0, "SOLAR": 16.0}}, "Horta-Guinardó - Horta"),
    "08032": ({"URBANO": {"INMUEBLE": 2300.0, "SOLAR": 780.0}, "RÚSTICO": {"INMUEBLE": 350.0, "SOLAR": 15.0}}, "Horta-Guinardó - El Carmel"),
    "08033": ({"URBANO": {"INMUEBLE": 1900.0, "SOLAR": 650.0}, "RÚSTICO": {"INMUEBLE": 310.0, "SOLAR": 13.0}}, "Nou Barris - Ciutat Meridiana"),
    "08034": ({"URBANO": {"INMUEBLE": 6900.0, "SOLAR": 2400.0}, "RÚSTICO": {"INMUEBLE": 720.0, "SOLAR": 30.0}}, "Les Corts - Pedralbes"),
    "08035": ({"URBANO": {"INMUEBLE": 2900.0, "SOLAR": 1000.0}, "RÚSTICO": {"INMUEBLE": 400.0, "SOLAR": 17.0}}, "Horta-Guinardó - Montbau"),
    "08036": ({"URBANO": {"INMUEBLE": 5000.0, "SOLAR": 1700.0}, "RÚSTICO": {"INMUEBLE": 570.0, "SOLAR": 24.0}}, "Eixample - Esquerra"),
    "08037": ({"URBANO": {"INMUEBLE": 5300.0, "SOLAR": 1800.0}, "RÚSTICO": {"INMUEBLE": 600.0, "SOLAR": 25.0}}, "Eixample - Dreta Centro"),
    "08038": ({"URBANO": {"INMUEBLE": 2900.0, "SOLAR": 1000.0}, "RÚSTICO": {"INMUEBLE": 400.0, "SOLAR": 17.0}}, "Sants-Montjuïc - Marina del Port"),
    "08041": ({"URBANO": {"INMUEBLE": 3400.0, "SOLAR": 1150.0}, "RÚSTICO": {"INMUEBLE": 450.0, "SOLAR": 19.0}}, "Horta-Guinardó - El Guinardó"),
    "08042": ({"URBANO": {"INMUEBLE": 2200.0, "SOLAR": 750.0}, "RÚSTICO": {"INMUEBLE": 340.0, "SOLAR": 14.0}}, "Nou Barris - Roquetes"),

    # === VALENCIA CAPITAL (Todos los CPs y Distritos) ===
    "46001": ({"URBANO": {"INMUEBLE": 3300.0, "SOLAR": 1100.0}, "RÚSTICO": {"INMUEBLE": 420.0, "SOLAR": 18.0}}, "Ciutat Vella - El Mercat / El Carme"),
    "46002": ({"URBANO": {"INMUEBLE": 3600.0, "SOLAR": 1200.0}, "RÚSTICO": {"INMUEBLE": 450.0, "SOLAR": 19.0}}, "Ciutat Vella - Sant Francesc"),
    "46003": ({"URBANO": {"INMUEBLE": 3500.0, "SOLAR": 1150.0}, "RÚSTICO": {"INMUEBLE": 440.0, "SOLAR": 19.0}}, "Ciutat Vella - La Seu"),
    "46004": ({"URBANO": {"INMUEBLE": 3800.0, "SOLAR": 1300.0}, "RÚSTICO": {"INMUEBLE": 470.0, "SOLAR": 20.0}}, "L'Eixample - Pla del Remei"),
    "46005": ({"URBANO": {"INMUEBLE": 3500.0, "SOLAR": 1200.0}, "RÚSTICO": {"INMUEBLE": 440.0, "SOLAR": 19.0}}, "L'Eixample - Gran Via"),
    "46006": ({"URBANO": {"INMUEBLE": 3400.0, "SOLAR": 1150.0}, "RÚSTICO": {"INMUEBLE": 430.0, "SOLAR": 18.0}}, "L'Eixample - Ruzafa / Russafa"),
    "46007": ({"URBANO": {"INMUEBLE": 2700.0, "SOLAR": 900.0}, "RÚSTICO": {"INMUEBLE": 380.0, "SOLAR": 16.0}}, "Extramurs - Arrancapins"),
    "46008": ({"URBANO": {"INMUEBLE": 2800.0, "SOLAR": 950.0}, "RÚSTICO": {"INMUEBLE": 390.0, "SOLAR": 16.0}}, "Extramurs - El Botànic"),
    "46009": ({"URBANO": {"INMUEBLE": 2100.0, "SOLAR": 700.0}, "RÚSTICO": {"INMUEBLE": 330.0, "SOLAR": 14.0}}, "La Saïdia - Marxalenes"),
    "46010": ({"URBANO": {"INMUEBLE": 3400.0, "SOLAR": 1150.0}, "RÚSTICO": {"INMUEBLE": 430.0, "SOLAR": 18.0}}, "El Pla del Real - Exposició / Mestalla"),
    "46011": ({"URBANO": {"INMUEBLE": 2400.0, "SOLAR": 800.0}, "RÚSTICO": {"INMUEBLE": 350.0, "SOLAR": 15.0}}, "Poblats Marítims - Cabanyal"),
    "46012": ({"URBANO": {"INMUEBLE": 1900.0, "SOLAR": 620.0}, "RÚSTICO": {"INMUEBLE": 310.0, "SOLAR": 13.0}}, "Poblats del Sud - El Saler"),
    "46013": ({"URBANO": {"INMUEBLE": 2200.0, "SOLAR": 730.0}, "RÚSTICO": {"INMUEBLE": 340.0, "SOLAR": 14.0}}, "Quatre Carreres - Mont-Olivet"),
    "46014": ({"URBANO": {"INMUEBLE": 1900.0, "SOLAR": 630.0}, "RÚSTICO": {"INMUEBLE": 310.0, "SOLAR": 13.0}}, "L'Olivereta - Nou Moles"),
    "46015": ({"URBANO": {"INMUEBLE": 2900.0, "SOLAR": 980.0}, "RÚSTICO": {"INMUEBLE": 400.0, "SOLAR": 17.0}}, "Campanar - Sant Pau"),
    "46016": ({"URBANO": {"INMUEBLE": 1600.0, "SOLAR": 520.0}, "RÚSTICO": {"INMUEBLE": 290.0, "SOLAR": 12.0}}, "Tavernes Blanques"),
    "46017": ({"URBANO": {"INMUEBLE": 1850.0, "SOLAR": 620.0}, "RÚSTICO": {"INMUEBLE": 300.0, "SOLAR": 13.0}}, "Jesús - La Creu Coberta"),
    "46018": ({"URBANO": {"INMUEBLE": 2100.0, "SOLAR": 700.0}, "RÚSTICO": {"INMUEBLE": 330.0, "SOLAR": 14.0}}, "Patraix - Safranar"),
    "46019": ({"URBANO": {"INMUEBLE": 1700.0, "SOLAR": 560.0}, "RÚSTICO": {"INMUEBLE": 300.0, "SOLAR": 12.0}}, "Rascanya - Torrefiel / Orriols"),
    "46020": ({"URBANO": {"INMUEBLE": 2500.0, "SOLAR": 830.0}, "RÚSTICO": {"INMUEBLE": 360.0, "SOLAR": 15.0}}, "Benimaclet"),
    "46021": ({"URBANO": {"INMUEBLE": 2700.0, "SOLAR": 900.0}, "RÚSTICO": {"INMUEBLE": 380.0, "SOLAR": 16.0}}, "Algirós - Ciutat Jardí"),
    "46022": ({"URBANO": {"INMUEBLE": 2500.0, "SOLAR": 830.0}, "RÚSTICO": {"INMUEBLE": 360.0, "SOLAR": 15.0}}, "Camins al Grau - Ayora"),
    "46023": ({"URBANO": {"INMUEBLE": 3300.0, "SOLAR": 1100.0}, "RÚSTICO": {"INMUEBLE": 420.0, "SOLAR": 18.0}}, "Camins al Grau - França / Penya-roja"),
    "46024": ({"URBANO": {"INMUEBLE": 1800.0, "SOLAR": 600.0}, "RÚSTICO": {"INMUEBLE": 300.0, "SOLAR": 13.0}}, "Poblats Marítims - Natzaret / Grau"),
    "46025": ({"URBANO": {"INMUEBLE": 1850.0, "SOLAR": 620.0}, "RÚSTICO": {"INMUEBLE": 300.0, "SOLAR": 13.0}}, "Benicalap"),
    "46026": ({"URBANO": {"INMUEBLE": 2300.0, "SOLAR": 760.0}, "RÚSTICO": {"INMUEBLE": 340.0, "SOLAR": 14.0}}, "Quatre Carreres - Malilla"),

    # === MÁLAGA Y COSTA DEL SOL ===
    "29001": ({"URBANO": {"INMUEBLE": 3600.0, "SOLAR": 1200.0}, "RÚSTICO": {"INMUEBLE": 450.0, "SOLAR": 20.0}}, "Málaga - Centro Histórico"),
    "29002": ({"URBANO": {"INMUEBLE": 2700.0, "SOLAR": 900.0}, "RÚSTICO": {"INMUEBLE": 380.0, "SOLAR": 16.0}}, "Málaga - El Bulto / Estación"),
    "29003": ({"URBANO": {"INMUEBLE": 2600.0, "SOLAR": 850.0}, "RÚSTICO": {"INMUEBLE": 370.0, "SOLAR": 16.0}}, "Málaga - Carretera de Cádiz"),
    "29004": ({"URBANO": {"INMUEBLE": 2400.0, "SOLAR": 800.0}, "RÚSTICO": {"INMUEBLE": 350.0, "SOLAR": 15.0}}, "Málaga - Guadalhorce"),
    "29005": ({"URBANO": {"INMUEBLE": 3700.0, "SOLAR": 1250.0}, "RÚSTICO": {"INMUEBLE": 460.0, "SOLAR": 20.0}}, "Málaga - Centro Norte"),
    "29006": ({"URBANO": {"INMUEBLE": 2500.0, "SOLAR": 800.0}, "RÚSTICO": {"INMUEBLE": 360.0, "SOLAR": 15.0}}, "Málaga - Cruz de Humilladero"),
    "29010": ({"URBANO": {"INMUEBLE": 2900.0, "SOLAR": 950.0}, "RÚSTICO": {"INMUEBLE": 390.0, "SOLAR": 16.0}}, "Málaga - Teatinos"),
    "29016": ({"URBANO": {"INMUEBLE": 4500.0, "SOLAR": 1500.0}, "RÚSTICO": {"INMUEBLE": 520.0, "SOLAR": 22.0}}, "Málaga - La Malagueta / Limonar"),
    "29017": ({"URBANO": {"INMUEBLE": 4100.0, "SOLAR": 1350.0}, "RÚSTICO": {"INMUEBLE": 490.0, "SOLAR": 21.0}}, "Málaga - Pedregalejo / El Palo"),
    "29601": ({"URBANO": {"INMUEBLE": 3800.0, "SOLAR": 1200.0}, "RÚSTICO": {"INMUEBLE": 500.0, "SOLAR": 22.0}}, "Marbella - Casco Antiguo"),
    "29602": ({"URBANO": {"INMUEBLE": 4200.0, "SOLAR": 1350.0}, "RÚSTICO": {"INMUEBLE": 520.0, "SOLAR": 23.0}}, "Marbella - Milla de Oro"),
    "29660": ({"URBANO": {"INMUEBLE": 4800.0, "SOLAR": 1550.0}, "RÚSTICO": {"INMUEBLE": 560.0, "SOLAR": 25.0}}, "Marbella - Nueva Andalucía / Puerto Banús"),
    "29680": ({"URBANO": {"INMUEBLE": 3100.0, "SOLAR": 1000.0}, "RÚSTICO": {"INMUEBLE": 450.0, "SOLAR": 20.0}}, "Estepona Centro"),
    "29630": ({"URBANO": {"INMUEBLE": 2800.0, "SOLAR": 900.0}, "RÚSTICO": {"INMUEBLE": 420.0, "SOLAR": 18.0}}, "Benalmádena Costa"),

    # === SEVILLA ===
    "41001": ({"URBANO": {"INMUEBLE": 3400.0, "SOLAR": 1100.0}, "RÚSTICO": {"INMUEBLE": 420.0, "SOLAR": 18.0}}, "Sevilla - Centro / Arenal"),
    "41002": ({"URBANO": {"INMUEBLE": 3200.0, "SOLAR": 1050.0}, "RÚSTICO": {"INMUEBLE": 400.0, "SOLAR": 17.0}}, "Sevilla - San Lorenzo / Alameda"),
    "41003": ({"URBANO": {"INMUEBLE": 2100.0, "SOLAR": 700.0}, "RÚSTICO": {"INMUEBLE": 320.0, "SOLAR": 14.0}}, "Sevilla - Macarena"),
    "41004": ({"URBANO": {"INMUEBLE": 3500.0, "SOLAR": 1150.0}, "RÚSTICO": {"INMUEBLE": 430.0, "SOLAR": 18.0}}, "Sevilla - Santa Cruz / Alfalfa"),
    "41006": ({"URBANO": {"INMUEBLE": 1250.0, "SOLAR": 420.0}, "RÚSTICO": {"INMUEBLE": 260.0, "SOLAR": 11.0}}, "Sevilla - Cerro - Amate"),
    "41010": ({"URBANO": {"INMUEBLE": 2900.0, "SOLAR": 950.0}, "RÚSTICO": {"INMUEBLE": 380.0, "SOLAR": 16.0}}, "Sevilla - Triana"),
    "41011": ({"URBANO": {"INMUEBLE": 2800.0, "SOLAR": 920.0}, "RÚSTICO": {"INMUEBLE": 370.0, "SOLAR": 16.0}}, "Sevilla - Los Remedios"),
    "41012": ({"URBANO": {"INMUEBLE": 2600.0, "SOLAR": 850.0}, "RÚSTICO": {"INMUEBLE": 350.0, "SOLAR": 15.0}}, "Sevilla - Sur / Bami"),
    "41018": ({"URBANO": {"INMUEBLE": 2850.0, "SOLAR": 940.0}, "RÚSTICO": {"INMUEBLE": 375.0, "SOLAR": 16.0}}, "Sevilla - Nervión"),

    # === PAÍS VASCO (Bilbao y Donostia) ===
    "48001": ({"URBANO": {"INMUEBLE": 4800.0, "SOLAR": 1600.0}, "RÚSTICO": {"INMUEBLE": 550.0, "SOLAR": 24.0}}, "Bilbao - Abando / Ensanche"),
    "48005": ({"URBANO": {"INMUEBLE": 3500.0, "SOLAR": 1150.0}, "RÚSTICO": {"INMUEBLE": 440.0, "SOLAR": 19.0}}, "Bilbao - Casco Viejo"),
    "48009": ({"URBANO": {"INMUEBLE": 4900.0, "SOLAR": 1650.0}, "RÚSTICO": {"INMUEBLE": 560.0, "SOLAR": 24.0}}, "Bilbao - Abandoibarra / Guggenheim"),
    "48011": ({"URBANO": {"INMUEBLE": 4400.0, "SOLAR": 1450.0}, "RÚSTICO": {"INMUEBLE": 510.0, "SOLAR": 22.0}}, "Bilbao - Indautxu"),
    "48014": ({"URBANO": {"INMUEBLE": 3700.0, "SOLAR": 1200.0}, "RÚSTICO": {"INMUEBLE": 460.0, "SOLAR": 20.0}}, "Bilbao - Deusto / Zorrotzaurre"),
    "20001": ({"URBANO": {"INMUEBLE": 6200.0, "SOLAR": 2100.0}, "RÚSTICO": {"INMUEBLE": 680.0, "SOLAR": 30.0}}, "San Sebastián - Gros"),
    "20004": ({"URBANO": {"INMUEBLE": 6500.0, "SOLAR": 2200.0}, "RÚSTICO": {"INMUEBLE": 700.0, "SOLAR": 31.0}}, "San Sebastián - Centro / La Concha"),
    "20008": ({"URBANO": {"INMUEBLE": 5300.0, "SOLAR": 1800.0}, "RÚSTICO": {"INMUEBLE": 600.0, "SOLAR": 26.0}}, "San Sebastián - Antiguo"),
    "20010": ({"URBANO": {"INMUEBLE": 4200.0, "SOLAR": 1400.0}, "RÚSTICO": {"INMUEBLE": 500.0, "SOLAR": 22.0}}, "San Sebastián - Amara"),

    # === ALICANTE ===
    "03001": ({"URBANO": {"INMUEBLE": 2400.0, "SOLAR": 750.0}, "RÚSTICO": {"INMUEBLE": 350.0, "SOLAR": 15.0}}, "Alicante - Centro / Rambla"),
    "03002": ({"URBANO": {"INMUEBLE": 2200.0, "SOLAR": 700.0}, "RÚSTICO": {"INMUEBLE": 340.0, "SOLAR": 14.0}}, "Alicante - Casco Antiguo"),
    "03003": ({"URBANO": {"INMUEBLE": 2100.0, "SOLAR": 680.0}, "RÚSTICO": {"INMUEBLE": 330.0, "SOLAR": 14.0}}, "Alicante - Maisonnave"),
    "03016": ({"URBANO": {"INMUEBLE": 3100.0, "SOLAR": 1000.0}, "RÚSTICO": {"INMUEBLE": 420.0, "SOLAR": 18.0}}, "Alicante - Playa San Juan"),

    # === BALEARES ===
    "07001": ({"URBANO": {"INMUEBLE": 4800.0, "SOLAR": 1600.0}, "RÚSTICO": {"INMUEBLE": 550.0, "SOLAR": 24.0}}, "Palma - Casco Antiguo"),
    "07002": ({"URBANO": {"INMUEBLE": 4900.0, "SOLAR": 1650.0}, "RÚSTICO": {"INMUEBLE": 560.0, "SOLAR": 25.0}}, "Palma - Cort / Sant Nicolau"),
    "07012": ({"URBANO": {"INMUEBLE": 5200.0, "SOLAR": 1750.0}, "RÚSTICO": {"INMUEBLE": 580.0, "SOLAR": 26.0}}, "Palma - Santa Catalina"),
    "07014": ({"URBANO": {"INMUEBLE": 6500.0, "SOLAR": 2200.0}, "RÚSTICO": {"INMUEBLE": 700.0, "SOLAR": 32.0}}, "Palma - Son Vida"),
    "07800": ({"URBANO": {"INMUEBLE": 5800.0, "SOLAR": 2000.0}, "RÚSTICO": {"INMUEBLE": 650.0, "SOLAR": 29.0}}, "Ibiza - Dalt Vila / Puerto"),

    # === TIER 2: ZARAGOZA, CORUÑA, ASTURIAS, CANARIAS, MURCIA, CASTILLA ===
    "50001": ({"URBANO": {"INMUEBLE": 2400.0, "SOLAR": 750.0}, "RÚSTICO": {"INMUEBLE": 340.0, "SOLAR": 15.0}}, "Zaragoza - Centro"),
    "50004": ({"URBANO": {"INMUEBLE": 2500.0, "SOLAR": 800.0}, "RÚSTICO": {"INMUEBLE": 350.0, "SOLAR": 15.0}}, "Zaragoza - Paseo Independencia"),
    "50017": ({"URBANO": {"INMUEBLE": 1400.0, "SOLAR": 450.0}, "RÚSTICO": {"INMUEBLE": 280.0, "SOLAR": 12.0}}, "Zaragoza - Delicias"),
    "50018": ({"URBANO": {"INMUEBLE": 1950.0, "SOLAR": 620.0}, "RÚSTICO": {"INMUEBLE": 310.0, "SOLAR": 13.0}}, "Zaragoza - Actur"),
    "15001": ({"URBANO": {"INMUEBLE": 2700.0, "SOLAR": 850.0}, "RÚSTICO": {"INMUEBLE": 360.0, "SOLAR": 16.0}}, "A Coruña - Ciudad Vieja"),
    "15003": ({"URBANO": {"INMUEBLE": 2600.0, "SOLAR": 820.0}, "RÚSTICO": {"INMUEBLE": 350.0, "SOLAR": 15.0}}, "A Coruña - Ensanche / Riazor"),
    "33001": ({"URBANO": {"INMUEBLE": 2000.0, "SOLAR": 620.0}, "RÚSTICO": {"INMUEBLE": 310.0, "SOLAR": 13.0}}, "Oviedo - Centro"),
    "33201": ({"URBANO": {"INMUEBLE": 2300.0, "SOLAR": 720.0}, "RÚSTICO": {"INMUEBLE": 330.0, "SOLAR": 14.0}}, "Gijón - Centro / San Lorenzo"),
    "35001": ({"URBANO": {"INMUEBLE": 2600.0, "SOLAR": 800.0}, "RÚSTICO": {"INMUEBLE": 350.0, "SOLAR": 15.0}}, "Las Palmas - Vegueta / Triana"),
    "35007": ({"URBANO": {"INMUEBLE": 2800.0, "SOLAR": 880.0}, "RÚSTICO": {"INMUEBLE": 370.0, "SOLAR": 16.0}}, "Las Palmas - Las Canteras"),
    "38001": ({"URBANO": {"INMUEBLE": 2300.0, "SOLAR": 700.0}, "RÚSTICO": {"INMUEBLE": 330.0, "SOLAR": 14.0}}, "Santa Cruz de Tenerife - Centro"),
    "18001": ({"URBANO": {"INMUEBLE": 2200.0, "SOLAR": 680.0}, "RÚSTICO": {"INMUEBLE": 320.0, "SOLAR": 14.0}}, "Granada - Centro"),
    "11001": ({"URBANO": {"INMUEBLE": 2600.0, "SOLAR": 800.0}, "RÚSTICO": {"INMUEBLE": 350.0, "SOLAR": 15.0}}, "Cádiz - Casco Histórico"),
    "11401": ({"URBANO": {"INMUEBLE": 1300.0, "SOLAR": 400.0}, "RÚSTICO": {"INMUEBLE": 260.0, "SOLAR": 11.0}}, "Jerez de la Frontera - Centro"),
    "30001": ({"URBANO": {"INMUEBLE": 1800.0, "SOLAR": 550.0}, "RÚSTICO": {"INMUEBLE": 300.0, "SOLAR": 13.0}}, "Murcia - Centro"),
    "47001": ({"URBANO": {"INMUEBLE": 2100.0, "SOLAR": 650.0}, "RÚSTICO": {"INMUEBLE": 320.0, "SOLAR": 14.0}}, "Valladolid - Centro"),
    "14001": ({"URBANO": {"INMUEBLE": 1850.0, "SOLAR": 580.0}, "RÚSTICO": {"INMUEBLE": 300.0, "SOLAR": 13.0}}, "Córdoba - Centro"),
    "43001": ({"URBANO": {"INMUEBLE": 1900.0, "SOLAR": 590.0}, "RÚSTICO": {"INMUEBLE": 310.0, "SOLAR": 13.0}}, "Tarragona - Centro / Rambla"),
    "17001": ({"URBANO": {"INMUEBLE": 2700.0, "SOLAR": 850.0}, "RÚSTICO": {"INMUEBLE": 360.0, "SOLAR": 16.0}}, "Girona - Barri Vell"),
    "45001": ({"URBANO": {"INMUEBLE": 1800.0, "SOLAR": 550.0}, "RÚSTICO": {"INMUEBLE": 300.0, "SOLAR": 13.0}}, "Toledo - Casco"),
    "45600": ({"URBANO": {"INMUEBLE": 950.0, "SOLAR": 280.0}, "RÚSTICO": {"INMUEBLE": 220.0, "SOLAR": 10.0}}, "Talavera de la Reina"),
    "01001": ({"URBANO": {"INMUEBLE": 2800.0, "SOLAR": 880.0}, "RÚSTICO": {"INMUEBLE": 370.0, "SOLAR": 16.0}}, "Vitoria-Gasteiz - Centro"),
    "31001": ({"URBANO": {"INMUEBLE": 2900.0, "SOLAR": 900.0}, "RÚSTICO": {"INMUEBLE": 380.0, "SOLAR": 16.0}}, "Pamplona - Ensanche / Casco"),
    "39001": ({"URBANO": {"INMUEBLE": 3200.0, "SOLAR": 1000.0}, "RÚSTICO": {"INMUEBLE": 410.0, "SOLAR": 18.0}}, "Santander - Centro / Sardinero"),
    "37001": ({"URBANO": {"INMUEBLE": 2100.0, "SOLAR": 650.0}, "RÚSTICO": {"INMUEBLE": 320.0, "SOLAR": 14.0}}, "Salamanca - Centro"),
    "09001": ({"URBANO": {"INMUEBLE": 1900.0, "SOLAR": 600.0}, "RÚSTICO": {"INMUEBLE": 300.0, "SOLAR": 13.0}}, "Burgos - Centro"),
    "12001": ({"URBANO": {"INMUEBLE": 1500.0, "SOLAR": 470.0}, "RÚSTICO": {"INMUEBLE": 280.0, "SOLAR": 12.0}}, "Castellón - Centro"),
    "04001": ({"URBANO": {"INMUEBLE": 1500.0, "SOLAR": 470.0}, "RÚSTICO": {"INMUEBLE": 280.0, "SOLAR": 12.0}}, "Almería - Centro"),
}

# Mapeo exhaustivo de nombres de barrios y distritos a Códigos Postales
DISTRICT_NEIGHBORHOOD_TO_CP: Dict[str, str] = {
    # Madrid - Vallecas y Sureste (Clave para resolver Benarrabá / Palomeras)
    "palomeras sureste": "28018",
    "palomeras bajas": "28018",
    "palomeras": "28018",
    "puente de vallecas": "28018",
    "vallecas": "28018",
    "entrevias": "28053",
    "entrevías": "28053",
    "san diego": "28053",
    "numancia": "28038",
    "portazgo": "28038",
    "santa eugenia": "28031",
    "villa de vallecas": "28031",
    "ensanche de vallecas": "28051",
    "valdecarros": "28051",
    "vicalvaro": "28032",
    "vicálvaro": "28032",
    "valdebernardo": "28032",
    "el cañaveral": "28052" if "el cañaveral" else "28052",
    "canaveral": "28052",
    "los berrocales": "28052",
    "los ahijones": "28052",
    # Madrid - Sur y Oeste
    "carabanchel": "28019",
    "comillas": "28019",
    "opañel": "28019",
    "opanel": "28019",
    "san isidro": "28019",
    "vista alegre": "28025",
    "vistalegre": "28025",
    "puerta bonita": "28025",
    "pau de carabanchel": "28054",
    "la peseta": "28054",
    "usera": "28026",
    "moscardo": "28026",
    "moscardó": "28026",
    "pradolongo": "28026",
    "orcasitas": "28041",
    "orcasur": "28041",
    "san fermin": "28041",
    "san fermín": "28041",
    "villaverde": "28021",
    "san cristobal": "28021",
    "san cristóbal": "28021",
    "butarque": "28021",
    "los rosales": "28021",
    "latina": "28011",
    "puerta del angel": "28011",
    "puerta del ángel": "28011",
    "campamento": "28024",
    "aluche": "28024",
    "las aguilas": "28044",
    "las águilas": "28044",
    "lucero": "28047",
    # Madrid - Centro, Chamberí, Salamanca, Retiro
    "salamanca": "28001",
    "recoletos": "28001",
    "castellana": "28006",
    "goya": "28001",
    "lista": "28006",
    "guindalera": "28028",
    "fuente del berro": "28028",
    "chamberi": "28010",
    "chamberí": "28010",
    "almagro": "28010",
    "trafalgar": "28010",
    "vallehermoso": "28003",
    "gaztambide": "28015",
    "arapiles": "28015",
    "retiro": "28009",
    "ibiza": "28009",
    "pacifico": "28007",
    "pacífico": "28007",
    "adelfas": "28007",
    "estrella": "28007",
    "centro madrid": "28013",
    "malasaña": "28004",
    "malasana": "28004",
    "chueca": "28004",
    "justicia": "28004",
    "la latina": "28005",
    "lavapies": "28012",
    "lavapiés": "28012",
    "sol": "28013",
    "cortes": "28014",
    "arganzuela": "28045",
    "delicias": "28045",
    "legazpi": "28045",
    "mendez alvaro": "28045",
    "méndez álvaro": "28045",
    # Madrid - Norte y Este
    "chamartin": "28002",
    "chamartín": "28002",
    "el viso": "28002",
    "prosperidad": "28002",
    "nueva españa": "28016",
    "nueva espana": "28016",
    "tetuan": "28020",
    "tetuán": "28020",
    "cuatro caminos": "28020",
    "castillejos": "28020",
    "cuzco": "28020",
    "bellas vistas": "28039",
    "valdeacederas": "28029",
    "moncloa": "28008",
    "argüelles": "28008",
    "arguelles": "28008",
    "aravaca": "28023",
    "valdemarin": "28023",
    "valdemarín": "28023",
    "ciudad lineal": "28017",
    "ventas": "28017",
    "pueblo nuevo": "28017",
    "quintana": "28017",
    "concepcion": "28027",
    "concepción": "28027",
    "san pascual": "28027",
    "arturo soria": "28027",
    "san blas": "28037",
    "simancas": "28037",
    "canillejas": "28022",
    "rejas": "28022",
    "moratalaz": "28030",
    "pavones": "28030",
    "fontarron": "28030",
    "fontarrón": "28030",
    "hortaleza": "28033",
    "pinar del rey": "28033",
    "sanchinarro": "28050",
    "valdebebas": "28055",
    "fuencarral": "28034",
    "mirasierra": "28034",
    "montecarmelo": "28034",
    "peñagrande": "28035",
    "penagrande": "28035",
    "las tablas": "28050",
    "barajas": "28042",
    "alameda de osuna": "28042",

    # Barcelona
    "eixample": "08007",
    "dreta de l'eixample": "08007",
    "esquerra de l'eixample": "08011",
    "sagrada familia": "08013",
    "sagrada família": "08013",
    "sant antoni": "08015",
    "fort pienc": "08009",
    "gracia": "08012",
    "gràcia": "08012",
    "vila de gracia": "08012",
    "vallcarca": "08023",
    "poblenou": "08005",
    "vila olimpica": "08005",
    "diagonal mar": "08019",
    "clot": "08026",
    "camp de l'arpa": "08025",
    "sant marti": "08020",
    "sarria": "08017",
    "sarrià": "08017",
    "tres torres": "08017",
    "sant gervasi": "08006",
    "galvany": "08006",
    "bonanova": "08021",
    "putxet": "08022",
    "ciutat vella": "08001",
    "raval": "08001",
    "gotic": "08002",
    "gòtic": "08002",
    "born": "08003",
    "barceloneta": "08003",
    "sants": "08014",
    "poble sec": "08004",
    "poble-sec": "08004",
    "les corts": "08029",
    "pedralbes": "08034",
    "maternitat": "08028",
    "horta": "08031",
    "guinardo": "08041",
    "guinardó": "08041",
    "carmel": "08032",
    "can baró": "08024",
    "can baro": "08024",
    "marià labèrnia": "08024",
    "maria labernia": "08024",
    "nou barris": "08016",
    "vilapicina": "08016",
    "roquetes": "08042",
    "ciutat meridiana": "08033",
    "sant andreu": "08030",
    "sagrera": "08027",

    # Valencia
    "ruzafa": "46006",
    "russafa": "46006",
    "pla del remei": "46004",
    "gran via": "46005",
    "ciutat vella valencia": "46001",
    "el carme": "46001",
    "cabanyal": "46011",
    "el grau": "46024",
    "campanar": "46015",
    "benimaclet": "46020",
    "patraix": "46018",
    "mestalla": "46010",
    "malilla": "46026",
    "olivereta": "46014",
    "saïdia": "46009",
    "saidia": "46009",
    "torrefiel": "46019",
    "orriols": "46019",
    "benicalap": "46025",
    "gayano lluch": "46025",

    # Madrid - Calles y barrios adicionales
    "fuentespina": "28031",
    "fermin caballero": "28029",
    "fermín caballero": "28029",
    "barrio del pilar": "28029",
    "puerto de arlaban": "28053",
    "eduardo requenas": "28053",
    "peña ubiña": "28053",
    "pena ubina": "28053",
    "mestanza": "28053",
    "marianistas": "28044",
    "buena vista": "28044",
    "buenavista": "28044",
    "cullera": "28047",
    "palomeras bajas": "28018",
    "palomeras sureste": "28018",
    "palomeras": "28018",
    "sierra de pineda": "28018"
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
    is_solar: bool = False,
    postal_code: Optional[str] = None
) -> Tuple[float, str, str]:
    """
    Resuelve el precio de referencia de mercado (€/m²) utilizando la Matriz 2x2.
    Eje Y: [URBANO, RÚSTICO]
    Eje X: [INMUEBLE, SOLAR]

    Jerarquía:
    1. Código postal explícito o extraído en CP_DISTRICT_MARKET_2X2
    2. Detección de barrio / distrito en DISTRICT_NEIGHBORHOOD_TO_CP
    3. Coincidencia con Municipio en MUNICIPALITY_MARKET_2X2
    4. Coincidencia con Distrito Capital
    5. Benchmark Provincial
    """
    prov_key = (province_str or "").strip().upper()
    loc_key = (locality_str or "").strip().upper()
    
    # Eje Y: URBANO vs RÚSTICO
    y_axis = "RÚSTICO" if ("RUSTICO" in (land_type or "").upper() or "AGRARIO" in (land_type or "").upper()) else "URBANO"
    
    # Eje X: INMUEBLE vs SOLAR
    x_axis = "SOLAR" if is_solar else "INMUEBLE"

    combined_text = f"{full_address_str} {desc_text} {locality_str} {province_str}".lower()
    text_normalized = combined_text.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")

    # 1. Intentar por Código Postal (CP) explícito o en texto
    cp_candidate = (postal_code or "").strip()
    if not cp_candidate or len(cp_candidate) != 5:
        cp_candidate = extract_postal_code(combined_text)

    if cp_candidate and cp_candidate in CP_DISTRICT_MARKET_2X2:
        matrix, label = CP_DISTRICT_MARKET_2X2[cp_candidate]
        price = matrix[y_axis][x_axis]
        return price, "SECCION", f"Barrio/CP MIVAU [{label} ({cp_candidate})]"

    # 2. Intentar por Barrio / Distrito mapeado directamente a CP
    # Ordenar por longitud descendente para que "palomeras sureste" coincida antes que "palomeras"
    for neighborhood_key, mapped_cp in sorted(DISTRICT_NEIGHBORHOOD_TO_CP.items(), key=lambda x: len(x[0]), reverse=True):
        if re.search(rf'\b{re.escape(neighborhood_key)}\b', text_normalized):
            if mapped_cp in CP_DISTRICT_MARKET_2X2:
                matrix, label = CP_DISTRICT_MARKET_2X2[mapped_cp]
                price = matrix[y_axis][x_axis]
                return price, "SECCION", f"Barrio/CP MIVAU [{label} ({mapped_cp})]"

    # 3. Intentar por Municipio / Localidad exacta
    if loc_key in MUNICIPALITY_MARKET_2X2:
        matrix = MUNICIPALITY_MARKET_2X2[loc_key]
        price = matrix[y_axis][x_axis]
        return price, "MUNICIPAL", f"Municipio MIVAU [{locality_str or loc_key}]"

    # 4. Intentar por Distrito en Grandes Capitales
    if prov_key in ["MADRID", "BARCELONA", "MÁLAGA", "MALAGA", "VALENCIA", "VALÈNCIA", "VALENCIA/VALÈNCIA", "SEVILLA"]:
        for cp_key, (matrix, district_name) in CP_DISTRICT_MARKET_2X2.items():
            dist_norm = district_name.lower().replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
            if dist_norm in text_normalized:
                price = matrix[y_axis][x_axis]
                return price, "SECCION", f"Barrio/Distrito MIVAU [{district_name}]"

    # 5. Fallback a Benchmark Provincial (utilizando el municipio/localidad real como nombre)
    prov_matrix = PROVINCE_MARKET_2X2.get(prov_key)
    if not prov_matrix:
        clean_prov = prov_key.split("/")[0].strip()
        prov_matrix = PROVINCE_MARKET_2X2.get(clean_prov, DEFAULT_2X2)
        
    price = prov_matrix[y_axis][x_axis]
    display_loc = locality_str.strip() if locality_str and locality_str.strip() else (province_str or 'España')
    return price, "MUNICIPAL", f"Municipio MIVAU [{display_loc}]"


# --- MESO URBANIZATION COST BENCHMARK ENGINE (€/m²s) ---
PROVINCE_URBANIZATION_COST: Dict[str, float] = {
    "MADRID": 65.0,
    "BARCELONA": 62.0,
    "BALEARES": 75.0,
    "BALEARS": 75.0,
    "ILLES BALEARS": 75.0,
    "GIPUZKOA": 70.0,
    "BIZKAIA": 68.0,
    "MÁLAGA": 55.0,
    "MALAGA": 55.0,
    "SEVILLA": 52.0,
    "VALENCIA": 50.0,
    "VALÈNCIA": 50.0,
    "VALENCIA/VALÈNCIA": 50.0,
    "ALICANTE": 48.0,
    "GIRONA": 52.0,
    "TARRAGONA": 45.0,
    "ZARAGOZA": 45.0,
    "CÁDIZ": 48.0,
    "GRANADA": 45.0,
    "MURCIA": 42.0,
    "TOLEDO": 38.0,
    "GUADALAJARA": 42.0,
}

CP_MUNICIPALITY_URBANIZATION_COST: Dict[str, Tuple[float, str]] = {
    "28014": (75.0, "Madrid Capital (Centro/Cortes)"),
    "28001": (85.0, "Madrid Capital (Salamanca)"),
    "28006": (85.0, "Madrid Capital (Salamanca)"),
    "28037": (65.0, "Madrid (San Blas-Canillejas)"),
    "28045": (70.0, "Madrid (Arganzuela)"),
    "08014": (68.0, "Barcelona (Sants-Montjuïc)"),
    "08001": (75.0, "Barcelona (Ciutat Vella)"),
    "41014": (55.0, "Sevilla (Bellavista-La Palmera)"),
    "46011": (52.0, "Valencia (Poblats Marítims-El Grau)"),
}

def resolve_urbanization_cost_m2s(
    province_str: str,
    locality_str: str,
    full_address_str: str = "",
    desc_text: str = ""
) -> Tuple[float, str, str]:
    """
    Resuelve el coste medio estimado de urbanización (€/m²s) basado en la jerarquía Meso:
    1. Código Postal (CP)
    2. Distrito / Municipio
    3. Benchmark Provincial

    Retorna: (coste_m2s, fuente_codigo, fuente_label)
    """
    combined_text = f"{full_address_str} {desc_text} {locality_str}".lower()
    cp = extract_postal_code(combined_text)
    
    if cp and cp in CP_MUNICIPALITY_URBANIZATION_COST:
        cost, label = CP_MUNICIPALITY_URBANIZATION_COST[cp]
        return cost, "CP", f"Meso CP {cp} ({label})"
    
    prov_key = (province_str or "").strip().upper()
    loc_key = (locality_str or "").strip().upper()
    
    # Check if locality matches any key
    for cp_k, (cost, label) in CP_MUNICIPALITY_URBANIZATION_COST.items():
        if loc_key and loc_key in label.upper():
            return cost, "MUNICIPAL", f"Meso Municipio [{locality_str}]"
            
    cost = PROVINCE_URBANIZATION_COST.get(prov_key, 45.0)
    display_loc = locality_str.strip() if locality_str and locality_str.strip() else (province_str or "España")
    return cost, "MUNICIPAL", f"Meso Municipio/Provincia [{display_loc}]"

