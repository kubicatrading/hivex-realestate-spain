import httpx
import re
import logging
import asyncio
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

SPANISH_NUMBER_WORDS = {
    'un': 1, 'uno': 1, 'una': 1, 'dos': 2, 'tres': 3, 'cuatro': 4, 'cinco': 5,
    'seis': 6, 'siete': 7, 'ocho': 8, 'nueve': 9, 'diez': 10, 'once': 11, 'doce': 12,
    'trece': 13, 'catorce': 14, 'quince': 15, 'dieciséis': 16, 'dieciseis': 16,
    'diecisiete': 17, 'dieciocho': 18, 'diecinueve': 19, 'veinte': 20, 'veintiuno': 21,
    'veintidós': 22, 'veintidos': 22, 'veintitrés': 23, 'veintitres': 23,
    'veinticuatro': 24, 'veinticinco': 25, 'veintiséis': 26, 'veintisiete': 27,
    'veintiocho': 28, 'veintinueve': 29, 'treinta': 30, 'cuarenta': 40,
    'cincuenta': 50, 'sesenta': 60, 'setenta': 70, 'ochenta': 80, 'noventa': 90,
    'cien': 100, 'ciento': 100, 'doscientos': 200, 'trescientos': 300,
    'cuatrocientos': 400, 'quinientos': 500, 'seiscientos': 600,
    'setecientos': 700, 'ochocientos': 800, 'novecientos': 900
}

def parse_spanish_written_number(words_str: str) -> Optional[float]:
    if not words_str:
        return None
    tokens = words_str.lower().replace(' y ', ' ').split()
    total = 0
    current = 0
    for t in tokens:
        if t in SPANISH_NUMBER_WORDS:
            val = SPANISH_NUMBER_WORDS[t]
            if val == 100 and current > 0 and current < 10:
                current *= 100
            else:
                current += val
    return float(total + current) if (total + current) > 0 else None

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

    def extract_idufir_cru(self, text: str) -> Optional[str]:
        """
        Extrae el IDUFIR / CRU (Código Registro Único de 14 dígitos) del texto de la subasta o certificado registral.
        """
        if not text:
            return None
        patterns = [
            r'(?:idufir|cru|código\s+registral|codigo\s+registral|c\.r\.u\.)\s*:?\s*(\d{14})',
            r'\b(\d{14})\b'
        ]
        for pat in patterns:
            m = re.search(pat, text.lower())
            if m:
                return m.group(1)
        return None

    @staticmethod
    def parse_spanish_number(val_str: str) -> Optional[float]:
        """
        Parsea cadenas de números considerando correctamente punto o coma como separador decimal
        o de millar. (Ej: '92.35' -> 92.35, '92,35' -> 92.35, '1.250,50' -> 1250.50)
        """
        if not val_str:
            return None
        s = val_str.strip()
        try:
            # Caso 1: Tiene punto y coma (e.g. 1.250,50)
            if '.' in s and ',' in s:
                if s.rfind(',') > s.rfind('.'):
                    clean = s.replace('.', '').replace(',', '.')
                else:
                    clean = s.replace(',', '')
                return float(clean)
            # Caso 2: Tiene sólo coma (e.g. 92,35 o 0,783 ha)
            if ',' in s and '.' not in s:
                parts = s.split(',')
                if len(parts) == 2:
                    if parts[0] == '0' or len(parts[1]) in (1, 2, 3):
                        clean = s.replace(',', '.')
                    else:
                        clean = s.replace(',', '')
                else:
                    clean = s.replace(',', '')
                return float(clean)
            # Caso 3: Tiene sólo punto (e.g. 92.35 o 1.250)
            if '.' in s and ',' not in s:
                parts = s.split('.')
                if len(parts) == 2 and len(parts[1]) in (1, 2):
                    clean = s # Mantener el punto decimal!
                elif len(parts) == 2 and len(parts[1]) == 3 and len(parts[0]) <= 2:
                    clean = s.replace('.', '')
                else:
                    clean = s
                return float(clean)
            return float(s)
        except Exception:
            return None

    def extract_ownership_percentage(self, text: str) -> float:
        """
        Extrae el porcentaje de pleno dominio o participacion subastada sin redondear (precisión matemática exacta).
        Ej: '16,66667% del pleno dominio' -> 16.66667, '100% del pleno dominio' -> 100.0
        Ignora cuotas de participación en elementos comunes o gastos de portal (Propiedad Horizontal).
        """
        if not text:
            return 100.0
        text_lower = text.lower()
        
        # Eliminar menciones de cuota de participación en elementos comunes/gastos de comunidad del bloque/portal (Propiedad Horizontal)
        cleaned_text = re.sub(
            r'cuotas?\s+(?:de\s+participaci[oó]n|en\s+el\s+valor|en\s+los\s+elementos|en\s+los\s+gastos)[^%\n]*%\s*-?',
            '',
            text_lower
        )
        
        m_pct = re.search(r'(\d+(?:[\.,]\d+)?)\s*%\s*(?:del\s*)?(?:pleno\s*dominio|nuda\s*propiedad|propiedad|indiviso|titularidad|participaci[oó]n)?', cleaned_text)
        if m_pct:
            val = self.parse_spanish_number(m_pct.group(1))
            if val and 0.000001 <= val <= 100.0:
                return float(val)
        m_frac = re.search(r'\b(\d+/\d+)\b\s*(?:del\s*)?(?:pleno\s*dominio|nuda\s*propiedad|propiedad|indiviso)?', cleaned_text)
        if m_frac:
            try:
                num, denom = m_frac.group(1).split('/')
                val = (float(num) / float(denom)) * 100.0
                return float(val)
            except Exception:
                pass
        return 100.0

    def extract_liens_info(self, text: str, id_subasta: str = "") -> Dict[str, Any]:
        """
        Extrae la información de cargas/gravámenes del texto del anuncio o edicto BOE.
        """
        if not text:
            return {
                "has_liens": False,
                "status": "SIN CARGAS",
                "label": "Libre de Cargas",
                "description": "Sin cargas preferentes declaradas en la ficha oficial del BOE.",
                "color": "green",
                "badge": "🟢 LIBRE DE CARGAS"
            }
        
        t = text.lower()
        
        no_liens_patterns = [
            "sin cargas", "libre de cargas", "libre de toda carga", "sin cargas preferentes",
            "no constan cargas", "no existen cargas", "no se aprecian cargas", "cargas: ninguna",
            "cargas: sin cargas", "cargas: libre", "sin gravámenes", "libre de gravámenes"
        ]
        
        has_liens_patterns = [
            "con cargas", "hipoteca", "embargo", "afección fiscal", "anexo de cargas",
            "existencia de cargas", "cargas preferentes", "cargas y gravámenes",
            "titular de las cargas", "cancelación de cargas", "liquidación de cargas",
            "servidumbre", "usufructo", "con gravámenes"
        ]
        
        if any(pat in t for pat in no_liens_patterns):
            return {
                "has_liens": False,
                "status": "SIN CARGAS",
                "label": "Sin Cargas (Libre)",
                "description": "Inmueble declarado libre de cargas preferentes según certificación registral en edicto BOE.",
                "color": "green",
                "badge": "🟢 LIBRE DE CARGAS"
            }
            
        for pat in has_liens_patterns:
            if pat in t:
                idx = t.find(pat)
                start_snippet = max(0, idx - 20)
                end_snippet = min(len(text), idx + 180)
                snippet = text[start_snippet:end_snippet].strip()
                return {
                    "has_liens": True,
                    "status": "CON CARGAS",
                    "label": "Con Cargas / Gravámenes",
                    "description": f"Se aprecian cargas o gravámenes en edicto BOE: \"...{snippet}...\"",
                    "color": "orange",
                    "badge": "🟠 CON CARGAS (VER EDICTO)"
                }
                
        return {
            "has_liens": False,
            "status": "SIN CARGAS",
            "label": "Sin Cargas Detectadas",
            "description": "Sin cargas preferentes explícitas en el extracto del BOE. Se recomienda verificar la certificación registral adjunta al edicto.",
            "color": "green",
            "badge": "🟢 LIBRE DE CARGAS"
        }

    def extract_land_classification(self, text: str) -> str:
        """
        Determina si el suelo/finca es RÚSTICO o URBANO.
        """
        if not text:
            return "URBANO"
        t = text.lower()
        if "rústic" in t or "rustica" in t or "agrari" in t or "suelo no urbanizable" in t or "snu" in t or "no urbanizable" in t:
            return "RÚSTICO"
        return "URBANO"

    def extract_surface_m2(self, text: str) -> Optional[float]:
        """Extrae la superficie exacta en m2 del texto del BOE, edicto o certificación registral, ignorando anejos (garaje, trastero)."""
        if not text:
            return None
        
        text_lower = text.lower()

        # 1. Búsqueda específica de superficie con números escritos en texto (Ej: 'sesenta metros noventa y cinco decímetros')
        written_pat = r'superficie\s+(?:construida|útil|registral|total)?\s*(?:de\s*)?([a-z\s]+?)\s*metros?(?:\s+([a-z\s]+?)\s*decímetros?)?'
        m_written = re.search(written_pat, text_lower)
        if m_written:
            w_m = m_written.group(1).strip() if m_written.group(1) else ''
            w_d = m_written.group(2).strip() if m_written.group(2) else ''
            val_m = parse_spanish_written_number(w_m)
            if val_m and 10.0 <= val_m <= 50000.0:
                val_d = parse_spanish_written_number(w_d) if w_d else 0.0
                return round(val_m + (val_d / 100.0 if val_d else 0.0), 2)

        # 1.5. Búsqueda de unidades agrarias/rústicas: Hectáreas (HA), Áreas y Centiáreas
        ha_patterns = [
            r'(?:superficie|extensión|cabida)?\s*(?:terreno|finca|parcela|total|registral)?\s*:?\s*(\d+(?:[\.,]\d+)?)\s*(?:ha\.?|hectárea|hectáreas|hectareas)\b',
            r'(\d+(?:[\.,]\d+)?)\s*(?:ha\.?|hectárea|hectáreas|hectareas)\b'
        ]
        for pat in ha_patterns:
            m = re.search(pat, text_lower)
            if m:
                val_ha = self.parse_spanish_number(m.group(1))
                if val_ha and val_ha > 0:
                    val_m2 = round(val_ha * 10000.0, 2)
                    if 10.0 <= val_m2 <= 50000000.0:
                        return val_m2

        areas_patterns = [
            r'(?:superficie|extensión|cabida)?\s*(?:terreno|finca|parcela|total|registral)?\s*:?\s*(\d+(?:[\.,]\d+)?)\s*(?:área|áreas|areas)\b'
        ]
        for pat in areas_patterns:
            m = re.search(pat, text_lower)
            if m:
                val_a = self.parse_spanish_number(m.group(1))
                if val_a and val_a > 0:
                    val_m2 = round(val_a * 100.0, 2)
                    if 10.0 <= val_m2 <= 50000000.0:
                        return val_m2

        # 2. Búsqueda específica de superficie de vivienda / local / inmueble principal con cifras digitales
        vivienda_patterns = [
            r'superficie\s+(?:construida|útil|registral|total)?\s*(?:de\s*)?[a-z\s]+?-\s*(\d+(?:[\.,]\d+)?)\s*m2-?',
            r'-\s*(\d+(?:[\.,]\d+)?)\s*(?:m2|m²)\s*-',
            r'vivienda(?:\s+que\s+consta\s+de|\s+de|\s+con|\s+de\s+una\s+superficie\s+de|\s+útil\s+de|\s+construida\s+de)?\s*:?\s*(\d+(?:[\.,]\d+)?)\s*(?:m2|m²|metros)',
            r'local(?:\s+comercial)?(?:\s+que\s+consta\s+de|\s+de|\s+con|\s+de\s+una\s+superficie\s+de|\s+útil\s+de|\s+construida\s+de)?\s*:?\s*(\d+(?:[\.,]\d+)?)\s*(?:m2|m²|metros)',
            r'superficie\s+(?:construida|útil|registral|total)\s*:?\s*(\d+(?:[\.,]\d+)?)\s*(?:m2|m²|metros)',
            r'piso(?:\s+de)?\s*(\d+(?:[\.,]\d+)?)\s*(?:m2|m²|metros)',
            r'ocupando\s+una\s+superficie\s+de\s*(\d+(?:[\.,]\d+)?)',
            r'cabida\s+de\s*(\d+(?:[\.,]\d+)?)\s*m'
        ]
        for pat in vivienda_patterns:
            m = re.search(pat, text_lower)
            if m:
                # Verificar que no esté en una frase dedicada a garaje/trastero
                match_start = max(0, m.start() - 30)
                prefix = text_lower[match_start:m.start()]
                if not any(annex in prefix for annex in ["garaje", "trastero", "aparcamiento", "cochera", "sótano", "anejo"]):
                    val = self.parse_spanish_number(m.group(1))
                    if val and 10.0 <= val <= 500000.0:
                        return val

        # 3. Limpiar menciones de anejos para evitar falsos positivos
        cleaned_text = re.sub(
            r'(?:garaje|trastero|aparcamiento|cochera|sótano|anejo)[^,\.\n]*(?:de\s*\d+(?:[\.,]\d+)?\s*(?:m2|m²|metros)[^,\.\n]*)?',
            '',
            text_lower
        )

        generic_patterns = [
            r'(\d+(?:[\.,]\d+)?)\s*(?:m2|m²|metros\s+cuadrados|m\.2)',
            r'extensión(?:\s+superficial|\s+de)?\s*:?\s*(\d+(?:[\.,]\d+)?)',
            r'consta\s+de\s*(\d+(?:[\.,]\d+)?)\s*m'
        ]
        for pat in generic_patterns:
            m = re.search(pat, cleaned_text)
            if m:
                val = self.parse_spanish_number(m.group(1))
                if val and 15.0 <= val <= 500000.0:
                    return val

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

                    if "valor subasta" in key or "valor de la subasta" in key:
                        data["starting_bid"] = self._parse_amount(val)
                    elif "valor de tasación" in key or "tasación" in key:
                        data["appraisal_value"] = self._parse_amount(val)
                    elif "importe del depósito" in key:
                        data["deposit_amount"] = self._parse_amount(val)
                    elif "puja mínima" in key or "puja minima" in key:
                        data["minimum_bid"] = self._parse_amount(val)
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

        # Si el valor de subasta sigue en 0, usar el valor de tasación como referencia
        if data["starting_bid"] == 0.0 and data["appraisal_value"] > 0.0:
            data["starting_bid"] = data["appraisal_value"]
        if data["appraisal_value"] == 0.0 and data["starting_bid"] > 0.0:
            data["appraisal_value"] = data["starting_bid"]

        return data

    def fetch_mock_auctions(self) -> List[Dict[str, Any]]:
        """
        Retorna lista vacía ya que está estrictamente prohibido el uso de datos simulados/mock.
        Se utilizan única y exclusivamente scraping en tiempo real de fuentes oficiales.
        """
        return []

    def geocode_address(self, address: str, locality: str, province: str) -> tuple:
        """
        Geolocaliza de forma precisa el inmueble usando la provincia y localidad en España.
        Aplica micro-desplazamiento para visualización clara de chinchetas múltiples en la misma zona.
        """
        from app.core.geo_utils import get_spanish_province_coords
        return get_spanish_province_coords(province_str=province, locality_str=locality, apply_jitter=True)

    @staticmethod
    def is_garage_or_storage(desc: str, title: str = "") -> bool:
        """
        Clasificador estricto para identificar y descartar plazas de garaje, parkings,
        trasteros, aparcamientos y participaciones indivisas de anexos.
        """
        text = f"{title or ''} {desc or ''}".lower()
        clean_desc = re.sub(r'^(urbana|rústica|rustica|finca|elemento|entidad|1/\d+|100%|pleno dominio)?\s*[\d\w\.-]*\s*[\.:,-]?\s*', '', (desc or '').lower().strip())
        
        # 1. Comprobación de si el sujeto principal de la ficha o título es un anexo
        starts_with_annex = any(clean_desc.startswith(p) for p in [
            'plaza de garaje', 'plaza de aparcamiento', 'plaza nº', 'plaza num', 'trastero',
            'garaje', 'aparcamiento', 'estacionamiento', 'cochera', 'local destinado a garaje',
            'local garaje', 'zona de estacionamiento', 'cuota indivisa de garaje',
            'una veinteava parte indivisa', 'participación indivisa', 'participacion indivisa'
        ])
        
        title_low = (title or '').lower()
        title_is_annex = any(k in title_low for k in ['plaza de garaje', 'trastero', 'aparcamiento', 'parking', 'cochera'])

        if starts_with_annex or title_is_annex:
            return True

        # 2. Si contiene palabras de garaje/trastero pero NO menciona vivienda/piso/casa/local/solar/nave
        has_annex_words = any(w in text for w in ['garaje', 'trastero', 'aparcamiento', 'estacionamiento', 'cochera', 'parking'])
        has_main_property = any(w in text for w in ['vivienda', 'piso', 'casa', 'chalet', 'dúplex', 'duplex', 'ático', 'atico', 'local comercial', 'nave industrial', 'solar', 'terreno', 'parcela'])

        if has_annex_words and not has_main_property:
            return True

        return False

    async def async_scrape_live_auctions(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Scrapea en tiempo real las subastas públicas activas directamente desde la sede electrónica del BOE en paralelo.
        Aplica control de concurrencia mediante asyncio.Semaphore y descarta automáticamente plazas de garaje y bienes no inmobiliarios.
        """
        payload = {
            "campo[0]": "SUBASTA.ORIGEN", "dato[0]": "",
            "campo[1]": "SUBASTA.AUTORIDAD", "dato[1]": "",
            "campo[2]": "SUBASTA.ESTADO.CODIGO", "dato[2]": "EJ",
            "campo[3]": "BIEN.TIPO", "dato[3]": "I",
            "page_hits": "500",
            "sort_field[0]": "SUBASTA.FECHA_FIN", "sort_order[0]": "desc",
            "accion": "Buscar"
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        try:
            async with httpx.AsyncClient(headers=headers, timeout=12.0, follow_redirects=True) as client:
                r = await client.post("https://subastas.boe.es/subastas_ava.php", data=payload)
                soup = BeautifulSoup(r.text, "html.parser")
                links = soup.find_all("a", href=lambda h: h and "detalleSubasta.php" in h)
                auction_ids = []
                for l in links:
                    m = re.search(r'idSub=([^&]+)', l.get("href", ""))
                    if m and m.group(1) not in auction_ids:
                        auction_ids.append(m.group(1))

                logger.info(f"Se han localizado {len(auction_ids)} subastas reales activas en el BOE.")

                target_ids = auction_ids[:limit] if (limit and limit > 0) else auction_ids

                # Semáforo para controlar la velocidad de peticiones y evitar sobrecargar la web del BOE
                semaphore = asyncio.Semaphore(10)

                async def fetch_one_auction(aid):
                    async with semaphore:
                        try:
                            r1 = await client.get(f"https://subastas.boe.es/detalleSubasta.php?idSub={aid}&ver=1")
                            r3 = await client.get(f"https://subastas.boe.es/detalleSubasta.php?idSub={aid}&ver=3")
                            return aid, r1.text, r3.text
                        except Exception as err:
                            logger.error(f"Error fetching subasta {aid}: {err}")
                            return aid, None, None

                tasks = [fetch_one_auction(aid) for aid in target_ids]
                fetched_data = await asyncio.gather(*tasks)

                real_auctions = []

                for aid, html_ver1, html_ver3 in fetched_data:
                    if not html_ver1 and not html_ver3:
                        continue

                    # 1. Datos del bien inmueble/solar (ver=3)
                    s3 = BeautifulSoup(html_ver3, "html.parser")
                    desc, address, locality, province, refcat = "", "", "", "", ""
                    for tr in s3.find_all("tr"):
                        tds = tr.find_all(["th", "td"])
                        if len(tds) >= 2:
                            k, v = tds[0].get_text(strip=True).lower(), tds[1].get_text(strip=True)
                            if "descripción" in k: desc = v
                            elif "dirección" in k: address = v
                            elif "localidad" in k: locality = v
                            elif "provincia" in k: province = v
                            elif "referencia catastral" in k or "catastral" in k or "ref. catastral" in k: refcat = v

                    if not refcat:
                        refcat = self.extract_cadastral_reference(html_ver3)

                    # Descartar si es únicamente plaza de garaje, trastero o bien no inmobiliario
                    if self.is_garage_or_storage(desc, f"Subasta de Inmueble en {locality} ({province})"):
                        logger.info(f"Subasta {aid} descartada por ser garaje/trastero/no inmueble: {desc[:60]}...")
                        continue

                    # 2. Datos financieros (ver=1)
                    s1 = BeautifulSoup(html_ver1, "html.parser")
                    appraisal, starting_bid, min_bid = 0.0, 0.0, 0.0
                    for tr in s1.find_all("tr"):
                        tds = tr.find_all(["th", "td"])
                        if len(tds) >= 2:
                            k, v = tds[0].get_text(strip=True).lower(), tds[1].get_text(strip=True)
                            if "valor subasta" in k or "valor de la subasta" in k:
                                starting_bid = self._parse_amount(v)
                            elif "tasación" in k or "valor de tasación" in k:
                                appraisal = self._parse_amount(v)
                            elif "puja mínima" in k or "puja minima" in k:
                                min_bid = self._parse_amount(v)

                    # Si valor subasta no vino explícito, usar tasación
                    if starting_bid == 0.0 and appraisal > 0.0:
                        starting_bid = appraisal
                    if appraisal == 0.0 and starting_bid > 0.0:
                        appraisal = starting_bid

                    # Geolocalización y ortofoto
                    lat, lon = self.geocode_address(address, locality, province)
                    images = []
                    if lat and lon:
                        d = 0.0015
                        cat_url = f"https://ovc.catastro.meh.es/Cartografia/WMS/ServidorWMS.aspx?SERVICE=WMS&SRS=EPSG:4326&REQUEST=GetMap&LAYERS=Catastro,PARCELA&STYLES=default&FORMAT=image/png&TRANSPARENT=FALSE&BBOX={lon-d},{lat-d},{lon+d},{lat+d}&WIDTH=800&HEIGHT=600"
                        images.append(cat_url)

                    ptype = "Solar" if any(w in desc_lower for w in ["solar", "terreno", "parcela", "finca rústica", "rustica", "suelo"]) else "Vivienda"

                    item = {
                        "id_subasta": aid,
                        "source": "BOE_SUBASTAS",
                        "title": f"Subasta de {ptype} en {locality} ({province})",
                        "description": desc,
                        "property_type": ptype,
                        "province": province,
                        "locality": locality,
                        "address": address if address else f"{locality}, {province}",
                        "appraisal_value": appraisal,
                        "starting_bid": starting_bid if starting_bid > 0 else (appraisal * 0.5),
                        "deposit_amount": starting_bid * 0.05 if starting_bid > 0 else (appraisal * 0.05),
                        "refcat": refcat if refcat else None,
                        "status": "EJECUCION",
                        "lat": lat,
                        "lon": lon,
                        "images": images,
                        "boe_url": f"https://subastas.boe.es/detalleSubasta.php?idSub={aid}"
                    }
                    real_auctions.append(item)

                return real_auctions
        except Exception as e:
            logger.error(f"Error realizando el scraping en tiempo real del BOE: {e}")
            return []

    def scrape_live_auctions(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Síncrono wrapper para async_scrape_live_auctions."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import nest_asyncio
                nest_asyncio.apply()
                return loop.run_until_complete(self.async_scrape_live_auctions(limit=limit))
            else:
                return loop.run_until_complete(self.async_scrape_live_auctions(limit=limit))
        except Exception:
            return asyncio.run(self.async_scrape_live_auctions(limit=limit))

    def _parse_amount(self, text: str) -> float:
        """Convierte cadenas monetarias españolas ("125.000,50 €") a float."""
        try:
            clean = text.replace("€", "").replace(".", "").replace(" ", "").strip()
            clean = clean.replace(",", ".")
            return float(clean)
        except Exception:
            return 0.0

