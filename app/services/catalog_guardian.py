"""
Guardián del Catálogo de Oportunidades (HIVEX Catalog Guardian)
=============================================================
Responsabilidad estricta:
1. CERO datos simulados o fotos cruzadas de otros inmuebles.
2. Detección proactiva de anuncios despublicados, caducados o retirados en portales de origen.
3. Purga inmediata y automática de cualquier oportunidad que haya dejado de estar disponible en el mercado.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("hivex.catalog_guardian")

DELISTED_PATTERNS = [
    r"ya no está publicado",
    r"anuncio ya no está publicado",
    r"el anunciante lo dio de baja",
    r"el anunciante ha dado de baja",
    r"este inmueble ya no está disponible",
    r"el anuncio ya no está disponible",
    r"inmueble no disponible",
    r"anuncio no disponible",
    r"este anuncio ya no está",
    r"anuncio caducado",
    r"anuncio finalizado",
    r"anuncio retirado",
    r"inmueble retirado",
    r"propiedad no disponible",
    r"no encontramos este inmueble",
    r"lo sentimos,\s*no hemos encontrado",
    r"página no encontrada",
    r"404\s*-\s*página no encontrada",
    r"anuncio dado de baja",
]


class CatalogGuardian:
    def __init__(self, catalog_path: Optional[Path] = None):
        self.catalog_path = catalog_path or (Path("app/data/verified_market_catalog.json"))

    def is_delisted_content(self, content: str) -> Tuple[bool, Optional[str]]:
        """
        Determina si el contenido extraído de la URL indica que el anuncio ha sido dado de baja o ya no existe.
        """
        if not content:
            return False, None

        content_lower = content.lower()
        for pattern in DELISTED_PATTERNS:
            if re.search(pattern, content_lower):
                matched_reason = f"Detectado patrón de despublicación: '{pattern}'"
                logger.info(f"[CatalogGuardian] {matched_reason}")
                return True, matched_reason

        return False, None

    def purge_opportunity(self, opp_id: str) -> bool:
        """
        Elimina de forma permanente e inmediata un inmueble del catálogo de mercado en disco.
        """
        clean_id = str(opp_id).strip().upper()
        if not self.catalog_path.exists():
            return False

        try:
            with open(self.catalog_path, "r", encoding="utf-8") as f:
                items = json.load(f)

            initial_len = len(items)
            filtered_items = [
                it for it in items
                if str(it.get("id", "")).strip().upper() != clean_id
            ]

            if len(filtered_items) < initial_len:
                with open(self.catalog_path, "w", encoding="utf-8") as f:
                    json.dump(filtered_items, f, ensure_ascii=False, indent=2)
                logger.info(f"[CatalogGuardian] Purgada oportunidad {clean_id} del catálogo (total restante: {len(filtered_items)})")
                return True
            return False
        except Exception as e:
            logger.error(f"[CatalogGuardian] Error purgando oportunidad {clean_id}: {e}")
            return False

    def check_and_purge_if_delisted(self, opp_id: str, content: str) -> bool:
        """
        Si el contenido del anuncio indica que está dado de baja, lo purga del catálogo automáticamente.
        Devuelve True si fue purgado.
        """
        is_delisted, reason = self.is_delisted_content(content)
        if is_delisted:
            logger.warning(f"[CatalogGuardian] Purgando {opp_id} por estar dado de baja en origen ({reason})")
            self.purge_opportunity(opp_id)
            return True
        return False

    def audit_catalog(self, max_items: Optional[int] = None) -> Dict[str, Any]:
        """
        Auditoría bajo demanda de oportunidades de mercado.
        Verifica el estado de los anuncios con portal_url y purga automáticamente los caducados.
        """
        from app.connectors.supadata_client import SupadataClient

        if not self.catalog_path.exists():
            return {"checked": 0, "purged": [], "remaining": 0}

        try:
            with open(self.catalog_path, "r", encoding="utf-8") as f:
                items = json.load(f)
        except Exception as e:
            logger.error(f"[CatalogGuardian] Error leyendo catálogo para auditoría: {e}")
            return {"error": str(e)}

        supadata = SupadataClient()
        purged_ids = []
        checked_count = 0

        target_items = [it for it in items if it.get("portal_url")]
        if max_items:
            target_items = target_items[:max_items]

        for it in target_items:
            opp_id = it.get("id")
            portal_url = it.get("portal_url")
            checked_count += 1

            try:
                scrape_res = supadata.scrape_url(portal_url)
                content = scrape_res.get("content", "") if scrape_res else ""
                is_delisted, reason = self.is_delisted_content(content)
                if is_delisted:
                    logger.warning(f"[CatalogGuardian Audit] Inmueble caducado {opp_id} en {portal_url}. Purgando...")
                    self.purge_opportunity(opp_id)
                    purged_ids.append({"id": opp_id, "url": portal_url, "reason": reason})
            except Exception as e_s:
                logger.debug(f"[CatalogGuardian Audit] Error verificando {opp_id}: {e_s}")

        # Recalcular restantes
        remaining = 0
        if self.catalog_path.exists():
            with open(self.catalog_path, "r", encoding="utf-8") as f:
                remaining = len(json.load(f))

        return {
            "checked": checked_count,
            "purged": purged_ids,
            "purged_count": len(purged_ids),
            "remaining": remaining
        }
