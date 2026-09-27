"""
Guardián del Catálogo de Oportunidades (HIVEX Catalog Guardian)
=============================================================
Principios de diseño:
1. REGLA ESTRUCTURAL UNIVERSAL (Sin dependencia lingüística ni modismos):
   - Código HTTP 404 / 410 / Inaccesible -> Inmueble caducado / retirado.
   - Si el portal ya NO dispone de fotografías para ese inmueble (0 fotos reales encontradas) -> Inmueble caducado / retirado.
   - Cero fotos simuladas o prestadas de otros inmuebles.
2. MODOS DE OPERACIÓN:
   - REACTIVO (En tiempo real / On-Demand): Al abrir un inmueble en la plataforma.
   - PROACTIVO Y PROGRAMADO (Scheduled / Background Worker): Auditoría periódica autónoma en segundo plano.
   - ADMINISTRATIVO: Disparo manual bajo demanda vía API endpoint (/api/v1/market/guardian/audit).
"""

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("hivex.catalog_guardian")


class CatalogGuardian:
    def __init__(self, catalog_path: Optional[Path] = None):
        self.catalog_path = catalog_path or (Path("app/data/verified_market_catalog.json"))

    @staticmethod
    def extract_photos_from_content(portal_url: str, content: str) -> List[str]:
        """
        Extrae exclusivamente fotografías reales del inmueble en el portal indicado.
        Totalmente independiente del idioma en que esté renderizada la página.
        """
        if not portal_url or not content:
            return []

        url_lower = portal_url.lower()
        extracted: List[str] = []

        if "idealista.com" in url_lower:
            # En Idealista las fotos reales de anuncio se sirven desde imgX.idealista.com
            # Descartamos avatares, logos comunes, mapas y assets de interfaz
            raw_imgs = re.findall(r'https?://img\d*\.idealista\.com/[^\s\"\)\']+\.jpg', content)
            for img in raw_imgs:
                if any(x in img.lower() for x in ["loading", "avatar", "common", "user", "static/common", "logo"]):
                    continue
                cleaned = re.sub(r'/blur/[^/]+/', '/blur/WEB_DETAIL-XL-L/', img)
                if cleaned not in extracted:
                    extracted.append(cleaned)

        elif "fotocasa.es" in url_lower:
            # En Fotocasa las fotos de inmueble son /images/ads/UUID
            raw_imgs = re.findall(r'https?://static\.fotocasa\.es/images/ads/[a-f0-9\-]+', content)
            for img in raw_imgs:
                clean_url = img.split("?")[0]
                if clean_url not in extracted:
                    extracted.append(clean_url)

        elif "pisos.com" in url_lower:
            # En Pisos.com las fotos de inmuebles son fotos.imghs.net
            raw_imgs = re.findall(r'https?://fotos\.imghs\.net/[^\s\"\)\']+\.jpg', content)
            for img in raw_imgs:
                if any(x in img.lower() for x in ["logo", "icon", "placeholder", "watermark", "avatar"]):
                    continue
                cleaned = img.replace("/fchm-wp/", "/fch-wp/")
                if cleaned not in extracted:
                    extracted.append(cleaned)

        elif "habitaclia.com" in url_lower:
            # En Habitaclia las fotos son static|fotos.habitaclia.com
            raw_imgs = re.findall(r'https?://(?:static|fotos)\.habitaclia\.com/[^\s\"\)\']+\.jpg', content)
            for img in raw_imgs:
                if any(x in img.lower() for x in ["logo", "icon", "loading", "avatar", "watermark"]):
                    continue
                if img not in extracted:
                    extracted.append(img)

        return extracted

    def verify_listing_active_status(
        self,
        portal_url: str,
        content: Optional[str] = None,
        http_code: Optional[int] = None
    ) -> Tuple[bool, Optional[str], List[str]]:
        """
        Regla Determinista Universal (Independiente del idioma):
        - Código HTTP 404 / 410 -> Despublicado (Inmueble retirado o página inexistente).
        - Si el portal ya NO dispone de fotos para ese inmueble (0 fotos válidas) -> Despublicado.
        - Si el portal dispone de al menos 1 foto real -> Activo.

        Retorna:
            (is_delisted: bool, reason: Optional[str], valid_photos: List[str])
        """
        # 1. Validación por códigos de estado HTTP estándar
        if http_code in (404, 410):
            return True, f"Código HTTP {http_code} (Página inexistente / Anuncio eliminado)", []

        if not content or len(content.strip()) < 50:
            return True, "Respuesta vacía o inaccesible desde el portal", []

        # 2. Validación estructural: ¿El portal dispone de fotos para este inmueble?
        photos = self.extract_photos_from_content(portal_url, content)
        if len(photos) == 0:
            # El portal ya no dispone de reportaje fotográfico para este activo
            return True, "El portal ya no dispone de fotografías para este inmueble (anuncio retirado/caducado)", []

        return False, None, photos

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

    def audit_catalog(self, max_items: Optional[int] = 30) -> Dict[str, Any]:
        """
        Auditoría proactiva del catálogo:
        Recorre inmuebles con portal_url, consulta el estado real en origen y purga
        los que devuelvan 404 o carezcan de fotos.
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
                http_code = scrape_res.get("status_code", 200) if scrape_res else 404

                is_delisted, reason, photos = self.verify_listing_active_status(
                    portal_url=portal_url,
                    content=content,
                    http_code=http_code
                )

                if is_delisted:
                    logger.warning(f"[CatalogGuardian Audit] Inmueble {opp_id} sin fotos o caducado en origen ({reason}). Purgando...")
                    self.purge_opportunity(opp_id)
                    purged_ids.append({"id": opp_id, "url": portal_url, "reason": reason})
            except Exception as e_s:
                logger.debug(f"[CatalogGuardian Audit] Advertencia auditando {opp_id}: {e_s}")

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


# Demonio / Hilo de Auditoría Periódica Autónomo
_guardian_thread = None
_guardian_running = False

def start_periodic_guardian_worker(interval_seconds: int = 43200, batch_size: int = 25):
    """
    Inicia un worker en segundo plano que ejecuta el Guardián de forma proactiva y programada
    cada `interval_seconds` (por defecto cada 12 horas) procesando lotes de `batch_size`.
    """
    global _guardian_thread, _guardian_running
    if _guardian_running:
        return

    _guardian_running = True

    def _worker():
        guardian = CatalogGuardian()
        # Esperar 60 segundos tras el arranque antes del primer pase para no saturar el inicio
        time.sleep(60)
        while _guardian_running:
            try:
                logger.info("[CatalogGuardian Worker] Iniciando ciclo programado de auditoría...")
                res = guardian.audit_catalog(max_items=batch_size)
                logger.info(f"[CatalogGuardian Worker] Ciclo completado: {res.get('purged_count', 0)} purgados de {res.get('checked', 0)} auditados.")
            except Exception as e:
                logger.error(f"[CatalogGuardian Worker] Error en ciclo programado: {e}")

            # Dormir hasta el siguiente intervalo
            time.sleep(interval_seconds)

    _guardian_thread = threading.Thread(target=_worker, daemon=True, name="HivexCatalogGuardianWorker")
    _guardian_thread.start()
    logger.info(f"[CatalogGuardian] Worker programado iniciado en segundo plano (intervalo: {interval_seconds}s).")
