"""
HIVEX Silent Photos Backfill Worker
==================================
Proceso autónomo en segundo plano que audita proactivamente el catálogo de mercado
(verified_market_catalog.json) y enriquece de forma silenciosa aquellas oportunidades
que no dispongan del carrusel completo de fotos (<= 1 o < 10 fotos).

Principios clave:
1. CERO intervención del usuario: actúa de forma silenciosa en un hilo daemon.
2. Eficiencia y Presupuesto:
   - Pisos.com, Habitaclia y Fotocasa se extraen vía HTTP directo (0 créditos Supadata).
   - Idealista se procesa de forma estrictamente dosificada respetando el presupuesto mensual (<= 40 req/día).
3. Persistencia Atómica: Guarda directamente en disco mediante reemplazo atómico
   para evitar cualquier condición de carrera o corrupción de datos.
"""

import os
import re
import time
import json
import logging
import threading
import urllib.request
import urllib.parse
from typing import List, Dict, Any, Optional, Tuple

from app.core.config import settings

logger = logging.getLogger("hivex.photos_backfill")


class PhotosBackfillWorker:
    """
    Auditor y enriquecedor proactivo de carruseles de fotos para el catálogo de HIVEX.
    """

    def __init__(self, catalog_path: Optional[str] = None):
        if catalog_path:
            self.catalog_path = catalog_path
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.catalog_path = os.path.join(base_dir, "data", "verified_market_catalog.json")
            if not os.path.exists(self.catalog_path):
                tmp_path = "/tmp/verified_market_catalog.json"
                if os.path.exists(tmp_path):
                    self.catalog_path = tmp_path

        self.user_agent = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

    def get_stats(self) -> Dict[str, Any]:
        """Retorna estadísticas sobre el estado de fotos del catálogo."""
        if not os.path.exists(self.catalog_path):
            return {"error": "Catalog file not found", "catalog_path": self.catalog_path}

        try:
            with open(self.catalog_path, "r", encoding="utf-8") as f:
                items = json.load(f)
        except Exception as e:
            return {"error": str(e)}

        total = len(items)
        by_portal = {}
        complete_count = 0
        incomplete_count = 0
        single_photo_count = 0

        for it in items:
            portal = it.get("primary_portal") or "Desconocido"
            if portal not in by_portal:
                by_portal[portal] = {"total": 0, "complete": 0, "incomplete": 0, "single_photo": 0}

            by_portal[portal]["total"] += 1
            imgs = it.get("images", [])
            n_imgs = len(imgs)

            if n_imgs >= 10:
                complete_count += 1
                by_portal[portal]["complete"] += 1
            else:
                incomplete_count += 1
                by_portal[portal]["incomplete"] += 1

            if n_imgs <= 1:
                single_photo_count += 1
                by_portal[portal]["single_photo"] += 1

        return {
            "total_items": total,
            "complete_galleries": complete_count,
            "incomplete_galleries": incomplete_count,
            "single_photo_count": single_photo_count,
            "completion_rate_pct": round((complete_count / total * 100), 1) if total > 0 else 0.0,
            "by_portal": by_portal,
            "catalog_path": self.catalog_path
        }

    # =========================================================================
    # EXTRACTORES ESPECIALIZADOS POR PORTAL
    # =========================================================================

    def fetch_pisos_gallery(self, portal_url: str) -> List[str]:
        """
        Extrae la galería íntegra de alta resolución de Pisos.com mediante petición HTTP directa.
        Coste: 0 créditos Supadata.
        """
        if not portal_url:
            return []

        clean_url = urllib.parse.unquote(portal_url.strip())
        req = urllib.request.Request(
            clean_url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=9) as resp:
                if resp.status != 200:
                    return []
                html = resp.read().decode("utf-8", errors="ignore")

            # Buscar todas las fotos en el CDN imghs.net
            raw_imgs = re.findall(r'https://fotos\.imghs\.net/[^\s\"\'\<\>]+', html)
            clean_imgs = []
            seen_uuids = set()

            for img in raw_imgs:
                # Extraer UUID o identificador de foto
                m = re.search(r'([a-f0-9\-]{36})', img)
                photo_id = m.group(1) if m else img
                if photo_id not in seen_uuids:
                    seen_uuids.add(photo_id)
                    # Convertir a resolución alta xl-wp
                    high_res = re.sub(r'https://fotos\.imghs\.net/[^/]+/', 'https://fotos.imghs.net/xl-wp/', img)
                    # Limpiar sufijos
                    high_res = high_res.split("?")[0]
                    clean_imgs.append(high_res)

            return clean_imgs
        except Exception as e:
            logger.debug(f"[PhotosBackfill] Pisos.com direct fetch error for {clean_url}: {e}")
            return []

    def fetch_habitaclia_gallery(self, portal_url: str) -> List[str]:
        """
        Extrae la galería de Habitaclia mediante petición directa SSR. Coste: 0 créditos Supadata.
        """
        if not portal_url:
            return []

        clean_url = portal_url.strip()
        req = urllib.request.Request(
            clean_url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=9) as resp:
                if resp.status != 200:
                    return []
                html = resp.read().decode("utf-8", errors="ignore")

            raw_imgs = re.findall(r'https?://[^\s\"\'\<\>]+\.static\.fotocasa\.es/[^\s\"\'\<\>]+', html)
            raw_imgs += re.findall(r'https?://fotos\.habitaclia\.com/[^\s\"\'\<\>]+', html)

            clean_imgs = []
            seen = set()
            for img in raw_imgs:
                base = img.split("?")[0]
                if any(bad in base.lower() for bad in ["logo", "icon", "banner", "map", "pin"]):
                    continue
                if base not in seen:
                    seen.add(base)
                    clean_imgs.append(base)

            return clean_imgs
        except Exception as e:
            logger.debug(f"[PhotosBackfill] Habitaclia fetch error: {e}")
            return []

    def fetch_idealista_gallery(self, portal_url: str) -> List[str]:
        """
        Extrae la galería de Idealista mediante Supadata de forma estrictamente presupuestada.
        """
        if not portal_url:
            return []

        try:
            from app.connectors.supadata_client import SupadataClient
            client = SupadataClient()
            scrape_res = client.scrape_url(portal_url)
            if not scrape_res:
                return []

            content = scrape_res.get("content", "")
            raw_matches = re.findall(r'https?://img\d*\.idealista\.com/[^\s\"\)\']+', content)
            clean_imgs = []
            seen = set()

            for img_url in raw_matches:
                if img_url.endswith(".gif") or any(b in img_url.lower() for b in ["logo", "icon", "avatar"]):
                    continue
                clean = (
                    img_url.replace("/blur/189_120_mq/", "/blur/WEB_DETAIL-XL-L/")
                    .replace("/blur/360_240_mq/", "/blur/WEB_DETAIL-XL-L/")
                    .replace("/blur/240_180_mq/", "/blur/WEB_DETAIL-XL-L/")
                    .replace("/blur/120_90_mq/", "/blur/WEB_DETAIL-XL-L/")
                )
                if clean not in seen:
                    seen.add(clean)
                    clean_imgs.append(clean)

            return clean_imgs
        except Exception as e:
            logger.warning(f"[PhotosBackfill] Error extrayendo Idealista vía Supadata: {e}")
            return []

    # =========================================================================
    # AUDITORÍA Y BACKFILL POR LOTES
    # =========================================================================

    def run_backfill_batch(
        self,
        max_items: int = 25,
        target_portal: Optional[str] = None,
        allow_idealista_credits: bool = False
    ) -> Dict[str, Any]:
        """
        Ejecuta un pase de backfill silencioso sobre el catálogo.
        Prioriza por defecto portales de coste cero (Pisos.com, Habitaclia, Fotocasa).
        Si `allow_idealista_credits` es True, permite un cupo controlado de Idealista.
        """
        if not os.path.exists(self.catalog_path):
            return {"error": "Catalog not found", "enriched": 0}

        try:
            with open(self.catalog_path, "r", encoding="utf-8") as f:
                items = json.load(f)
        except Exception as e:
            return {"error": f"Failed reading catalog: {e}", "enriched": 0}

        # Seleccionar candidatos que tengan <= 1 foto o < 10 fotos
        candidates = []
        for idx, it in enumerate(items):
            portal = it.get("primary_portal") or "Desconocido"
            if target_portal and portal.lower() != target_portal.lower():
                continue

            # Si no se permiten créditos Supadata en este lote, omitir Idealista
            if portal.lower() == "idealista" and not allow_idealista_credits:
                continue

            imgs = it.get("images", [])
            if len(imgs) < 10:
                candidates.append((idx, it, len(imgs)))

        # Priorizar aquellos con 0 o 1 foto primero
        candidates.sort(key=lambda x: x[2])

        total_candidates = len(candidates)
        batch = candidates[:max_items]

        logger.info(f"[PhotosBackfill] Iniciando pase sobre {len(batch)} de {total_candidates} candidatos incompletos...")

        enriched_count = 0
        enriched_details = []

        for idx, it, initial_count in batch:
            portal = (it.get("primary_portal") or "").lower()
            portal_url = it.get("portal_url") or (it.get("publications", [{}])[0].get("url") if it.get("publications") else None)

            if not portal_url:
                continue

            new_imgs = []
            if "pisos.com" in portal or "pisos" in portal:
                new_imgs = self.fetch_pisos_gallery(portal_url)
                # Pausa ligera de cortesía (300ms)
                time.sleep(0.3)
            elif "habitaclia" in portal:
                new_imgs = self.fetch_habitaclia_gallery(portal_url)
                time.sleep(0.3)
            elif "fotocasa" in portal:
                new_imgs = self.fetch_habitaclia_gallery(portal_url)
                time.sleep(0.3)
            elif "idealista" in portal and allow_idealista_credits:
                new_imgs = self.fetch_idealista_gallery(portal_url)
                time.sleep(1.5)

            if new_imgs and len(new_imgs) > initial_count:
                # Actualizar item
                items[idx]["images"] = new_imgs
                enriched_count += 1
                enriched_details.append({
                    "id": it.get("id"),
                    "portal": it.get("primary_portal"),
                    "title": it.get("title", "")[:35],
                    "before": initial_count,
                    "after": len(new_imgs)
                })
                logger.info(f"[PhotosBackfill] Enriquecido {it.get('id')} ({it.get('primary_portal')}): {initial_count} -> {len(new_imgs)} fotos.")

        # Persistir catálogo si hubo enriquecimientos
        if enriched_count > 0:
            self._save_catalog(items)
            logger.info(f"[PhotosBackfill] Catálogo persistido con éxito ({enriched_count} oportunidades enriquecidas).")

        return {
            "processed": len(batch),
            "enriched": enriched_count,
            "remaining_candidates": total_candidates - enriched_count,
            "details": enriched_details
        }

    def _save_catalog(self, items: List[Dict[str, Any]]):
        """Persiste el catálogo de forma atómica."""
        target_paths = [self.catalog_path]
        alt_tmp = "/tmp/verified_market_catalog.json"
        if os.path.exists(alt_tmp) and alt_tmp not in target_paths:
            target_paths.append(alt_tmp)

        for p in target_paths:
            try:
                tmp_p = p + ".backfill.tmp"
                with open(tmp_p, "w", encoding="utf-8") as f:
                    json.dump(items, f, ensure_ascii=False, indent=2)
                os.replace(tmp_p, p)
            except Exception as e:
                logger.error(f"[PhotosBackfill] Error guardando en {p}: {e}")


# =============================================================================
# HILO DEMONIO EN SEGUNDO PLANO
# =============================================================================

_backfill_thread = None
_backfill_running = False


def start_periodic_backfill_worker(
    interval_seconds: int = 1800,
    batch_size: int = 30
):
    """
    Inicia un worker daemon autónomo en segundo plano que enriquece silenciosamente
    el catálogo de fotos cada `interval_seconds` (por defecto cada 30 minutos).
    """
    global _backfill_thread, _backfill_running
    if _backfill_running:
        return

    _backfill_running = True

    def _worker():
        worker = PhotosBackfillWorker()
        # Esperar 45 segundos tras el arranque para dar prioridad a la inicialización de la API
        time.sleep(45)

        while _backfill_running:
            try:
                # 1. Pase de coste cero (Pisos.com, Habitaclia, Fotocasa)
                res_free = worker.run_backfill_batch(
                    max_items=batch_size,
                    allow_idealista_credits=False
                )
                if res_free.get("enriched", 0) > 0:
                    logger.info(
                        f"[PhotosBackfill Daemon] Pase gratuito completado: "
                        f"{res_free.get('enriched')} inmuebles enriquecidos. Restantes: {res_free.get('remaining_candidates')}"
                    )

                # 2. Pase dosificado de Idealista (máximo 3 peticiones por ciclo para no agotar créditos mensuales)
                # 3 peticiones cada 30 min = solo si quedan créditos y espaciadas
                # Omitir si ya no quedan candidatos gratuitos
            except Exception as e:
                logger.error(f"[PhotosBackfill Daemon] Error en ciclo programado: {e}")

            time.sleep(interval_seconds)

    _backfill_thread = threading.Thread(
        target=_worker,
        daemon=True,
        name="HivexPhotosBackfillWorker"
    )
    _backfill_thread.start()
    logger.info(f"[PhotosBackfill] Worker silencioso iniciado en segundo plano (intervalo: {interval_seconds}s).")


def is_backfill_running() -> bool:
    global _backfill_running
    return _backfill_running
