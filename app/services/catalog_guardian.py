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
        Soporta tanto Markdown como HTML y payloads JSON embebidos (con barras escapadas \\/).
        """
        if not portal_url or not content:
            return []

        from app.connectors.market_scraper import MarketScraper

        # Desescapar barras JSON (ej. window.__INITIAL_PROPS__ = JSON.parse("...https:\/\/static.fotocasa.es\/..."))
        norm_content = content.replace(r"\/", "/")
        url_lower = portal_url.lower()
        raw_candidates: List[str] = []

        if "idealista.com" in url_lower:
            # En Idealista las fotos reales de anuncio se sirven desde imgX.idealista.com
            raw_imgs = re.findall(r'https?://img\d*\.idealista\.com/[^\s\"\)\'<>\\]+\.(?:jpg|jpeg|webp)', norm_content, re.I)
            for img in raw_imgs:
                if any(x in img.lower() for x in ["loading", "avatar", "common", "user", "static/common", "logo", "/b.pro/", "/blur/95_45_mq/"]):
                    continue
                raw_candidates.append(img)

        elif "fotocasa.es" in url_lower:
            # En Fotocasa las fotos de inmueble son /images/ads/UUID (excluir /images/client/ que son logos de agencia)
            raw_imgs = re.findall(r'https?://(?:[a-z0-9\-]+\.)?static\.fotocasa\.es/images/ads/[a-f0-9\-]{20,}', norm_content, re.I)
            raw_candidates.extend(raw_imgs)

        elif "pisos.com" in url_lower:
            # En Pisos.com las fotos de inmuebles son fotos.imghs.net (excluir map.imghs.net y prof-wp)
            raw_imgs = re.findall(r'https?://fotos\.imghs\.net/[^\s\"\)\'<>\\]+\.(?:jpg|jpeg|webp)', norm_content, re.I)
            for img in raw_imgs:
                if any(x in img.lower() for x in ["logo", "icon", "placeholder", "watermark", "avatar", "prof-wp"]):
                    continue
                raw_candidates.append(img)

        elif "habitaclia.com" in url_lower:
            # En Habitaclia las fotos pertenecen a la red Adevinta (static.fotocasa.es/images/ads/UUID) o images.habimg.com
            # 1. Extraer URLs directas de static.fotocasa.es/images/ads/UUID (presentes en __INITIAL_PROPS__ y Markdown)
            fc_direct = re.findall(r'https?://(?:[a-z0-9\-]+\.)?static\.fotocasa\.es/images/ads/[a-f0-9\-]{20,}', norm_content, re.I)
            raw_candidates.extend(fc_direct)

            # 2. Extraer UUIDs de la galería oficial (foto.htm?p=...imagen=UUID.jpg)
            gallery_uuids = re.findall(r'imagen=([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})\.jpg', norm_content, re.I)
            for uid in gallery_uuids:
                raw_candidates.append(f"https://static.fotocasa.es/images/ads/{uid}")

            # 3. Buscar imágenes habimg (normalizando sufijo P/M/G/V -> XL)
            habimg = re.findall(
                r'(?:https?:)?//images\.habimg\.com/imgh/[^\s\"\'\)<>\\]*[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}[A-Z]*\.(?:jpg|jpeg|webp)',
                norm_content,
                re.I,
            )
            for h in habimg:
                raw_candidates.append(("https:" + h) if h.startswith("//") else h)

            # 4. Fallback a CDNs tradicionales de Habitaclia
            hab_trad = re.findall(r'https?://(?:static|fotos)\.habitaclia\.com/[^\s\"\)\'<>\\]+\.(?:jpg|jpeg|webp)', norm_content, re.I)
            for img in hab_trad:
                if any(x in img.lower() for x in ["logo", "icon", "loading", "avatar", "watermark"]):
                    continue
                raw_candidates.append(img)

        elif "milanuncios.com" in url_lower or "milanuncios" in norm_content[:2000].lower():
            raw_imgs = re.findall(
                r'(?:https?:)?//(?:[a-z0-9\-]+\.)?(?:milanuncios\.com|static\.fotocasa\.es/images/ads|scmspain\.com)/[^\s\"\'\)\]>\\]+?(?:\.(?:jpg|jpeg|webp|png)|[a-f0-9\-]{32,})(?:\?[^\s\"\'\)\]>\\]*)?',
                norm_content,
                re.I,
            )
            for img in raw_imgs:
                full_u = ("https:" + img) if img.startswith("//") else img
                if any(x in full_u.lower() for x in ["logo", "icon", "avatar", "banner", "placeholder", "default", "sprite", "/images/client/"]):
                    continue
                raw_candidates.append(full_u)

        elif "yaencontre.com" in url_lower or "yaencontre" in norm_content[:2000].lower():
            raw_imgs = re.findall(
                r'(?:https?:)?//[^\s\"\'\)\]>\\]*yaencontre\.com[^\s\"\'\)\]>\\]+?\.(?:jpg|jpeg|webp|png)(?:\?[^\s\"\'\)\]>\\]*)?',
                norm_content,
                re.I,
            )
            for img in raw_imgs:
                full_u = ("https:" + img) if img.startswith("//") else img
                if any(x in full_u.lower() for x in ["logo", "icon", "avatar", "banner", "placeholder", "default", "sprite"]):
                    continue
                raw_candidates.append(full_u)

        extracted: List[str] = []
        seen_keys = set()
        for raw_u in raw_candidates:
            norm_u = MarketScraper.normalize_portal_photo_url(raw_u)
            if not MarketScraper.is_valid_real_portal_photo(norm_u):
                continue
            key = MarketScraper.canonical_photo_key(norm_u)
            if key and key not in seen_keys:
                seen_keys.add(key)
                extracted.append(norm_u)

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

    def is_delisted_content(self, content: str, portal_url: str = "") -> Tuple[bool, Optional[str]]:
        """
        Método de compatibilidad con llamadas anteriores.
        Evalúa si el contenido o portal_url carece de fotos o indica recurso no disponible.
        """
        if not content:
            return True, "Contenido vacío o inaccesible"

        content_lower = content.lower()
        delisted_keywords = [
            "ya no está publicado",
            "dio de baja el",
            "ya no está disponible",
            "404 - página no encontrada",
            "anuncio caducado",
            "inmueble no disponible",
            "anuncio desactivado",
            "página no encontrada",
        ]
        for kw in delisted_keywords:
            if kw in content_lower:
                return True, f"Patrón de despublicación detectado: {kw}"

        if portal_url:
            photos = self.extract_photos_from_content(portal_url, content)
            if len(photos) == 0:
                return True, "El portal no dispone de fotos para este anuncio"
        return False, None

    def purge_opportunity(self, opp_id: str) -> bool:
        """
        Elimina de forma permanente e inmediata un inmueble del catálogo de mercado (en PostgreSQL y en disco).
        """
        clean_id = str(opp_id).strip().upper()
        db_purged = False
        try:
            from app.connectors.market_scraper import MarketScraper
            db_purged = MarketScraper.purge_market_opportunity_in_db(clean_id)
        except Exception as e_db_p:
            logger.warning(f"[CatalogGuardian] Aviso purgando {clean_id} en PostgreSQL: {e_db_p}")

        if not self.catalog_path.exists():
            return db_purged

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
            return db_purged
        except Exception as e:
            logger.info(f"[CatalogGuardian] Catálogo en disco solo-lectura, purga de {clean_id} aplicada en PostgreSQL ({db_purged}): {e}")
            return db_purged

    def audit_catalog(self, max_items: Optional[int] = 30, allow_idealista_credits: bool = False) -> Dict[str, Any]:
        """
        Auditoría proactiva del catálogo:
        Recorre inmuebles con portal_url, consulta el estado real en origen y purga
        los que devuelvan 404 o carezcan de fotos.
        Portales directos (Pisos.com, Habitaclia, Fotocasa) se auditan con 0 créditos.
        """
        from app.connectors.supadata_client import SupadataClient
        from app.connectors.market_scraper import MarketScraper

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

        # Fase 0 (0 créditos): Purgar inmediatamente cualquier inmueble con 0 fotos reales o ID sintético
        valid_items_for_http = []
        for it in items:
            opp_id = str(it.get("id") or "").strip().upper()
            valid_imgs = MarketScraper.ensure_twenty_images(it.get("images"))
            if opp_id in MarketScraper.SYNTHETIC_BLACKLIST_IDS or not valid_imgs:
                self.purge_opportunity(opp_id)
                purged_ids.append({
                    "id": opp_id,
                    "url": it.get("portal_url"),
                    "reason": "Sin fotografías reales válidas en catálogo o ID sintético"
                })
            else:
                valid_items_for_http.append(it)

        target_items = [it for it in valid_items_for_http if it.get("portal_url")]
        if max_items:
            target_items = target_items[:max_items]

        for it in target_items:
            opp_id = it.get("id")
            portal_url = it.get("portal_url")
            portal_low = (it.get("primary_portal") or "").lower()
            checked_count += 1

            try:
                content = ""
                http_code = 200
                is_free_portal = any(p in portal_low or p in portal_url.lower() for p in ["pisos", "habitaclia", "fotocasa"])

                # Verificación directa para portales sin bloqueo agresivo (0 créditos Supadata)
                if is_free_portal:
                    try:
                        import httpx
                        headers = {
                            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        }
                        with httpx.Client(timeout=8.0, follow_redirects=True) as client:
                            resp = client.get(portal_url, headers=headers)
                            http_code = resp.status_code
                            if resp.status_code == 200:
                                content = resp.text
                    except Exception as e_d:
                        logger.debug(f"[CatalogGuardian Audit] Check directo para {opp_id}: {e_d}")

                # Para Idealista (requiere proxy residencial Supadata)
                if not content and not is_free_portal:
                    if allow_idealista_credits:
                        scrape_res = supadata.scrape_url(portal_url)
                        content = scrape_res.get("content", "") if scrape_res else ""
                        http_code = scrape_res.get("status_code", 200) if scrape_res else 404
                    else:
                        continue

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

def start_periodic_guardian_worker(interval_seconds: int = 43200, batch_size: int = 25, max_items_per_run: Optional[int] = None):
    """
    Inicia un worker en segundo plano que ejecuta el Guardián de forma proactiva y programada
    cada `interval_seconds` (por defecto cada 12 horas) procesando lotes de `batch_size` / `max_items_per_run`.
    """
    if max_items_per_run is not None:
        batch_size = max_items_per_run
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
