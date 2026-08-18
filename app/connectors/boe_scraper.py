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
                "title": "Subasta judicial de Vivienda Residencial en Madrid Capital",
                "description": "Piso residencial para reformar en Calle de Alcalá 120, Madrid. RefCat 8812301VK4781S0001AB",
                "property_type": "Vivienda",
                "province": "Madrid",
                "locality": "Madrid",
                "address": "Calle de Alcalá 120",
                "appraisal_value": 350000.0,
                "starting_bid": 190000.0, # 45.7% por debajo del mercado estimado (Oportunidad Flipping)
                "deposit_amount": 17500.0,
                "refcat": "8812301VK4781S0001AB",
                "status": "EJECUCION",
                "lat": 40.4285,
                "lon": -3.6701
            },
            {
                "id_subasta": "SUB-JA-2026-100292",
                "source": "BOE_SUBASTAS",
                "title": "Subasta de Parcelas de Suelo Urbano en Málaga (Estepona)",
                "description": "Solar edificable de 1.200 m2 en Estepona, Málaga. Edificabilidad 0,8. RefCat 2905101UF0123S0001CD",
                "property_type": "Solar",
                "province": "Málaga",
                "locality": "Estepona",
                "address": "Avenida del Litoral 45",
                "appraisal_value": 420000.0,
                "starting_bid": 210000.0, # 50% de descuento (Oportunidad Suelo/Desarrollo)
                "deposit_amount": 21000.0,
                "refcat": "2905101UF0123S0001CD",
                "status": "EJECUCION",
                "lat": 36.4258,
                "lon": -5.1450
            },
            {
                "id_subasta": "SUB-JA-2026-100293",
                "source": "BOE_SUBASTAS",
                "title": "Subasta de Piso en Valencia (Ciutat Vella)",
                "description": "Piso de 85 m2 en Calle Quart 12, Valencia. RefCat 4690001YJ2731S0002EF",
                "property_type": "Vivienda",
                "province": "Valencia",
                "locality": "Valencia",
                "address": "Calle Quart 12",
                "appraisal_value": 240000.0,
                "starting_bid": 130000.0, # ~45.8% descuento
                "deposit_amount": 12000.0,
                "refcat": "4690001YJ2731S0002EF",
                "status": "EJECUCION",
                "lat": 39.4752,
                "lon": -0.3801
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
