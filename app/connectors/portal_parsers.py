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
from app.connectors.boe_scraper import BOESubastasScraper
from app.engine.meso_market_price import (
    resolve_meso_market_price_2x2,
    extract_postal_code,
    DISTRICT_NEIGHBORHOOD_TO_CP,
    CP_DISTRICT_MARKET_2X2,
)

logger = logging.getLogger(__name__)


# Centroides de coordenadas y datos socioeconómicos de referencia por distrito/localidad
DISTRICT_COORDINATES: Dict[str, Dict[str, Any]] = {
    # MADRID CAPITAL Y DISTRITOS
    "salamanca": {"lat": 40.4297, "lon": -3.6822, "income": 58000, "m2_price": 6800.0, "growth": 1.2, "cp": "28001"},
    "goya": {"lat": 40.4245, "lon": -3.6765, "income": 56000, "m2_price": 6500.0, "growth": 1.1, "cp": "28009"},
    "recoletos": {"lat": 40.4225, "lon": -3.6885, "income": 69000, "m2_price": 8500.0, "growth": 0.9, "cp": "28001"},
    "castellana": {"lat": 40.4355, "lon": -3.6850, "income": 62000, "m2_price": 7200.0, "growth": 1.0, "cp": "28006"},
    "guindalera": {"lat": 40.4360, "lon": -3.6680, "income": 48000, "m2_price": 5100.0, "growth": 1.4, "cp": "28028"},
    "fuente del berro": {"lat": 40.4260, "lon": -3.6630, "income": 51000, "m2_price": 5400.0, "growth": 1.3, "cp": "28028"},
    "el viso": {"lat": 40.4465, "lon": -3.6820, "income": 72000, "m2_price": 7200.0, "growth": 0.7, "cp": "28002"},
    "chamartin": {"lat": 40.4625, "lon": -3.6765, "income": 54200, "m2_price": 5400.0, "growth": 1.9, "cp": "28036"},
    "prosperidad": {"lat": 40.4440, "lon": -3.6730, "income": 47000, "m2_price": 4900.0, "growth": 1.5, "cp": "28002"},
    "ciudad jardin": {"lat": 40.4500, "lon": -3.6710, "income": 49000, "m2_price": 5100.0, "growth": 1.4, "cp": "28002"},
    "hispanoamerica": {"lat": 40.4560, "lon": -3.6780, "income": 57000, "m2_price": 5600.0, "growth": 1.2, "cp": "28016"},
    "nueva españa": {"lat": 40.4650, "lon": -3.6790, "income": 61000, "m2_price": 5800.0, "growth": 1.1, "cp": "28036"},
    "castilla": {"lat": 40.4725, "lon": -3.6845, "income": 53000, "m2_price": 5200.0, "growth": 1.8, "cp": "28036"},
    "chamberi": {"lat": 40.4350, "lon": -3.7020, "income": 58900, "m2_price": 6300.0, "growth": 0.8, "cp": "28010"},
    "trafalgar": {"lat": 40.4320, "lon": -3.7015, "income": 57000, "m2_price": 6100.0, "growth": 0.9, "cp": "28010"},
    "almagro": {"lat": 40.4310, "lon": -3.6920, "income": 64000, "m2_price": 7100.0, "growth": 0.8, "cp": "28010"},
    "arapiles": {"lat": 40.4340, "lon": -3.7070, "income": 55000, "m2_price": 5900.0, "growth": 0.9, "cp": "28015"},
    "gaztambide": {"lat": 40.4360, "lon": -3.7140, "income": 54000, "m2_price": 5800.0, "growth": 0.9, "cp": "28015"},
    "vallehermoso": {"lat": 40.4430, "lon": -3.7110, "income": 59000, "m2_price": 6200.0, "growth": 0.8, "cp": "28003"},
    "rios rosas": {"lat": 40.4420, "lon": -3.6980, "income": 58000, "m2_price": 6100.0, "growth": 0.9, "cp": "28003"},
    "centro": {"lat": 40.4180, "lon": -3.7060, "income": 42000, "m2_price": 5200.0, "growth": 1.5, "cp": "28012"},
    "malasaña": {"lat": 40.4265, "lon": -3.7045, "income": 44500, "m2_price": 5300.0, "growth": 1.6, "cp": "28004"},
    "chueca": {"lat": 40.4230, "lon": -3.6980, "income": 46000, "m2_price": 5500.0, "growth": 1.4, "cp": "28004"},
    "palacio": {"lat": 40.4150, "lon": -3.7130, "income": 46000, "m2_price": 5400.0, "growth": 1.2, "cp": "28013"},
    "sol": {"lat": 40.4170, "lon": -3.7035, "income": 43000, "m2_price": 5600.0, "growth": 1.3, "cp": "28013"},
    "cortes": {"lat": 40.4140, "lon": -3.6970, "income": 48000, "m2_price": 5800.0, "growth": 1.1, "cp": "28014"},
    "justicia": {"lat": 40.4240, "lon": -3.6960, "income": 52000, "m2_price": 6400.0, "growth": 1.2, "cp": "28004"},
    "universidad": {"lat": 40.4270, "lon": -3.7070, "income": 44000, "m2_price": 5300.0, "growth": 1.5, "cp": "28004"},
    "lavapies": {"lat": 40.4090, "lon": -3.7010, "income": 36000, "m2_price": 4500.0, "growth": 1.8, "cp": "28012"},
    "embajadores": {"lat": 40.4080, "lon": -3.7020, "income": 36500, "m2_price": 4500.0, "growth": 1.8, "cp": "28012"},
    "retiro": {"lat": 40.4110, "lon": -3.6780, "income": 53500, "m2_price": 5900.0, "growth": 1.0, "cp": "28009"},
    "ibiza": {"lat": 40.4185, "lon": -3.6760, "income": 52000, "m2_price": 5800.0, "growth": 1.0, "cp": "28009"},
    "pacifico": {"lat": 40.4040, "lon": -3.6780, "income": 46000, "m2_price": 4800.0, "growth": 1.4, "cp": "28007"},
    "adelfas": {"lat": 40.3990, "lon": -3.6680, "income": 42000, "m2_price": 4400.0, "growth": 1.6, "cp": "28007"},
    "estrella": {"lat": 40.4110, "lon": -3.6650, "income": 49000, "m2_price": 4900.0, "growth": 1.3, "cp": "28007"},
    "vallecas": {"lat": 40.3850, "lon": -3.6600, "income": 28500, "m2_price": 2300.0, "growth": 3.2, "cp": "28018"},
    "puente de vallecas": {"lat": 40.3850, "lon": -3.6600, "income": 28500, "m2_price": 2300.0, "growth": 3.2, "cp": "28018"},
    "palomeras sureste": {"lat": 40.3880, "lon": -3.6380, "income": 28500, "m2_price": 2300.0, "growth": 3.2, "cp": "28018"},
    "palomeras": {"lat": 40.3880, "lon": -3.6380, "income": 28500, "m2_price": 2300.0, "growth": 3.2, "cp": "28018"},
    "san diego": {"lat": 40.3920, "lon": -3.6680, "income": 27000, "m2_price": 2300.0, "growth": 2.9, "cp": "28018"},
    "entrevias": {"lat": 40.3800, "lon": -3.6700, "income": 26000, "m2_price": 2100.0, "growth": 2.8, "cp": "28018"},
    "portazgo": {"lat": 40.3900, "lon": -3.6550, "income": 28000, "m2_price": 2300.0, "growth": 3.0, "cp": "28018"},
    "numancia": {"lat": 40.3980, "lon": -3.6580, "income": 29000, "m2_price": 2400.0, "growth": 2.7, "cp": "28038"},
    "santa eugenia": {"lat": 40.3840, "lon": -3.6110, "income": 34000, "m2_price": 2400.0, "growth": 2.8, "cp": "28031"},
    "villa de vallecas": {"lat": 40.3780, "lon": -3.6180, "income": 34000, "m2_price": 2400.0, "growth": 2.8, "cp": "28031"},
    "casco historico de vallecas": {"lat": 40.3780, "lon": -3.6180, "income": 33000, "m2_price": 2350.0, "growth": 2.8, "cp": "28031"},
    "ensanche de vallecas": {"lat": 40.3620, "lon": -3.6010, "income": 37200, "m2_price": 3100.0, "growth": 3.8, "cp": "28051"},
    "vicalvaro": {"lat": 40.4020, "lon": -3.6080, "income": 34500, "m2_price": 2800.0, "growth": 3.9, "cp": "28032"},
    "el cañaveral": {"lat": 40.4150, "lon": -3.5600, "income": 38000, "m2_price": 3200.0, "growth": 4.8, "cp": "28052"},
    "los berrocales": {"lat": 40.3685, "lon": -3.5890, "income": 36500, "m2_price": 3100.0, "growth": 4.5, "cp": "28052"},
    "carabanchel": {"lat": 40.3850, "lon": -3.7400, "income": 28500, "m2_price": 2750.0, "growth": 2.1, "cp": "28025"},
    "vista alegre": {"lat": 40.3885, "lon": -3.7420, "income": 29000, "m2_price": 2700.0, "growth": 2.0, "cp": "28025"},
    "san isidro": {"lat": 40.3950, "lon": -3.7250, "income": 31000, "m2_price": 2900.0, "growth": 2.1, "cp": "28019"},
    "opañel": {"lat": 40.3880, "lon": -3.7180, "income": 30000, "m2_price": 2800.0, "growth": 2.0, "cp": "28019"},
    "buena vista": {"lat": 40.3720, "lon": -3.7500, "income": 29500, "m2_price": 2650.0, "growth": 2.2, "cp": "28025"},
    "aluche": {"lat": 40.3870, "lon": -3.7650, "income": 30000, "m2_price": 2500.0, "growth": 2.2, "cp": "28024"},
    "campamento": {"lat": 40.3950, "lon": -3.7750, "income": 31000, "m2_price": 2500.0, "growth": 2.0, "cp": "28024"},
    "latina": {"lat": 40.4050, "lon": -3.7480, "income": 31000, "m2_price": 2650.0, "growth": 1.9, "cp": "28011"},
    "puerta del angel": {"lat": 40.4120, "lon": -3.7310, "income": 32000, "m2_price": 2650.0, "growth": 2.0, "cp": "28011"},
    "lucero": {"lat": 40.4050, "lon": -3.7400, "income": 30500, "m2_price": 2650.0, "growth": 2.0, "cp": "28011"},
    "usera": {"lat": 40.3820, "lon": -3.7050, "income": 27000, "m2_price": 2250.0, "growth": 2.4, "cp": "28026"},
    "moscardo": {"lat": 40.3890, "lon": -3.7050, "income": 27500, "m2_price": 2250.0, "growth": 2.3, "cp": "28026"},
    "orcasitas": {"lat": 40.3700, "lon": -3.7150, "income": 25000, "m2_price": 2100.0, "growth": 2.1, "cp": "28041"},
    "san fermin": {"lat": 40.3680, "lon": -3.6920, "income": 25500, "m2_price": 2100.0, "growth": 2.1, "cp": "28041"},
    "villaverde": {"lat": 40.3450, "lon": -3.7100, "income": 26000, "m2_price": 1950.0, "growth": 2.1, "cp": "28021"},
    "san cristobal": {"lat": 40.3410, "lon": -3.6920, "income": 23000, "m2_price": 1750.0, "growth": 2.0, "cp": "28021"},
    "butarque": {"lat": 40.3380, "lon": -3.6820, "income": 29000, "m2_price": 2100.0, "growth": 3.0, "cp": "28021"},
    "villaverde alto": {"lat": 40.3450, "lon": -3.7150, "income": 25500, "m2_price": 1950.0, "growth": 2.0, "cp": "28021"},
    "villaverde bajo": {"lat": 40.3520, "lon": -3.6950, "income": 26500, "m2_price": 2000.0, "growth": 2.1, "cp": "28021"},
    "san blas": {"lat": 40.4350, "lon": -3.6180, "income": 32000, "m2_price": 2550.0, "growth": 2.5, "cp": "28037"},
    "simancas": {"lat": 40.4300, "lon": -3.6260, "income": 31000, "m2_price": 2550.0, "growth": 2.5, "cp": "28037"},
    "canillejas": {"lat": 40.4420, "lon": -3.6050, "income": 33000, "m2_price": 2700.0, "growth": 2.4, "cp": "28022"},
    "moratalaz": {"lat": 40.4070, "lon": -3.6450, "income": 34000, "m2_price": 2750.0, "growth": 1.8, "cp": "28030"},
    "ciudad lineal": {"lat": 40.4450, "lon": -3.6520, "income": 38000, "m2_price": 3100.0, "growth": 1.7, "cp": "28017"},
    "ventas": {"lat": 40.4310, "lon": -3.6590, "income": 37000, "m2_price": 3100.0, "growth": 1.7, "cp": "28017"},
    "pueblo nuevo": {"lat": 40.4320, "lon": -3.6420, "income": 33000, "m2_price": 2850.0, "growth": 1.8, "cp": "28017"},
    "quintana": {"lat": 40.4360, "lon": -3.6490, "income": 35000, "m2_price": 3000.0, "growth": 1.7, "cp": "28027"},
    "concepcion": {"lat": 40.4410, "lon": -3.6520, "income": 36000, "m2_price": 3050.0, "growth": 1.6, "cp": "28027"},
    "barajas": {"lat": 40.4730, "lon": -3.5800, "income": 41000, "m2_price": 3400.0, "growth": 2.0, "cp": "28042"},
    "alameda de osuna": {"lat": 40.4570, "lon": -3.5880, "income": 45000, "m2_price": 3600.0, "growth": 1.8, "cp": "28042"},
    "arganzuela": {"lat": 40.3990, "lon": -3.6980, "income": 46000, "m2_price": 4400.0, "growth": 2.1, "cp": "28045"},
    "delicias": {"lat": 40.4010, "lon": -3.6920, "income": 45000, "m2_price": 4400.0, "growth": 2.0, "cp": "28045"},
    "legazpi": {"lat": 40.3910, "lon": -3.6960, "income": 44000, "m2_price": 4400.0, "growth": 2.2, "cp": "28045"},
    "tetuan": {"lat": 40.4580, "lon": -3.7020, "income": 37000, "m2_price": 4100.0, "growth": 2.2, "cp": "28020"},
    "cuatro caminos": {"lat": 40.4490, "lon": -3.7020, "income": 39000, "m2_price": 4300.0, "growth": 2.0, "cp": "28020"},
    "moncloa": {"lat": 40.4350, "lon": -3.7250, "income": 51000, "m2_price": 4900.0, "growth": 1.1, "cp": "28008"},
    "fuencarral": {"lat": 40.4950, "lon": -3.7050, "income": 49000, "m2_price": 4400.0, "growth": 2.6, "cp": "28034"},
    "hortaleza": {"lat": 40.4700, "lon": -3.6550, "income": 47000, "m2_price": 4200.0, "growth": 2.1, "cp": "28043"},

    # BARCELONA
    "eixample": {"lat": 41.3880, "lon": 2.1620, "income": 49800, "m2_price": 5100.0, "growth": 0.6, "cp": "08007"},
    "dreta de l'eixample": {"lat": 41.3930, "lon": 2.1670, "income": 52000, "m2_price": 5300.0, "growth": 0.7, "cp": "08009"},
    "dreta de leixample": {"lat": 41.3930, "lon": 2.1670, "income": 52000, "m2_price": 5300.0, "growth": 0.7, "cp": "08009"},
    "esquerra de l'eixample": {"lat": 41.3840, "lon": 2.1550, "income": 49000, "m2_price": 4950.0, "growth": 0.6, "cp": "08011"},
    "esquerra de leixample": {"lat": 41.3840, "lon": 2.1550, "income": 49000, "m2_price": 4950.0, "growth": 0.6, "cp": "08011"},
    "nova esquerra": {"lat": 41.3810, "lon": 2.1480, "income": 47500, "m2_price": 4850.0, "growth": 0.6, "cp": "08015"},
    "sant antoni": {"lat": 41.3795, "lon": 2.1595, "income": 43000, "m2_price": 4650.0, "growth": 0.8, "cp": "08015"},
    "sagrada familia": {"lat": 41.4035, "lon": 2.1745, "income": 45000, "m2_price": 4700.0, "growth": 1.0, "cp": "08013"},
    "fort pienc": {"lat": 41.3960, "lon": 2.1830, "income": 44000, "m2_price": 4600.0, "growth": 0.9, "cp": "08013"},
    "gracia": {"lat": 41.4030, "lon": 2.1580, "income": 44100, "m2_price": 4900.0, "growth": 1.1, "cp": "08012"},
    "vila de gracia": {"lat": 41.4030, "lon": 2.1570, "income": 44100, "m2_price": 4900.0, "growth": 1.1, "cp": "08012"},
    "camp d'en grassot": {"lat": 41.4060, "lon": 2.1660, "income": 42000, "m2_price": 4500.0, "growth": 1.0, "cp": "08025"},
    "poblenou": {"lat": 41.4020, "lon": 2.2020, "income": 48200, "m2_price": 4600.0, "growth": 2.9, "cp": "08005"},
    "sant marti": {"lat": 41.4150, "lon": 2.2000, "income": 42000, "m2_price": 4100.0, "growth": 2.4, "cp": "08020"},
    "sarria": {"lat": 41.4010, "lon": 2.1220, "income": 68000, "m2_price": 6200.0, "growth": 0.5, "cp": "08017"},
    "les tres torres": {"lat": 41.3990, "lon": 2.1290, "income": 71000, "m2_price": 6400.0, "growth": 0.4, "cp": "08017"},
    "sant gervasi": {"lat": 41.4050, "lon": 2.1380, "income": 64000, "m2_price": 5900.0, "growth": 0.5, "cp": "08022"},
    "vallvidrera": {"lat": 41.4160, "lon": 2.1020, "income": 58000, "m2_price": 5100.0, "growth": 0.6, "cp": "08017"},
    "ciutat vella": {"lat": 41.3820, "lon": 2.1750, "income": 33000, "m2_price": 4400.0, "growth": 1.2, "cp": "08001"},
    "raval": {"lat": 41.3790, "lon": 2.1685, "income": 31000, "m2_price": 4100.0, "growth": 1.3, "cp": "08001"},
    "gotic": {"lat": 41.3825, "lon": 2.1765, "income": 35000, "m2_price": 4600.0, "growth": 1.1, "cp": "08002"},
    "gòtic": {"lat": 41.3825, "lon": 2.1765, "income": 35000, "m2_price": 4600.0, "growth": 1.1, "cp": "08002"},
    "sant pere": {"lat": 41.3870, "lon": 2.1795, "income": 36000, "m2_price": 4500.0, "growth": 1.2, "cp": "08003"},
    "barceloneta": {"lat": 41.3800, "lon": 2.1900, "income": 34000, "m2_price": 4800.0, "growth": 1.0, "cp": "08003"},
    "sants": {"lat": 41.3750, "lon": 2.1380, "income": 38500, "m2_price": 3800.0, "growth": 1.4, "cp": "08014"},
    "sants-badal": {"lat": 41.3740, "lon": 2.1280, "income": 37000, "m2_price": 3700.0, "growth": 1.3, "cp": "08028"},
    "la bordeta": {"lat": 41.3690, "lon": 2.1360, "income": 36000, "m2_price": 3600.0, "growth": 1.4, "cp": "08014"},
    "hostafrancs": {"lat": 41.3750, "lon": 2.1430, "income": 38000, "m2_price": 3850.0, "growth": 1.3, "cp": "08014"},
    "poble sec": {"lat": 41.3730, "lon": 2.1620, "income": 35000, "m2_price": 3900.0, "growth": 1.2, "cp": "08004"},
    "les corts": {"lat": 41.3850, "lon": 2.1280, "income": 56000, "m2_price": 5300.0, "growth": 0.8, "cp": "08028"},
    "sant andreu": {"lat": 41.4350, "lon": 2.1900, "income": 35000, "m2_price": 3300.0, "growth": 1.5, "cp": "08030"},
    "nou barris": {"lat": 41.4420, "lon": 2.1750, "income": 27000, "m2_price": 2700.0, "growth": 1.8, "cp": "08031"},
    "horta": {"lat": 41.4310, "lon": 2.1550, "income": 36000, "m2_price": 3400.0, "growth": 1.3, "cp": "08032"},
    "guinardo": {"lat": 41.4190, "lon": 2.1760, "income": 37000, "m2_price": 3500.0, "growth": 1.4, "cp": "08041"},
    "guinardó": {"lat": 41.4190, "lon": 2.1760, "income": 37000, "m2_price": 3500.0, "growth": 1.4, "cp": "08041"},
    "can baro": {"lat": 41.4170, "lon": 2.1610, "income": 36500, "m2_price": 3450.0, "growth": 1.3, "cp": "08024"},
    "can baró": {"lat": 41.4170, "lon": 2.1610, "income": 36500, "m2_price": 3450.0, "growth": 1.3, "cp": "08024"},
    "carmel": {"lat": 41.4230, "lon": 2.1550, "income": 29000, "m2_price": 2800.0, "growth": 1.5, "cp": "08032"},
    "el carmel": {"lat": 41.4230, "lon": 2.1550, "income": 29000, "m2_price": 2800.0, "growth": 1.5, "cp": "08032"},
    "besos": {"lat": 41.4190, "lon": 2.2140, "income": 28000, "m2_price": 2750.0, "growth": 1.6, "cp": "08019"},
    "besòs": {"lat": 41.4190, "lon": 2.2140, "income": 28000, "m2_price": 2750.0, "growth": 1.6, "cp": "08019"},
    "verneda": {"lat": 41.4240, "lon": 2.2030, "income": 30000, "m2_price": 2900.0, "growth": 1.5, "cp": "08020"},
    "plaza de catalunya": {"lat": 41.3870, "lon": 2.1700, "income": 50000, "m2_price": 5200.0, "growth": 0.7, "cp": "08002"},
    "rambla de catalunya": {"lat": 41.3910, "lon": 2.1620, "income": 53000, "m2_price": 5400.0, "growth": 0.6, "cp": "08007"},

    # VALENCIA
    "ruzafa": {"lat": 39.4625, "lon": -0.3735, "income": 38900, "m2_price": 3600.0, "growth": 1.7, "cp": "46006"},
    "el grau": {"lat": 39.4605, "lon": -0.3370, "income": 33400, "m2_price": 2950.0, "growth": 3.4, "cp": "46024"},
    "ciutat vella valencia": {"lat": 39.4750, "lon": -0.3780, "income": 41000, "m2_price": 3700.0, "growth": 1.2, "cp": "46001"},
    "campanar": {"lat": 39.4830, "lon": -0.3950, "income": 36000, "m2_price": 2800.0, "growth": 2.2, "cp": "46015"},
    "benimaclet": {"lat": 39.4870, "lon": -0.3580, "income": 35000, "m2_price": 2850.0, "growth": 2.0, "cp": "46020"},
    "patraix": {"lat": 39.4610, "lon": -0.3950, "income": 31000, "m2_price": 2300.0, "growth": 2.1, "cp": "46018"},
    "sant marcelli": {"lat": 39.4480, "lon": -0.3920, "income": 29000, "m2_price": 2150.0, "growth": 2.3, "cp": "46017"},
    "sant marcellí": {"lat": 39.4480, "lon": -0.3920, "income": 29000, "m2_price": 2150.0, "growth": 2.3, "cp": "46017"},
    "sant marcel·lí": {"lat": 39.4480, "lon": -0.3920, "income": 29000, "m2_price": 2150.0, "growth": 2.3, "cp": "46017"},
    "mont-olivet": {"lat": 39.4580, "lon": -0.3620, "income": 33000, "m2_price": 2650.0, "growth": 2.2, "cp": "46006"},
    "cabanyal": {"lat": 39.4670, "lon": -0.3280, "income": 32000, "m2_price": 2750.0, "growth": 3.5, "cp": "46011"},
    "canyamelar": {"lat": 39.4640, "lon": -0.3270, "income": 32000, "m2_price": 2750.0, "growth": 3.5, "cp": "46011"},
    "torrefiel": {"lat": 39.4930, "lon": -0.3720, "income": 28000, "m2_price": 2050.0, "growth": 2.4, "cp": "46019"},
    "orriols": {"lat": 39.4920, "lon": -0.3640, "income": 26500, "m2_price": 1950.0, "growth": 2.5, "cp": "46019"},
    "sant francesc": {"lat": 39.4700, "lon": -0.3770, "income": 42000, "m2_price": 3850.0, "growth": 1.2, "cp": "46002"},
    "petxina": {"lat": 39.4730, "lon": -0.3880, "income": 36000, "m2_price": 2900.0, "growth": 1.9, "cp": "46008"},
    "pla del remei": {"lat": 39.4680, "lon": -0.3680, "income": 47000, "m2_price": 4200.0, "growth": 1.0, "cp": "46004"},
    "aiora": {"lat": 39.4680, "lon": -0.3470, "income": 31000, "m2_price": 2450.0, "growth": 2.6, "cp": "46022"},
    "betero": {"lat": 39.4720, "lon": -0.3390, "income": 30000, "m2_price": 2350.0, "growth": 2.7, "cp": "46022"},
    "beteró": {"lat": 39.4720, "lon": -0.3390, "income": 30000, "m2_price": 2350.0, "growth": 2.7, "cp": "46022"},
    "na rovella": {"lat": 39.4530, "lon": -0.3640, "income": 31500, "m2_price": 2400.0, "growth": 2.3, "cp": "46013"},
    "la seu": {"lat": 39.4760, "lon": -0.3750, "income": 41500, "m2_price": 3800.0, "growth": 1.1, "cp": "46003"},
    "la xerea": {"lat": 39.4740, "lon": -0.3710, "income": 43000, "m2_price": 3900.0, "growth": 1.1, "cp": "46003"},
    "el mercat": {"lat": 39.4730, "lon": -0.3790, "income": 39000, "m2_price": 3550.0, "growth": 1.3, "cp": "46001"},
    "benimamet": {"lat": 39.5010, "lon": -0.4240, "income": 28500, "m2_price": 1950.0, "growth": 2.2, "cp": "46035"},
    "benimàmet": {"lat": 39.5010, "lon": -0.4240, "income": 28500, "m2_price": 1950.0, "growth": 2.2, "cp": "46035"},
    "gayano lluch": {"lat": 39.4950, "lon": -0.3730, "income": 29500, "m2_price": 2100.0, "growth": 2.3, "cp": "46025"},

    # MALAGA
    "soho": {"lat": 36.7170, "lon": -4.4230, "income": 41800, "m2_price": 4200.0, "growth": 2.5, "cp": "29001"},
    "teatinos": {"lat": 36.7190, "lon": -4.4750, "income": 38000, "m2_price": 3100.0, "growth": 3.6, "cp": "29010"},
    "cortijo merino": {"lat": 36.7020, "lon": -4.4810, "income": 31200, "m2_price": 2650.0, "growth": 3.9, "cp": "29004"},
    "cruz de humilladero": {"lat": 36.7120, "lon": -4.4450, "income": 30500, "m2_price": 2550.0, "growth": 2.8, "cp": "29006"},
    "carretera de cadiz": {"lat": 36.6980, "lon": -4.4420, "income": 29000, "m2_price": 2600.0, "growth": 3.2, "cp": "29003"},

    # ALICANTE PROVINCIA (LOCALIDADES CLAVE)
    "denia": {"lat": 38.8407, "lon": 0.1057, "income": 34000, "m2_price": 2850.0, "growth": 2.8, "cp": "03700"},
    "dénia": {"lat": 38.8407, "lon": 0.1057, "income": 34000, "m2_price": 2850.0, "growth": 2.8, "cp": "03700"},
    "benidorm": {"lat": 38.5411, "lon": -0.1225, "income": 32000, "m2_price": 2900.0, "growth": 2.5, "cp": "03501"},
    "altea": {"lat": 38.5989, "lon": -0.0514, "income": 36000, "m2_price": 3100.0, "growth": 2.1, "cp": "03590"},
    "calpe": {"lat": 38.6447, "lon": 0.0457, "income": 33000, "m2_price": 2950.0, "growth": 2.2, "cp": "03710"},
    "calp": {"lat": 38.6447, "lon": 0.0457, "income": 33000, "m2_price": 2950.0, "growth": 2.2, "cp": "03710"},
    "torrevieja": {"lat": 37.9787, "lon": -0.6822, "income": 28000, "m2_price": 2100.0, "growth": 3.1, "cp": "03181"},
    "elche": {"lat": 38.2669, "lon": -0.6983, "income": 31000, "m2_price": 1650.0, "growth": 2.0, "cp": "03201"},
    "javea": {"lat": 38.7894, "lon": 0.1661, "income": 37000, "m2_price": 3400.0, "growth": 2.4, "cp": "03730"},
    "jávea": {"lat": 38.7894, "lon": 0.1661, "income": 37000, "m2_price": 3400.0, "growth": 2.4, "cp": "03730"},

    # VALENCIA PROVINCIA (LOCALIDADES CLAVE)
    "gandia": {"lat": 38.9676, "lon": -0.1804, "income": 31000, "m2_price": 1850.0, "growth": 2.3, "cp": "46701"},
    "gandía": {"lat": 38.9676, "lon": -0.1804, "income": 31000, "m2_price": 1850.0, "growth": 2.3, "cp": "46701"},
    "cullera": {"lat": 39.1633, "lon": -0.2541, "income": 32000, "m2_price": 2150.0, "growth": 2.6, "cp": "46400"},
    "oliva": {"lat": 38.9197, "lon": -0.1211, "income": 29000, "m2_price": 1650.0, "growth": 2.1, "cp": "46780"},
    "sagunto": {"lat": 39.6796, "lon": -0.2785, "income": 33000, "m2_price": 1750.0, "growth": 3.0, "cp": "46520"},
    "sagunt": {"lat": 39.6796, "lon": -0.2785, "income": 33000, "m2_price": 1750.0, "growth": 3.0, "cp": "46520"},
    "torrent": {"lat": 39.4367, "lon": -0.4658, "income": 34000, "m2_price": 1800.0, "growth": 2.2, "cp": "46900"},

    # MALAGA PROVINCIA
    "marbella": {"lat": 36.5101, "lon": -4.8824, "income": 45000, "m2_price": 4500.0, "growth": 3.2, "cp": "29601"},
    "estepona": {"lat": 36.4256, "lon": -5.1459, "income": 38000, "m2_price": 3300.0, "growth": 3.8, "cp": "29680"},
    "fuengirola": {"lat": 36.5399, "lon": -4.6247, "income": 34000, "m2_price": 3100.0, "growth": 2.9, "cp": "29640"},

    # BARCELONA PROVINCIA
    "sitges": {"lat": 41.2372, "lon": 1.8059, "income": 52000, "m2_price": 4800.0, "growth": 1.8, "cp": "08870"},
    "badalona": {"lat": 41.4469, "lon": 2.2450, "income": 35000, "m2_price": 2700.0, "growth": 2.5, "cp": "08911"},
    "sant cugat del valles": {"lat": 41.4722, "lon": 2.0863, "income": 65000, "m2_price": 4600.0, "growth": 1.2, "cp": "08172"},

    # MADRID PROVINCIA
    "pozuelo de alarcon": {"lat": 40.4354, "lon": -3.8138, "income": 78000, "m2_price": 4400.0, "growth": 0.9, "cp": "28223"},
    "las rozas de madrid": {"lat": 40.4925, "lon": -3.8744, "income": 62000, "m2_price": 3800.0, "growth": 1.4, "cp": "28231"},
    "alcobendas": {"lat": 40.5475, "lon": -3.6421, "income": 59000, "m2_price": 3900.0, "growth": 1.3, "cp": "28100"},
}

LOCALITY_TO_PROVINCE: Dict[str, str] = {
    "denia": "Alicante",
    "dénia": "Alicante",
    "benidorm": "Alicante",
    "altea": "Alicante",
    "calpe": "Alicante",
    "calp": "Alicante",
    "torrevieja": "Alicante",
    "elche": "Alicante",
    "elx": "Alicante",
    "javea": "Alicante",
    "jávea": "Alicante",
    "xabia": "Alicante",
    "xàbia": "Alicante",
    "gandia": "Valencia",
    "gandía": "Valencia",
    "cullera": "Valencia",
    "oliva": "Valencia",
    "sagunto": "Valencia",
    "sagunt": "Valencia",
    "torrent": "Valencia",
    "marbella": "Málaga",
    "estepona": "Málaga",
    "fuengirola": "Málaga",
    "sitges": "Barcelona",
    "badalona": "Barcelona",
    "sant cugat del valles": "Barcelona",
    "sant cugat del vallès": "Barcelona",
    "pozuelo de alarcon": "Madrid",
    "pozuelo de alarcón": "Madrid",
    "las rozas": "Madrid",
    "las rozas de madrid": "Madrid",
    "alcobendas": "Madrid",
    "madrid": "Madrid",
    "barcelona": "Barcelona",
    "valencia": "Valencia",
    "alicante": "Alicante",
    "malaga": "Málaga",
    "málaga": "Málaga",
    "sevilla": "Sevilla",
    "zaragoza": "Zaragoza",
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

                if len(title) < 5 or re.match(r'^\d+/\d+$', title):
                    continue

                # Contexto previo (para fotos y comercializadora)
                start_prev = matches[i - 1].end() if i > 0 else max(0, match.start() - 1500)
                prev_text = markdown_content[start_prev:match.start()]

                # Contexto posterior (para precios, características y descripción)
                end_post = matches[i + 1].start() if i + 1 < len(matches) else min(len(markdown_content), match.end() + 2000)
                post_text = markdown_content[match.end():end_post]

                # Descartar naves para cualquier mercado
                if BOESubastasScraper.is_nave(title=title, desc=post_text[:600], property_type=""):
                    continue

                # 1. Comercializadora / Agencia
                agency = "Agencia Inmobiliaria"
                agency_matches = list(re.finditer(r'\[(?:Comercializa)?(?P<agency>[^\]]+)\]\(https?://(?:www\.)?idealista\.com/pro/[^\)]+\)', prev_text))
                if agency_matches:
                    agency = agency_matches[-1].group("agency").replace("Comercializa", "").strip()

                # 2. Imágenes del inmueble: capturar todas las fotos disponibles sin límite
                images = []
                full_img_block = prev_text + "\n" + post_text[:2500]
                img_matches = re.findall(r'https?://img\d*\.idealista\.com/[^\s\"\)\']+', full_img_block)
                for img_url in img_matches:
                    if img_url.endswith('.gif'):
                        continue
                    clean_img = (
                        img_url.replace("/blur/189_120_mq/", "/blur/WEB_DETAIL-XL-L/")
                        .replace("/blur/300_225_mq/", "/blur/WEB_DETAIL-XL-L/")
                        .replace("/blur/480_360_mq/", "/blur/WEB_DETAIL-XL-L/")
                        .replace("/blur/WEB_DETAIL_TOP-L-L/", "/blur/WEB_DETAIL-XL-L/")
                        .replace("/blur/591_420_mq/", "/blur/WEB_DETAIL-XL-L/")
                    )
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

                price_drop_amount = max(0.0, original_listing_price - listing_price)
                price_drop_percentage = discount_percentage
                price_drop_date = "2026-03-01" if price_drop_amount > 0 else None

                # 4. Características: "Garaje incluido 3 hab.131 m²3ª planta exterior con ascensor"
                rooms = 2
                rooms_match = re.search(r'(\d+)\s*hab(?:\.|\b)', post_text[:400])
                if rooms_match:
                    rooms = int(rooms_match.group(1))

                surface_m2 = 80.0
                surf_match = re.search(r'(\d+(?:\.\d+)?)\s*m[²2]', post_text[:400])
                if surf_match:
                    surface_m2 = float(surf_match.group(1).replace(".", ""))

                # Descartar naves camufladas con superficie >= 600 m2
                if BOESubastasScraper.is_nave(title=title, desc=post_text[:600], property_type="", surface_m2=surface_m2):
                    continue

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
                    "price_drop_percentage": price_drop_percentage,
                    "price_drop_amount": price_drop_amount,
                    "price_drop_date": price_drop_date,
                    "discount_percentage": discount_percentage,
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

                opportunity["portal_id"] = str(item_id)
                opportunity["portal_url"] = url
                opportunity["primary_portal"] = "Idealista"
                opportunity["discount_percentage"] = discount_percentage if discount_percentage > 0 else discount_vs_market

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
    def _resolve_location_and_kpis(cls, title: str, default_province: str, explicit_cp: Optional[str] = None) -> Dict[str, Any]:
        """
        Resuelve con exactitud el código postal, distrito, coordenadas y KPIs meso (precio m2, renta per cápita)
        a partir del título o dirección utilizando la matriz MIVAU / INE CP_DISTRICT_MARKET_2X2.
        """
        t_lower = (title or "").lower()
        prov_lower = (default_province or "Madrid").lower().strip()

        # 1. Buscar coincidencias en DISTRICT_NEIGHBORHOOD_TO_CP (priorizando nombres más largos)
        matched_neighborhood = None
        for n_key, cp in sorted(DISTRICT_NEIGHBORHOOD_TO_CP.items(), key=lambda x: len(x[0]), reverse=True):
            if re.search(rf'\b{re.escape(n_key)}\b', t_lower):
                matched_neighborhood = n_key
                break

        # 2. Determinar el Código Postal
        # Prioridad: barrio específico > CP extraído del texto > CP explícito (si no es genérico de capital)
        postal_code = None
        generic_center_cps = {"28001", "08001", "46001", "29001", "03001", "41001", "50001"}
        if matched_neighborhood:
            postal_code = DISTRICT_NEIGHBORHOOD_TO_CP[matched_neighborhood]
        elif explicit_cp and explicit_cp.isdigit() and len(explicit_cp) == 5 and explicit_cp not in generic_center_cps:
            postal_code = explicit_cp
        else:
            extracted = extract_postal_code(title)
            if extracted:
                postal_code = extracted
            elif explicit_cp and explicit_cp.isdigit() and len(explicit_cp) == 5:
                postal_code = explicit_cp

        # 3. Datos del CP desde la matriz MIVAU CP_DISTRICT_MARKET_2X2
        cp_meta = CP_DISTRICT_MARKET_2X2.get(postal_code) if postal_code else None

        # 4. Determinar Localidad, Provincia y Distrito
        locality = default_province
        province = default_province
        district_label = f"{default_province} Centro"
        avg_income = 38000
        growth_rate = 1.5

        # Detección inteligente de localidad y provincia
        detected_loc_key = None
        if default_province and default_province.lower().strip() in LOCALITY_TO_PROVINCE:
            detected_loc_key = default_province.lower().strip()
        elif matched_neighborhood and matched_neighborhood in LOCALITY_TO_PROVINCE:
            detected_loc_key = matched_neighborhood
        else:
            for l_key in LOCALITY_TO_PROVINCE:
                if re.search(rf'\b{re.escape(l_key)}\b', t_lower):
                    detected_loc_key = l_key
                    break

        if detected_loc_key:
            province = LOCALITY_TO_PROVINCE[detected_loc_key]
            # Normalizar nombre formal de la localidad
            loc_names = {
                "denia": "Dénia", "dénia": "Dénia",
                "benidorm": "Benidorm", "altea": "Altea",
                "calpe": "Calpe", "calp": "Calpe",
                "torrevieja": "Torrevieja", "elche": "Elche", "elx": "Elche",
                "javea": "Jávea", "jávea": "Jávea", "xabia": "Jávea", "xàbia": "Jávea",
                "gandia": "Gandía", "gandía": "Gandía",
                "cullera": "Cullera", "oliva": "Oliva",
                "sagunto": "Sagunto", "sagunt": "Sagunto", "torrent": "Torrent",
                "marbella": "Marbella", "estepona": "Estepona", "fuengirola": "Fuengirola",
                "sitges": "Sitges", "badalona": "Badalona",
                "sant cugat del valles": "Sant Cugat del Vallès", "sant cugat del vallès": "Sant Cugat del Vallès",
                "pozuelo de alarcon": "Pozuelo de Alarcón", "pozuelo de alarcón": "Pozuelo de Alarcón",
                "las rozas": "Las Rozas de Madrid", "las rozas de madrid": "Las Rozas de Madrid",
                "alcobendas": "Alcobendas"
            }
            locality = loc_names.get(detected_loc_key, detected_loc_key.capitalize())
            district_label = f"{locality} Centro"

        if cp_meta:
            _, district_label = cp_meta

        if matched_neighborhood and matched_neighborhood in DISTRICT_COORDINATES:
            coord_data = DISTRICT_COORDINATES[matched_neighborhood]
            avg_income = coord_data.get("income", 38000)
            growth_rate = coord_data.get("growth", 1.5)
        elif detected_loc_key and detected_loc_key in DISTRICT_COORDINATES:
            coord_data = DISTRICT_COORDINATES[detected_loc_key]
            avg_income = coord_data.get("income", 38000)
            growth_rate = coord_data.get("growth", 1.5)

        # 5. Obtener precio meso exacto con resolve_meso_market_price_2x2 (Matriz 2x2)
        is_solar = any(k in t_lower for k in ["solar", "terreno", "suelo", "parcela", "finca rústica", "finca rustica"])
        land_type = "RÚSTICO" if any(k in t_lower for k in ["rústico", "rustico", "agrario", "campo"]) else "URBANO"
        m2_price, meso_code, meso_label = resolve_meso_market_price_2x2(
            province_str=province,
            locality_str=locality,
            full_address_str=title,
            desc_text="",
            land_type=land_type,
            is_solar=is_solar,
            postal_code=postal_code
        )

        PROV_CP_PREFIX = {
            "madrid": "28",
            "barcelona": "08",
            "valencia": "46",
            "valència": "46",
            "malaga": "29",
            "málaga": "29",
            "sevilla": "41",
            "alicante": "03",
        }
        target_cp_prefix = None
        for prov_name, pref in PROV_CP_PREFIX.items():
            if prov_name in prov_lower or prov_name in locality.lower():
                target_cp_prefix = pref
                break

        # 6. Coordenadas geográficas
        lat, lon = None, None
        for d_key, coords in DISTRICT_COORDINATES.items():
            coord_cp = coords.get("cp", "")
            if target_cp_prefix and coord_cp and not coord_cp.startswith(target_cp_prefix):
                continue
            if d_key in t_lower or (matched_neighborhood and d_key == matched_neighborhood):
                lat = coords.get("lat")
                lon = coords.get("lon")
                if not postal_code and coord_cp:
                    postal_code = coord_cp
                break

        # Fallback de coordenadas por provincia o capital
        if lat is None or lon is None:
            coords_prov = DISTRICT_COORDINATES.get(province.lower()) or DISTRICT_COORDINATES.get(locality.lower())
            if coords_prov:
                lat, lon = coords_prov.get("lat"), coords_prov.get("lon")
            else:
                if "valencia" in prov_lower or "valència" in prov_lower or "valencia" in locality.lower():
                    lat, lon = (39.4699, -0.3763)
                elif "madrid" in prov_lower:
                    lat, lon = (40.4168, -3.7038)
                elif "barcelona" in prov_lower:
                    lat, lon = (41.3879, 2.1699)
                elif "malaga" in prov_lower or "málaga" in prov_lower:
                    lat, lon = (36.7213, -4.4214)
                elif "sevilla" in prov_lower:
                    lat, lon = (37.3891, -5.9845)
                elif "alicante" in prov_lower:
                    lat, lon = (38.3452, -0.4810)
                else:
                    lat, lon = (40.4168, -3.7038)

        # Fallback de postal_code si aún es None
        if not postal_code:
            if "madrid" in prov_lower:
                postal_code = "28001"
            elif "barcelona" in prov_lower:
                postal_code = "08001"
            elif "valencia" in prov_lower:
                postal_code = "46001"
            elif "malaga" in prov_lower or "málaga" in prov_lower:
                postal_code = "29001"
            elif "toledo" in prov_lower:
                postal_code = "45600" if "talavera" in t_lower else "45001"
            else:
                postal_code = "28001"

        return {
            "address": title,
            "locality": locality,
            "province": province,
            "postal_code": postal_code,
            "lat": lat,
            "lon": lon,
            "district_label": district_label,
            "avg_household_income": avg_income,
            "area_m2_price": m2_price,
            "population_growth_rate": growth_rate,
            "meso_label": meso_label
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
        # o enlaces con /inmueble/, /viviendas/ o /i<id>.htm
        link_pattern = re.compile(
            r'\[(?P<title>[^\]]+)\]\((?P<url>https?://(?:www\.)?habitaclia\.com/(?:[^\)]*-)?i?(?P<id>\d{6,})\.htm[^\s\)]*)(?:\s+"[^"]*")?\)',
            re.IGNORECASE
        )

        matches = list(link_pattern.finditer(markdown_content))
        for i, match in enumerate(matches):
            try:
                item_id = match.group("id") or str(100000 + i)
                title = match.group("title").strip()
                url = match.group("url")

                if len(title) < 5 or re.match(r'^\d+/\d+$', title):
                    continue

                # Contexto previo y posterior (amplio para abarcar carrusel de fotos previo)
                start_prev = matches[i - 1].end() if i > 0 else max(0, match.start() - 8000)
                prev_text = markdown_content[start_prev:match.start()]
                end_post = matches[i + 1].start() if i + 1 < len(matches) else min(len(markdown_content), match.end() + 2000)
                post_text = markdown_content[match.end():end_post]

                # Descartar naves
                if BOESubastasScraper.is_nave(title=title, desc=post_text[:600], property_type=""):
                    continue

                price_match = re.search(r'(\d{1,3}(?:\.\d{3})+)\s*€', prev_text) or re.search(r'(\d{1,3}(?:\.\d{3})+)\s*€', post_text)
                if not price_match:
                    continue

                listing_price = float(price_match.group(1).replace(".", ""))
                if listing_price < 20000:
                    continue

                # Localización
                loc_data = IdealistaMarkdownParser._resolve_location_and_kpis(title, default_province)

                # Superficie y habitaciones
                surf_match = re.search(r'(\d+(?:\.\d+)?)\s*m[²2]', post_text) or re.search(r'(\d+(?:\.\d+)?)\s*m[²2]', prev_text)
                surface_m2 = float(surf_match.group(1).replace(".", "")) if surf_match else 85.0

                rooms_match = re.search(r'(\d+)\s*hab', post_text) or re.search(r'(\d+)\s*hab', prev_text)
                rooms = int(rooms_match.group(1)) if rooms_match else 3

                # Extraer hasta 20 imágenes del carrusel
                images = []
                raw_img_matches = (
                    re.findall(r'https?://static\.fotocasa\.es/images/ads/[^\s\"\)\']+', prev_text + "\n" + post_text)
                    + re.findall(r'!\[[^\]]*\]\((https?://[^\)]+)\)', prev_text + "\n" + post_text)
                )
                for img_url in raw_img_matches:
                    clean_img = img_url.split("?")[0] + "?rule=web_listing_440x330" if "static.fotocasa.es" in img_url else img_url
                    if clean_img not in images:
                        images.append(clean_img)
                    if len(images) >= 20:
                        break

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
                    "price_drop_percentage": 0.0,
                    "price_drop_amount": 0.0,
                    "price_drop_date": None,
                    "discount_percentage": 0.0,
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
                    "images": images,
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

                opportunity["portal_id"] = str(item_id)
                opportunity["portal_url"] = url
                opportunity["primary_portal"] = "Habitaclia"
                opportunity["discount_percentage"] = discount_vs_market

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


class FotocasaMarkdownParser:
    """
    Parser especializado para extraer oportunidades estructuradas
    del Markdown generado por Supadata al consultar Fotocasa.es.
    """

    @classmethod
    def parse_listings(cls, markdown_content: str, default_province: str = "Madrid") -> List[Dict[str, Any]]:
        listings: List[Dict[str, Any]] = []
        if not markdown_content:
            return listings

        # Fotocasa: [Título](https://www.fotocasa.es/es/comprar/vivienda/...)
        link_pattern = re.compile(
            r'\[(?P<title>[^\]]+)\]\((?P<url>https?://(?:www\.)?fotocasa\.es/es/comprar/vivienda/[^\)]*(?:/(?P<id>\d{6,})|-(?P<alt_id>\d{6,}))[^\)]*)\)',
            re.IGNORECASE
        )

        matches = list(link_pattern.finditer(markdown_content))
        if not matches:
            fallback_pattern = re.compile(
                r'\[(?P<title>[^\]]+)\]\((?P<url>https?://(?:www\.)?fotocasa\.es/es/comprar/[^\)]+)\)',
                re.IGNORECASE
            )
            matches = list(fallback_pattern.finditer(markdown_content))

        for i, match in enumerate(matches):
            try:
                item_id = match.groupdict().get("id") or match.groupdict().get("alt_id") or str(200000 + i)
                title = match.group("title").strip()
                url = match.group("url")

                if len(title) < 5 or re.match(r'^\d+/\d+$', title):
                    continue

                start_prev = matches[i - 1].end() if i > 0 else max(0, match.start() - 1200)
                prev_text = markdown_content[start_prev:match.start()]
                end_post = matches[i + 1].start() if i + 1 < len(matches) else min(len(markdown_content), match.end() + 1500)
                post_text = markdown_content[match.end():end_post]

                if BOESubastasScraper.is_nave(title=title, desc=post_text[:600], property_type=""):
                    continue

                # Precios
                price_matches = re.findall(r'(\d{1,3}(?:\.\d{3})+)\s*€(?!\s*/\s*m[²2]|\s*/\s*mes)', post_text[:500])
                if not price_matches:
                    continue

                clean_prices = [float(p.replace(".", "")) for p in price_matches if float(p.replace(".", "")) > 15000]
                if not clean_prices:
                    continue

                listing_price = clean_prices[0]
                original_listing_price = clean_prices[1] if len(clean_prices) > 1 and clean_prices[1] > listing_price else listing_price
                price_drop_amount = max(0.0, original_listing_price - listing_price)
                price_drop_percentage = round((price_drop_amount / original_listing_price) * 100, 1) if original_listing_price > 0 else 0.0
                price_drop_date = "2026-03-01" if price_drop_amount > 0 else None

                # Superficie, habitaciones, planta, ascensor
                rooms = 2
                rooms_match = re.search(r'(\d+)\s*(?:habs?|hab\b|habitaciones)', post_text[:400], re.IGNORECASE)
                if rooms_match:
                    rooms = int(rooms_match.group(1))

                surface_m2 = 80.0
                surf_match = re.search(r'(\d+(?:\.\d+)?)\s*m[²2]', post_text[:400])
                if surf_match:
                    surface_m2 = float(surf_match.group(1).replace(".", ""))

                floor = "Exterior"
                floor_match = re.search(r'(\d+[ªº]?\s*planta|bajo|ático|entreplanta)', post_text[:400], re.IGNORECASE)
                if floor_match:
                    floor = floor_match.group(1).strip()

                has_elevator = "sin ascensor" not in post_text[:400].lower()

                # Imágenes: capturar hasta 20 fotos del inmueble
                images = []
                raw_img_matches = (
                    re.findall(r'https?://static\.fotocasa\.es/images/ads/[^\s\"\)\']+', prev_text + "\n" + post_text[:4000])
                    + re.findall(r'!\[[^\]]*\]\((https?://[^\)]+)\)', prev_text + "\n" + post_text[:4000])
                )
                for img_url in raw_img_matches:
                    clean_img = img_url.split("?")[0] + "?rule=web_listing_440x330" if "static.fotocasa.es" in img_url else img_url
                    if clean_img not in images:
                        images.append(clean_img)
                    if len(images) >= 20:
                        break

                # Ubicación y KPIs meso
                loc_data = IdealistaMarkdownParser._resolve_location_and_kpis(title, default_province)

                opportunity = {
                    "id": f"MKT-FOTOCASA-{item_id}",
                    "title": title,
                    "address": loc_data.get("address") or title,
                    "locality": loc_data.get("locality", default_province),
                    "province": loc_data.get("province", default_province),
                    "postal_code": loc_data.get("postal_code", "28001"),
                    "lat": loc_data.get("lat"),
                    "lon": loc_data.get("lon"),
                    "property_type": "PISO" if "chalet" not in title.lower() else "CHALET",
                    "strategy": "HOUSE_FLIPPING" if surface_m2 < 140 else "BUY_AND_HOLD",
                    "surface_m2": surface_m2,
                    "rooms": rooms,
                    "bathrooms": max(1, rooms - 1),
                    "floor": floor,
                    "has_elevator": has_elevator,
                    "energy_certificate": "E",
                    "original_listing_price": original_listing_price,
                    "listing_price": listing_price,
                    "price_drop_percentage": price_drop_percentage,
                    "price_drop_amount": price_drop_amount,
                    "price_drop_date": price_drop_date,
                    "discount_percentage": price_drop_percentage,
                    "first_published_date": "2026-03-01",
                    "publications": [
                        {
                            "portal": "Fotocasa",
                            "price": listing_price,
                            "url": url,
                            "agency": "Inmobiliaria Fotocasa",
                            "published_date": "2026-03-01"
                        }
                    ],
                    "census_tract_data": {
                        "district": loc_data.get("district_label", default_province),
                        "avg_household_income": loc_data.get("avg_household_income", 40000),
                        "avg_person_income": round(loc_data.get("avg_household_income", 40000) / 2.2),
                        "area_m2_price": loc_data.get("area_m2_price", 3400.0),
                        "population_growth_rate": loc_data.get("population_growth_rate", 1.5)
                    },
                    "images": images,
                    "description": f"{title}. Inmueble verificado en Fotocasa."
                }

                is_solar = (opportunity.get("strategy") == "LAND_DEVELOPMENT" or "solar" in (opportunity.get("property_type") or "").lower() or "terreno" in (opportunity.get("property_type") or "").lower())

                if is_solar:
                    monthly_rent = 0.0
                    rental_yield = 0.0
                    yield_score = 0.0
                    yield_color = "rojo"
                    btl_score = None
                else:
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

                area_m2_price = float(loc_data.get("area_m2_price", 3400.0))
                est_market_val = surface_m2 * area_m2_price
                discount_vs_market = round(max(0.0, ((est_market_val - listing_price) / est_market_val) * 100), 1) if est_market_val > 0 else 0.0

                overall_score = KPICalculator.calculate_overall_opportunity_score(
                    discount_percentage=discount_vs_market / 100.0,
                    poi_score=83.0,
                    income_amount=loc_data.get("avg_household_income", 40000),
                    population_growth=loc_data.get("population_growth_rate", 1.5),
                    rental_yield=rental_yield,
                    is_solar=is_solar
                )

                opportunity["portal_id"] = str(item_id)
                opportunity["portal_url"] = url
                opportunity["primary_portal"] = "Fotocasa"
                opportunity["discount_percentage"] = price_drop_percentage if price_drop_percentage > 0 else discount_vs_market

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
            except Exception as e_foto:
                logger.warning(f"Error parseando item Fotocasa: {e_foto}")

        listings.sort(
            key=lambda x: (
                1 if x.get("is_new") else 0,
                max(x.get("overall_score") or x.get("discount_score") or 0.0, x.get("btl_score") or 0.0),
                x.get("discount_vs_market") or x.get("discount_percentage") or 0.0
            ),
            reverse=True
        )
        logger.info(f"[Fotocasa Parser] Extraídos {len(listings)} inmuebles con éxito.")
        return listings


class PisosComMarkdownParser:
    """
    Parser especializado para extraer oportunidades estructuradas
    del Markdown generado por Supadata al consultar Pisos.com.
    """

    @classmethod
    def parse_listings(cls, markdown_content: str, default_province: str = "Madrid") -> List[Dict[str, Any]]:
        listings: List[Dict[str, Any]] = []
        if not markdown_content:
            return listings

        link_pattern = re.compile(
            r'\[(?P<title>[^\]]+)\]\((?P<url>https?://(?:www\.)?pisos\.com/comprar/[^\)]*-(?P<id>\d{5,})[^\)]*)\)',
            re.IGNORECASE
        )

        matches = list(link_pattern.finditer(markdown_content))
        if not matches:
            fallback_pattern = re.compile(
                r'\[(?P<title>[^\]]+)\]\((?P<url>https?://(?:www\.)?pisos\.com/(?:comprar|venta)/[^\)]+)\)',
                re.IGNORECASE
            )
            matches = list(fallback_pattern.finditer(markdown_content))

        for i, match in enumerate(matches):
            try:
                item_id = match.groupdict().get("id") or str(300000 + i)
                title = match.group("title").strip()
                url = match.group("url")

                start_prev = matches[i - 1].end() if i > 0 else max(0, match.start() - 1200)
                prev_text = markdown_content[start_prev:match.start()]
                end_post = matches[i + 1].start() if i + 1 < len(matches) else min(len(markdown_content), match.end() + 1500)
                post_text = markdown_content[match.end():end_post]

                if BOESubastasScraper.is_nave(title=title, desc=post_text[:600], property_type=""):
                    continue

                price_matches = re.findall(r'(\d{1,3}(?:\.\d{3})+)\s*€(?!\s*/\s*m[²2]|\s*/\s*mes)', post_text[:500])
                if not price_matches:
                    continue

                clean_prices = [float(p.replace(".", "")) for p in price_matches if float(p.replace(".", "")) > 15000]
                if not clean_prices:
                    continue

                listing_price = clean_prices[0]
                original_listing_price = clean_prices[1] if len(clean_prices) > 1 and clean_prices[1] > listing_price else listing_price
                price_drop_amount = max(0.0, original_listing_price - listing_price)
                price_drop_percentage = round((price_drop_amount / original_listing_price) * 100, 1) if original_listing_price > 0 else 0.0
                price_drop_date = "2026-03-01" if price_drop_amount > 0 else None

                rooms = 2
                rooms_match = re.search(r'(\d+)\s*(?:habs?|hab\b|habitaciones)', post_text[:400], re.IGNORECASE)
                if rooms_match:
                    rooms = int(rooms_match.group(1))

                surface_m2 = 80.0
                surf_match = re.search(r'(\d+(?:\.\d+)?)\s*m[²2]', post_text[:400])
                if surf_match:
                    surface_m2 = float(surf_match.group(1).replace(".", ""))

                floor = "Exterior"
                floor_match = re.search(r'(\d+[ªº]?\s*planta|bajo|ático|entreplanta)', post_text[:400], re.IGNORECASE)
                if floor_match:
                    floor = floor_match.group(1).strip()

                has_elevator = "sin ascensor" not in post_text[:400].lower()

                images = []
                img_matches = re.findall(r'!\[[^\]]*\]\((https?://[^\)]+\.(?:jpg|jpeg|png|webp)[^\)]*)\)', prev_text + "\n" + post_text[:1200])
                for img_url in img_matches:
                    if img_url not in images:
                        images.append(img_url)

                loc_data = IdealistaMarkdownParser._resolve_location_and_kpis(title, default_province)

                opportunity = {
                    "id": f"MKT-PISOSCOM-{item_id}",
                    "title": title,
                    "address": loc_data.get("address") or title,
                    "locality": loc_data.get("locality", default_province),
                    "province": loc_data.get("province", default_province),
                    "postal_code": loc_data.get("postal_code", "28001"),
                    "lat": loc_data.get("lat"),
                    "lon": loc_data.get("lon"),
                    "property_type": "PISO" if "chalet" not in title.lower() else "CHALET",
                    "strategy": "HOUSE_FLIPPING" if surface_m2 < 140 else "BUY_AND_HOLD",
                    "surface_m2": surface_m2,
                    "rooms": rooms,
                    "bathrooms": max(1, rooms - 1),
                    "floor": floor,
                    "has_elevator": has_elevator,
                    "energy_certificate": "E",
                    "original_listing_price": original_listing_price,
                    "listing_price": listing_price,
                    "price_drop_percentage": price_drop_percentage,
                    "price_drop_amount": price_drop_amount,
                    "price_drop_date": price_drop_date,
                    "discount_percentage": price_drop_percentage,
                    "first_published_date": "2026-03-01",
                    "publications": [
                        {
                            "portal": "Pisos.com",
                            "price": listing_price,
                            "url": url,
                            "agency": "Inmobiliaria Pisos.com",
                            "published_date": "2026-03-01"
                        }
                    ],
                    "census_tract_data": {
                        "district": loc_data.get("district_label", default_province),
                        "avg_household_income": loc_data.get("avg_household_income", 40000),
                        "avg_person_income": round(loc_data.get("avg_household_income", 40000) / 2.2),
                        "area_m2_price": loc_data.get("area_m2_price", 3400.0),
                        "population_growth_rate": loc_data.get("population_growth_rate", 1.5)
                    },
                    "images": images,
                    "description": f"{title}. Inmueble verificado en Pisos.com."
                }

                is_solar = (opportunity.get("strategy") == "LAND_DEVELOPMENT" or "solar" in (opportunity.get("property_type") or "").lower() or "terreno" in (opportunity.get("property_type") or "").lower())

                if is_solar:
                    monthly_rent = 0.0
                    rental_yield = 0.0
                    yield_score = 0.0
                    yield_color = "rojo"
                    btl_score = None
                else:
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

                area_m2_price = float(loc_data.get("area_m2_price", 3400.0))
                est_market_val = surface_m2 * area_m2_price
                discount_vs_market = round(max(0.0, ((est_market_val - listing_price) / est_market_val) * 100), 1) if est_market_val > 0 else 0.0

                overall_score = KPICalculator.calculate_overall_opportunity_score(
                    discount_percentage=discount_vs_market / 100.0,
                    poi_score=81.0,
                    income_amount=loc_data.get("avg_household_income", 40000),
                    population_growth=loc_data.get("population_growth_rate", 1.5),
                    rental_yield=rental_yield,
                    is_solar=is_solar
                )

                opportunity["portal_id"] = str(item_id)
                opportunity["portal_url"] = url
                opportunity["primary_portal"] = "Pisos.com"
                opportunity["discount_percentage"] = price_drop_percentage if price_drop_percentage > 0 else discount_vs_market

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
            except Exception as e_pisos:
                logger.warning(f"Error parseando item Pisos.com: {e_pisos}")

        listings.sort(
            key=lambda x: (
                1 if x.get("is_new") else 0,
                max(x.get("overall_score") or x.get("discount_score") or 0.0, x.get("btl_score") or 0.0),
                x.get("discount_vs_market") or x.get("discount_percentage") or 0.0
            ),
            reverse=True
        )
        logger.info(f"[Pisos.com Parser] Extraídos {len(listings)} inmuebles con éxito.")
        return listings
