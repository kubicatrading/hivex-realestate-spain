import httpx
import xml.etree.ElementTree as ET
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class CatastroClient:
    """
    Cliente para la Sede Electrónica del Catastro (SEC) y Servicios OGC WFS INSPIRE.
    Permite obtener datos físicos, fiscales y geometría de parcelas catastrales en España.
    """
    INSPIRE_WFS_URL = "http://ovc.catastro.meh.es/INSPIRE/wfsCP.aspx"
    OVC_REST_URL = "http://ovc.catastro.meh.es/ovcservweb/OVCSWLocalizacionRC/OVCConsultaRC.asmx/Consulta_DNPRC"

    def __init__(self, timeout: float = 10.0):
        self.client = httpx.Client(timeout=timeout)

    @staticmethod
    def normalize_cadastral_reference(ref: str) -> str:
        """
        Normaliza errores de mecanografía frecuentes en edictos del BOE
        (ej. sustituir la letra 'O' por el dígito '0' en bloques numéricos de referencias rústicas
        como '46900AO76000440000FO' -> '46900A076000440000FO').
        """
        if not ref:
            return ""
        clean = ref.strip().upper().replace(" ", "").replace("-", "")
        
        # Corrección de referencias rústicas de 20 caracteres (Estructura: 5 dígitos INE + 1 letra sector + 12 dígitos polígono/parcela + 2 letras control)
        import re
        if len(clean) == 20 and re.match(r'^\d{5}[A-Z]', clean):
            prefix = clean[:6]  # 5 dígitos ine + 'A' sector
            polygon_parcel = clean[6:18]  # 12 caracteres numéricos
            control = clean[18:]  # 2 letras de control
            
            fixed_middle = (
                polygon_parcel
                .replace("O", "0")
                .replace("I", "1")
                .replace("L", "1")
            )
            return prefix + fixed_middle + control
            
        return clean

    def get_parcel_details(self, refcat: str) -> Dict[str, Any]:
        """
        Consulta los datos alfanuméricos y oficiales de la Sede Electrónica del Catastro (SEC) por Referencia Catastral.
        Retorna la superficie oficial y la clasificación de suelo (URBANO/RÚSTICO) directamente del Catastro.
        """
        details = {
            "refcat": refcat,
            "surface_m2": None,
            "land_use": "RESIDENCIAL",
            "land_type": self.detect_land_type_from_catastro(refcat),
            "build_year": None,
            "reference_price_m2": None, # Ref Micro si la SEC la proporciona
            "address": "España",
            "polygon_geojson": None
        }

        if not refcat:
            return details

        raw_refcat = refcat.strip().upper().replace(" ", "").replace("-", "")
        clean_refcat = self.normalize_cadastral_reference(raw_refcat)
        details["refcat"] = clean_refcat

        # Probar primero la referencia normalizada y luego la original si fuera distinta
        candidate_refs = [clean_refcat]
        if raw_refcat != clean_refcat:
            candidate_refs.append(raw_refcat)

        for target_ref in candidate_refs:
            # 1. Consulta oficial SEC REST por Referencia Catastral (20 caracteres)
            try:
                params = {"Provincia": "", "Municipio": "", "RC": target_ref}
                resp = self.client.get(self.OVC_REST_URL, params=params)
                if resp.status_code == 200:
                    details["land_type"] = self.detect_land_type_from_catastro(target_ref, resp.text)
                    surface = self._extract_surface_from_sec_xml(resp.text)
                    if surface and surface > 0:
                        details["surface_m2"] = surface
                        return details
            except Exception as e:
                logger.warning(f"Error consultando Catastro SEC REST para {target_ref}: {e}")

            # 2. Consulta WFS INSPIRE por parcela catastral (14 caracteres)
            try:
                parcel_ref = target_ref[:14] if len(target_ref) >= 14 else target_ref
                params = {
                    "service": "WFS",
                    "version": "2.0.0",
                    "request": "GetFeature",
                    "STOREDQUERY_ID": "GetParcel",
                    "refcat": parcel_ref,
                    "srsName": "EPSG:4326"
                }
                resp = self.client.get(self.INSPIRE_WFS_URL, params=params)
                if resp.status_code == 200 and "<cp:areaValue" in resp.text:
                    details["land_type"] = self.detect_land_type_from_catastro(target_ref, resp.text)
                    surface = self._extract_area_from_gml(resp.text)
                    if surface and surface > 0:
                        details["surface_m2"] = surface
            except Exception as e:
                logger.warning(f"Error consultando Catastro WFS para {target_ref}: {e}")

        return details

    def detect_land_type_from_catastro(self, refcat: str, xml_text: Optional[str] = None) -> str:
        """
        Determina estrictamente la clasificación del suelo (URBANO o RÚSTICO)
        a partir de la estructura oficial de la Referencia Catastral y los XML de Catastro.
        NO UTILIZA EXTRACTORES DE TEXTO.
        """
        if not refcat:
            return "URBANO"
        
        clean = refcat.strip().upper()
        
        # 1. Comprobar respuesta XML de Catastro si está disponible
        if xml_text:
            xml_lower = xml_text.lower()
            if "<cn>rustico" in xml_lower or "<cn>ru" in xml_lower or "<clase>rustico" in xml_lower or "<cn>agrario" in xml_lower:
                return "RÚSTICO"
            if "<cn>urbano" in xml_lower or "<cn>ur" in xml_lower or "<clase>urbano" in xml_lower:
                return "URBANO"

        # 2. Estructura oficial de la Referencia Catastral de Catastro España:
        # En parcelas rústicas (ej. 16146A019001250000GQ), el carácter 6 es 'A' (Agrario/Rústico) seguido del número de polígono y parcela
        import re
        if re.match(r'^\d{5}[A-Z]\d{8,}', clean):
            return "RÚSTICO"
            
        return "URBANO"

    def _extract_surface_from_sec_xml(self, xml_text: str) -> Optional[float]:
        """Extrae la superficie construida oficial del XML devuelto por la Sede Electrónica del Catastro."""
        try:
            root = ET.fromstring(xml_text)
            for elem in root.iter():
                tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                if tag in ["spt", "st", "suf"]:
                    if elem.text and elem.text.strip():
                        val = float(elem.text.strip().replace(",", "."))
                        if val > 0:
                            return val
        except Exception:
            pass
        return None

    def _extract_area_from_gml(self, xml_text: str) -> Optional[float]:
        """Extrae la superficie en m2 del XML/GML devuelto por Catastro INSPIRE."""
        try:
            root = ET.fromstring(xml_text)
            for elem in root.iter():
                tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                if tag in ["areaValue", "officialArea", "area"]:
                    if elem.text and elem.text.strip():
                        return float(elem.text.strip())
        except Exception:
            pass
        return None

    def resolve_refcat_from_address_or_cru(self, address: str, locality: str, province: str) -> Optional[str]:
        """
        Intenta resolver la Referencia Catastral (20 caracteres) a partir de la dirección postal o localidad
        usando los servicios de localización de Catastro.
        """
        if not address or not locality:
            return None
        import re
        clean_addr = re.sub(r'Piso.*|Puerta.*|Portal.*|CP:.*|Escalera.*', '', address, flags=re.IGNORECASE).strip()
        parts = clean_addr.split(',')
        street_part = parts[0].replace('Calle', '').replace('Avda', '').replace('Avenida', '').replace('Plaza', '').replace('Paseo', '').strip()
        m_num = re.search(r'\b(\d+)\b', street_part)
        num = m_num.group(1) if m_num else '1'
        street_name = re.sub(r'\b\d+\b', '', street_part).strip()

        url = "http://ovc.catastro.meh.es/ovcservweb/OVCSWLocalizacionRC/OVCConsultaRC.asmx/Consulta_DNPPP"
        params = {
            "Provincia": province or "",
            "Municipio": locality or "",
            "TipoVia": "",
            "NombreVia": street_name,
            "Numero": num
        }
        try:
            resp = self.client.get(url, params=params)
            if resp.status_code == 200:
                root = ET.fromstring(resp.text)
                for elem in root.iter():
                    tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                    if tag in ["pc1", "lrcd"]:
                        pc1 = elem.find("{http://www.catastro.meh.es/}pc1") or elem.find("pc1")
                        pc2 = elem.find("{http://www.catastro.meh.es/}pc2") or elem.find("pc2")
                        if pc1 is not None and pc2 is not None and pc1.text and pc2.text:
                            return pc1.text + pc2.text
        except Exception as e:
            logger.warning(f"Error resolviendo Catastro por dirección para {locality}: {e}")
        return None
