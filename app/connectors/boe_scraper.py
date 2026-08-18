import httpx
import re
import logging
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class BOESubastasScraper:
    """
    Scraper & Parser para el Portal de Subastas del BOE (Boletín Oficial del Estado).
    Soporta extracción de Subastas Judiciales, Notariales y Administrativas.
    """
    BASE_URL = "https://subastas.boe.es"
    SEARCH_URL = "https://subastas.boe.es/subastas_buscar.php"

    def __init__(self, timeout: float = 15.0):
        self.client = httpx.Client(
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            timeout=timeout,
            follow_redirects=True
        )

    def extract_cadastral_reference(self, text: str) -> Optional[str]:
        """
        Extrae la referencia catastral (14 o 20 caracteres alfanuméricos) del texto de la subasta.
        Ejemplo RefCat: 1234567VK3813S0001WX o 1234567VK3813S
        """
        if not text:
            return None
        # Expresión regular para referencias catastrales españolas (14 o 20 dígitos/letras)
        pattern = r'\b([0-9]{7}[A-Z]{2}[0-9]{4}[A-Z0-9]{1,7})\b'
        match = re.search(pattern, text.upper())
        if match:
            return match.group(1)
        return None

    def parse_auction_detail(self, auction_id: str, html_content: str) -> Dict[str, Any]:
        """
        Parsea el HTML de la página de detalles de un lote/subasta del BOE.
        """
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Extracción de campos
        data = {
            "id_subasta": auction_id,
            "title": "",
            "description": "",
            "property_type": "Vivienda", # Por defecto residencial
            "province": "",
            "locality": "",
            "address": "",
            "appraisal_value": 0.0,
            "starting_bid": 0.0,
            "deposit_amount": 0.0,
            "refcat": None,
            "status": "EJECUCION",
            "auction_start_date": None,
            "auction_end_date": None
        }

        # Parsear título y descripción
        title_tag = soup.find("h3", class_="subasta_titulo") or soup.find("h2")
        if title_tag:
            data["title"] = title_tag.get_text(strip=True)

        # Buscar tablas de información alfanumérica
        tables = soup.find_all("table")
        full_text = ""
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cols = row.find_all(["th", "td"])
                if len(cols) == 2:
                    key = cols[0].get_text(strip=True).lower()
                    val = cols[1].get_text(strip=True)
                    full_text += f" {key} {val}"

                    if "valor de tasación" in key:
                        data["appraisal_value"] = self._parse_amount(val)
                    elif "importe del depósito" in key:
                        data["deposit_amount"] = self._parse_amount(val)
                    elif "puja mínima" in key or "tramo entre pujas" in key or "valor subasta" in key:
                        data["starting_bid"] = self._parse_amount(val)
                    elif "provincia" in key:
                        data["province"] = val
                    elif "localidad" in key or "municipio" in key:
                        data["locality"] = val
                    elif "dirección" in key or "ubicación" in key:
                        data["address"] = val
                    elif "tipo de bien" in key:
                        if "solar" in val.lower() or "terreno" in val.lower() or "parcela" in val.lower() or "suelo" in val.lower():
                            data["property_type"] = "Solar"
                        else:
                            data["property_type"] = "Vivienda"

        # Buscar RefCat en el texto completo
        data["description"] = full_text.strip()
        data["refcat"] = self.extract_cadastral_reference(full_text)

        # Si el precio de salida sigue en 0, usar el valor de tasación como referencia
        if data["starting_bid"] == 0.0 and data["appraisal_value"] > 0.0:
            data["starting_bid"] = data["appraisal_value"] * 0.5 # Estimación habitual de salida del BOE

        return data

    def fetch_mock_auctions(self) -> List[Dict[str, Any]]:
        """
        Retorna datos estructurados reales/simulados para pruebas y poblamiento inicial
        de subastas del BOE en ubicaciones clave de España (Madrid, Barcelona, Málaga, Valencia).
        """
        return [
            {
                "id_subasta": "SUB-JA-2026-100291",
                "source": "BOE_SUBASTAS",
                "title": "Subasta judicial de Vivienda Residencial en Madrid Capital (Alcalá)",
                "description": "Piso residencial para reformar en Calle de Alcalá 120, 2ºA, 28009 Madrid. RefCat 8812301VK4781S0001AB. Excelente oportunidad de flipping en pleno Barrio de Salamanca.",
                "property_type": "Vivienda",
                "province": "Madrid",
                "locality": "Madrid",
                "address": "Calle de Alcalá 120, 2º A, 28009",
                "appraisal_value": 361000.0,
                "starting_bid": 190000.0, # ~47% de descuento
                "deposit_amount": 17500.0,
                "refcat": "MADRID_8812301VK4781S0001AB",
                "status": "EJECUCION",
                "lat": 40.4285,
                "lon": -3.6701,
                "images": [
                    "https://images.unsplash.com/photo-1560518883-ce09059eeffa?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1512917774080-9991f1c4c750?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=800&q=80"
                ]
            },
            {
                "id_subasta": "SUB-JA-2026-100292",
                "source": "BOE_SUBASTAS",
                "title": "Subasta de Parcelas de Suelo Urbano en Málaga (Estepona)",
                "description": "Solar edificable de 1.200 m2 en Estepona, Málaga. Edificabilidad 0,8. RefCat 2905101UF0123S0001CD.",
                "property_type": "Solar",
                "province": "Málaga",
                "locality": "Estepona",
                "address": "Avenida del Litoral 45, Sector SUP-C13, 29680",
                "appraisal_value": 621000.0,
                "starting_bid": 210000.0, # ~66% de descuento
                "deposit_amount": 21000.0,
                "refcat": "MALAGA_2905101UF0123S0001CD",
                "status": "EJECUCION",
                "lat": 36.4258,
                "lon": -5.1450,
                "zoning_classification": "Suelo Urbano Consolidado (SUC-R1)",
                "urbanization_status": "Aprobación Provisional PGOU / Plan Parcial en Tramitación (Ejecución 2026-2027)",
                "buildability_ratio": "0.80 m²t/m²s (960 m² edificables)",
                "permitted_uses": "Residencial Colectivo / Unifamiliar (B+2) + Comercial en Planta Baja",
                "images": [
                    "https://images.unsplash.com/photo-1500382017468-9049fed747ef?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1524813686514-a57563d77965?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=800&q=80"
                ]
            },
            {
                "id_subasta": "SUB-JA-2026-100293",
                "source": "BOE_SUBASTAS",
                "title": "Subasta de Piso Residencial en Valencia (Ciutat Vella)",
                "description": "Piso de 85 m2 en Calle Quart 12, 3ºB, 46001 Valencia. RefCat 4690001YJ2731S0002EF",
                "property_type": "Vivienda",
                "province": "Valencia",
                "locality": "Valencia",
                "address": "Calle Quart 12, 3º B, 46001",
                "appraisal_value": 187000.0,
                "starting_bid": 130000.0, # ~30.4% de descuento
                "deposit_amount": 12000.0,
                "refcat": "VALENCIA_4690001YJ2731S0002EF",
                "status": "EJECUCION",
                "lat": 39.4752,
                "lon": -0.3801,
                "images": [
                    "https://images.unsplash.com/photo-1502672260266-1c1ef2d93688?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1560448204-e02f11c3d0e2?auto=format&fit=crop&w=800&q=80"
                ]
            },
            {
                "id_subasta": "SUB-JA-2026-100294",
                "source": "BOE_SUBASTAS",
                "title": "Subasta de Vivienda en Barcelona (Eixample)",
                "description": "Piso de 88 m2 en Carrer de Mallorca 240, 1º 2ª, 08008 Barcelona. RefCat 0800101BA1234S0001GH",
                "property_type": "Vivienda",
                "province": "Barcelona",
                "locality": "Barcelona",
                "address": "Carrer de Mallorca 240, 1º 2ª, 08008",
                "appraisal_value": 308000.0,
                "starting_bid": 260000.0, # ~15.5% de descuento
                "deposit_amount": 15000.0,
                "refcat": "BARCELONA_0800101BA1234S0001GH",
                "status": "EJECUCION",
                "lat": 41.3912,
                "lon": 2.1623,
                "images": [
                    "https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1600607687939-ce8a6c25118c?auto=format&fit=crop&w=800&q=80"
                ]
            },
            {
                "id_subasta": "SUB-JA-2026-100295",
                "source": "BOE_SUBASTAS",
                "title": "Subasta de Inmueble en Sevilla (Nervión)",
                "description": "Piso de 90 m2 en Avenida de San Francisco Javier 18, 41018 Sevilla.",
                "property_type": "Vivienda",
                "province": "Sevilla",
                "locality": "Sevilla",
                "address": "Avda. San Francisco Javier 18, 4º C, 41018",
                "appraisal_value": 189000.0,
                "starting_bid": 165000.0, # ~12.7% de descuento
                "deposit_amount": 9000.0,
                "refcat": "SEVILLA_4100101SE4321S0001IJ",
                "status": "EJECUCION",
                "lat": 37.3821,
                "lon": -5.9752,
                "images": [
                    "https://images.unsplash.com/photo-1580587771525-78b9dba3b914?auto=format&fit=crop&w=800&q=80"
                ]
            },
            {
                "id_subasta": "SUB-JA-2026-100296",
                "source": "BOE_SUBASTAS",
                "title": "Subasta de Vivienda en Alicante (Playa de San Juan)",
                "description": "Apartamento de 105 m2 cerca de la costa en Avenida de Niza 30, Alicante.",
                "property_type": "Vivienda",
                "province": "Alicante",
                "locality": "Alicante",
                "address": "Avenida de Niza 30, Bloque B, 03540",
                "appraisal_value": 204750.0,
                "starting_bid": 155000.0, # ~24.3% de descuento
                "deposit_amount": 8000.0,
                "refcat": "ALICANTE_0300101AL9876S0001KL",
                "status": "EJECUCION",
                "lat": 38.3622,
                "lon": -0.4201,
                "images": [
                    "https://images.unsplash.com/photo-1512915922686-57c11dde9b6b?auto=format&fit=crop&w=800&q=80"
                ]
            },
            {
                "id_subasta": "SUB-JA-2026-100297",
                "source": "BOE_SUBASTAS",
                "title": "Subasta de Solar Urbano en Zaragoza (Actur)",
                "description": "Parcela residencial de 800 m2 en Calle Poeta Luciano Gracia 5, Zaragoza.",
                "property_type": "Solar",
                "province": "Zaragoza",
                "locality": "Zaragoza",
                "address": "Calle Poeta Luciano Gracia 5, 50018",
                "appraisal_value": 320000.0,
                "starting_bid": 240000.0, # ~25.0% de descuento
                "deposit_amount": 12000.0,
                "refcat": "ZARAGOZA_5000101ZA5555S0001MN",
                "status": "EJECUCION",
                "lat": 41.6702,
                "lon": -0.8872,
                "zoning_classification": "Suelo Urbano Consolidado Residencial (SUC)",
                "urbanization_status": "Consolidado - Edificación Directa con Licencia Municipal",
                "buildability_ratio": "1.25 m²t/m²s (1.000 m² edificables)",
                "permitted_uses": "Residencial Colectivo / Unifamiliar en Hilera (Capacidad: 10 Viviendas)",
                "images": [
                    "https://images.unsplash.com/photo-1500382017468-9049fed747ef?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1600585154526-990dced4db0d?auto=format&fit=crop&w=800&q=80"
                ]
            },
            {
                "id_subasta": "SUB-JA-2026-100298",
                "source": "BOE_SUBASTAS",
                "title": "Subasta de Piso en Bilbao (Indautxu)",
                "description": "Piso de 82 m2 en Alameda de Urquijo 45, Bilbao.",
                "property_type": "Vivienda",
                "province": "Bizkaia",
                "locality": "Bilbao",
                "address": "Alameda de Urquijo 45, 2º Dcha, 48011",
                "appraisal_value": 254200.0,
                "starting_bid": 215000.0, # ~15.4% de descuento
                "deposit_amount": 11000.0,
                "refcat": "BIZKAIA_4800101BI7777S0001OP",
                "status": "EJECUCION",
                "lat": 43.2612,
                "lon": -2.9381,
                "images": [
                    "https://images.unsplash.com/photo-1600566753376-12c8ab7fb75b?auto=format&fit=crop&w=800&q=80"
                ]
            }
        ]

    def _parse_amount(self, text: str) -> float:
        """Convierte cadenas monetarias españolas ("125.000,50 €") a float."""
        try:
            clean = text.replace("€", "").replace(".", "").replace(" ", "").strip()
            clean = clean.replace(",", ".")
            return float(clean)
        except Exception:
            return 0.0
