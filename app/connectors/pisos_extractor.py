"""
Extractor de Ubicación y Geodatos Especializado para Pisos.com.
Extrae coordenadas exactas (lat/lon), dirección de calle, barrio, distrito, municipio
y código postal a partir de la URL, el HTML y el control de mapa interactivo de Pisos.com.
"""

import re
import html as htmllib
import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Mapeo exhaustivo de municipios y barrios de Pisos.com a Códigos Postales
MUNICIPALITY_NEIGHBORHOOD_TO_CP: Dict[str, str] = {
    # Madrid Capital y Municipios
    "puerta del angel": "28011",
    "puerta del ángel": "28011",
    "madrid rio": "28011",
    "madrid río": "28011",
    "avenida de portugal": "28011",
    "latina": "28011",
    "pinto": "28320",
    "valdemoro": "28340",
    "alcala de henares": "28802",
    "alcalá de henares": "28802",
    "puerta de madrid": "28802",
    "el juncal": "28802",
    "reyes catolicos": "28802",
    "reyes católicos": "28802",
    "la garena": "28806",
    "torrejon de ardoz": "28850",
    "torrejón de ardoz": "28850",
    "coslada": "28821",
    "san fernando de henares": "28830",
    "getafe": "28901",
    "leganes": "28911",
    "leganés": "28911",
    "alcorcon": "28921",
    "alcorcón": "28921",
    "mostoles": "28931",
    "móstoles": "28931",
    "fuenlabrada": "28941",
    "parla": "28981",
    "alcobendas": "28100",
    "san sebastian de los reyes": "28701",
    "san sebastián de los reyes": "28701",
    "majadahonda": "28220",
    "las rozas": "28231",
    "pozuelo de alarcon": "28223",
    "pozuelo de alarcón": "28223",
    "aravaca": "28023",
    "valdemarin": "28023",
    "boadilla del monte": "28660",
    "alameda de osuna": "28042",
    "santa eugenia": "28031",
    "villa de vallecas": "28031",
    "chopera": "28045",
    "cuatro caminos": "28020",
    "ciudad 70": "28821",
    "valdezarza": "28039",
    "gaztambide": "28015",
    "arapiles": "28015",
    "somosaguas": "28223",
    "la cabrera": "28751",
    "pozuelo del rey": "28813",
    "sol": "28013",

    # Alicante y Costa Blanca
    "alicante": "03001",
    "alacant": "03001",
    "centro tradicional": "03001",
    "mercado": "03004",
    "casco antiguo": "03002",
    "san blas": "03005",
    "playa san juan": "03540",
    "playas playa de san juan": "03540",
    "cabo de la huerta": "03540",
    "sant joan d'alacant": "03550",
    "sant joan": "03550",
    "san juan de alicante": "03550",
    "mutxamel": "03110",
    "elche": "03201",
    "elx": "03201",
    "campello": "03560",
    "el campello": "03560",
    "cabo roig": "03189",
    "la zenia": "03189",
    "alfas del pi": "03580",
    "calpe": "03710",

    # Valencia
    "ruzafa": "46006",
    "russafa": "46006",
    "ciutat vella": "46001",
    "el carme": "46001",
    "cabanyal": "46011",
    "el grau": "46024",
    "campanar": "46015",
    "benimaclet": "46020",
    "patraix": "46018",
    "malilla": "46026",
    "sant marcelli": "46017",
    "torrente": "46900",
    "torrent": "46900",
    "paterna": "46980",
    "aldaia": "46960",
    "massamagrell": "46130",
    "san antonio de benageber": "46184",
    "gandia": "46700",
    "playa de gandia": "46730",
    "xeresa": "46790",
    "godella": "46110",

    # Barcelona
    "el raval": "08001",
    "la guineueta": "08042",
    "eixample": "08007",
    "gracia": "08012",
    "gràcia": "08012",
    "poblenou": "08005",
    "sarria": "08017",
    "sarrià": "08017",
    "sant gervasi": "08006",
    "badalona": "08911",
    "hospitalet de llobregat": "08901",
    "l'hospitalet": "08901",
    "sant cugat": "08172",
    "sabadell": "08201",
    "terrassa": "08221",
    "sant pere de ribes": "08810",
    "sant pere de vilamajor": "08458",
    "llinars del valles": "08450",
    "suria": "08260",
    "begues": "08859",
    "llica d'amunt": "08186",
    "vic": "08500",
    "palau-solita": "08184"
}


class PisosExtractor:
    """Extractor robusto para páginas y anuncios de Pisos.com."""

    @staticmethod
    def extract_postal_code_from_url_or_text(text: str) -> Optional[str]:
        """
        Extrae código postal español (01000-52999) permitiendo delimitadores no numéricos
        (como 'el_juncal28802-666' o 'mercado03004-658').
        """
        if not text:
            return None
        # Busca 5 dígitos de CP español no rodeados de otros dígitos
        matches = re.findall(r'(?:^|[^0-9])((?:0[1-9]|[1-4][0-9]|5[0-2])\d{3})(?:[^0-9]|$)', text)
        if matches:
            # Excluir años como 2024, 2025, 2026 si coincidiesen por error
            for cp in matches:
                if cp not in ("2023", "2024", "2025", "2026"):
                    return cp
        return None

    @classmethod
    def extract_location_info_from_html(cls, html: str, url: str = "") -> Dict[str, Any]:
        """
        Extrae datos detallados de localización del anuncio de Pisos.com:
        - latitud y longitud (del mapa data-params o imagen de caché del mapa)
        - calle / dirección concreta
        - barrio y distrito
        - municipio / localidad
        - código postal
        """
        result = {
            "latitude": None,
            "longitude": None,
            "street_address": "",
            "neighborhood": "",
            "district": "",
            "locality": "",
            "province": "",
            "postal_code": "",
            "full_address": ""
        }

        # 1. Extraer latitud y longitud del mapa interactivo
        # Caso A: data-params="latitude=40.4733842&longitude=-3.3798573..."
        m_params = re.search(r'class=[\"\']location[\"\'][^>]*data-params=[\"\']([^\"\']+)[\"\']', html, re.I)
        if not m_params:
            m_params = re.search(r'data-params=[\"\']([^\"\']*latitude[^\"\']*)[\"\']', html, re.I)

        if m_params:
            raw_params = htmllib.unescape(m_params.group(1))
            m_lat = re.search(r'latitude=([0-9\.\-]+)', raw_params)
            m_lon = re.search(r'longitude=([0-9\.\-]+)', raw_params)
            if m_lat and m_lon:
                try:
                    result["latitude"] = float(m_lat.group(1))
                    result["longitude"] = float(m_lon.group(1))
                except ValueError:
                    pass

        # Caso B: URL de imagen del mapa: https://map.imghs.net/.../2_350_40.4733842@-3.3798573_0_1.gif
        if result["latitude"] is None:
            m_map_img = re.search(r'map\.imghs\.net[^\'\"]*?([0-9\.\-]+)@([0-9\.\-]+)', html)
            if m_map_img:
                try:
                    result["latitude"] = float(m_map_img.group(1))
                    result["longitude"] = float(m_map_img.group(2))
                except ValueError:
                    pass

        # 2. Extraer dirección de calle (del H1 o bloque superior del mapa)
        m_h1 = re.search(r'<h1[^>]*>([^<]+)</h1>', html, re.I)
        if m_h1:
            h1_text = htmllib.unescape(m_h1.group(1)).strip()
            # "Piso en venta en Calle de Hernán Cortés" -> "Calle de Hernán Cortés"
            street_match = re.search(r'(?:en venta en|en alquiler en|en)\s+(.+)$', h1_text, re.I)
            if street_match:
                result["street_address"] = street_match.group(1).strip()
            else:
                result["street_address"] = h1_text

        # 3. Extraer barrio, distrito y municipio del subtítulo adyacente al mapa
        # <p>Puerta de Madrid, El Juncal (Distrito Reyes Católicos. Alcalá de Henares)</p>
        m_sub = re.search(r'</h1>\s*<p[^>]*>([^<]+)</p>', html, re.I)
        subtitle_text = ""
        if m_sub:
            subtitle_text = htmllib.unescape(m_sub.group(1)).strip()
        else:
            # Buscar en bloque de localización
            m_loc_block = re.search(r'class=[\"\']location__ask-address[\"\'][\s\S]*?<span[^>]*>([^<]+)</span>', html, re.I)
            if m_loc_block:
                subtitle_text = htmllib.unescape(m_loc_block.group(1)).strip()

        if subtitle_text:
            # Parsear estructura: "Barrio (Distrito X. Municipio - Provincia)"
            m_paren = re.search(r'^(.*?)\s*\((.*?)\)$', subtitle_text)
            if m_paren:
                result["neighborhood"] = m_paren.group(1).strip()
                inside_paren = m_paren.group(2).strip()
                # Separar distrito y municipio
                if "." in inside_paren:
                    parts = inside_paren.split(".", 1)
                    result["district"] = parts[0].replace("Distrito", "").strip()
                    loc_prov = parts[1].strip()
                else:
                    loc_prov = inside_paren

                if " - " in loc_prov:
                    lp_parts = loc_prov.split(" - ")
                    result["locality"] = lp_parts[0].strip()
                    result["province"] = lp_parts[1].strip()
                else:
                    result["locality"] = loc_prov
            else:
                result["locality"] = subtitle_text

        # 4. Resolver Código Postal
        # Prioridad 1: Del URL de pisos.com
        cp = cls.extract_postal_code_from_url_or_text(url)
        # Prioridad 2: Del HTML
        if not cp:
            cp = cls.extract_postal_code_from_url_or_text(subtitle_text)

        # Prioridad 3: De nuestro diccionario de barrios/municipios
        if not cp:
            combined = f"{url} {subtitle_text} {result['neighborhood']} {result['locality']}".lower()
            normalized = combined.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
            for name, assigned_cp in MUNICIPALITY_NEIGHBORHOOD_TO_CP.items():
                name_norm = name.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
                if name_norm in normalized:
                    cp = assigned_cp
                    break

        result["postal_code"] = cp or ""

        # 5. Si faltaba municipio o provincia, inferirlo por CP
        if cp:
            pref = cp[:2]
            prov_map = {
                "28": "Madrid", "08": "Barcelona", "46": "Valencia", "41": "Sevilla",
                "29": "Málaga", "03": "Alicante", "50": "Zaragoza", "30": "Murcia"
            }
            if not result["province"] and pref in prov_map:
                result["province"] = prov_map[pref]
            if not result["locality"]:
                result["locality"] = result["province"]

        # 6. Construir full_address cohesiva
        parts = []
        if result["street_address"]: parts.append(result["street_address"])
        if result["neighborhood"] and result["neighborhood"] not in result["street_address"]: parts.append(result["neighborhood"])
        if result["locality"]: parts.append(result["locality"])
        if result["postal_code"]: parts.append(f"({result['postal_code']})")
        result["full_address"] = ", ".join(parts)

        return result
