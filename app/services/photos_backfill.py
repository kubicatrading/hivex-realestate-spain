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

    def get_daily_quota(self) -> Dict[str, Any]:
        """
        Retorna y actualiza el estado de la cuota diaria de créditos Supadata (máx 10/día = 300/mes).
        """
        today_str = time.strftime("%Y-%m-%d", time.gmtime())
        quota_paths = [
            os.path.join(os.path.dirname(self.catalog_path), "supadata_backfill_quota.json"),
            "/tmp/supadata_backfill_quota.json"
        ]
        data = {
            "date": today_str,
            "credits_used_today": 0,
            "daily_budget": 10,
            "monthly_budget": 300,
            "credits_remaining_today": 10
        }
        for qp in quota_paths:
            if os.path.exists(qp):
                try:
                    with open(qp, "r", encoding="utf-8") as f:
                        saved = json.load(f)
                    if saved.get("date") == today_str:
                        data["credits_used_today"] = saved.get("credits_used_today", 0)
                        break
                except Exception:
                    pass
        data["credits_remaining_today"] = max(0, data["daily_budget"] - data["credits_used_today"])
        return data

    def record_idealista_credit_used(self) -> int:
        """
        Registra 1 crédito consumido para Idealista en la cuota diaria persistida.
        """
        today_str = time.strftime("%Y-%m-%d", time.gmtime())
        quota = self.get_daily_quota()
        quota["credits_used_today"] += 1
        quota["date"] = today_str
        quota["daily_budget"] = 10
        quota["monthly_budget"] = 300
        quota["credits_remaining_today"] = max(0, quota["daily_budget"] - quota["credits_used_today"])
        quota["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        quota_paths = [
            os.path.join(os.path.dirname(self.catalog_path), "supadata_backfill_quota.json"),
            "/tmp/supadata_backfill_quota.json"
        ]
        for qp in quota_paths:
            try:
                os.makedirs(os.path.dirname(qp), exist_ok=True)
                with open(qp, "w", encoding="utf-8") as f:
                    json.dump(quota, f, indent=2)
            except Exception as e:
                logger.debug(f"[PhotosBackfill] Error persistiendo cuota en {qp}: {e}")
        return quota["credits_used_today"]

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
            "catalog_path": self.catalog_path,
            "supadata_daily_quota": self.get_daily_quota()
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
        allow_idealista_credits: bool = True
    ) -> Dict[str, Any]:
        """
        Ejecuta un pase de backfill silencioso sobre el catálogo:
        1. Portales de coste cero (Pisos.com, Habitaclia, Fotocasa) se enriquecen sin límite de créditos.
        2. Idealista consume de la bolsa exclusiva de 300 créditos/mes (estrictamente <= 10 créditos/día).
           Prioriza oportunidades con 0-1 foto y mayor descuento/score.
        """
        if not os.path.exists(self.catalog_path):
            return {"error": "Catalog not found", "enriched": 0}

        try:
            with open(self.catalog_path, "r", encoding="utf-8") as f:
                items = json.load(f)
        except Exception as e:
            return {"error": f"Failed reading catalog: {e}", "enriched": 0}

        free_candidates = []
        idealista_candidates = []

        for idx, it in enumerate(items):
            portal = (it.get("primary_portal") or "Desconocido").lower()
            if target_portal and portal != target_portal.lower():
                continue

            imgs = it.get("images", [])
            if len(imgs) < 10:
                if "idealista" in portal:
                    idealista_candidates.append((idx, it, len(imgs)))
                else:
                    free_candidates.append((idx, it, len(imgs)))

        # Ordenar candidatos gratuitos: menos fotos primero
        free_candidates.sort(key=lambda x: x[2])

        # Ordenar candidatos Idealista:
        # 1. Sin fotos (0 o 1) primero
        # 2. Mayor descuento / score general
        idealista_candidates.sort(
            key=lambda x: (
                0 if x[2] <= 1 else 1,
                -float(x[1].get("overall_score") or x[1].get("discount_score") or 0.0),
                -float(x[1].get("discount_percentage") or 0.0)
            )
        )

        quota = self.get_daily_quota()
        credits_remaining_today = quota.get("credits_remaining_today", 10)

        batch_to_process = []
        # Añadir candidatos gratuitos hasta max_items
        batch_to_process.extend([(*c, False) for c in free_candidates[:max_items]])

        # Si se autoriza Idealista y quedan créditos hoy:
        if allow_idealista_credits:
            if credits_remaining_today > 0:
                slots_left = max(0, max_items - len(batch_to_process))
                idealista_to_take = min(credits_remaining_today, slots_left if slots_left > 0 else 5)
                batch_to_process.extend([(*c, True) for c in idealista_candidates[:idealista_to_take]])
            else:
                logger.info(
                    f"[PhotosBackfill] Cupo diario de 10 créditos Supadata alcanzado hoy ({quota['date']}). "
                    f"Idealista en pausa hasta mañana para preservar los 300 créditos mensuales."
                )

        logger.info(
            f"[PhotosBackfill] Procesando lote de {len(batch_to_process)} inmuebles "
            f"(Gratuitos: {len(free_candidates)}, Idealista pendientes: {len(idealista_candidates)}, "
            f"Créditos Idealista disponibles hoy: {credits_remaining_today}/10)..."
        )

        enriched_count = 0
        enriched_details = []
        idealista_credits_consumed = 0

        for idx, it, initial_count, is_idealista in batch_to_process:
            portal = (it.get("primary_portal") or "").lower()
            portal_url = it.get("portal_url") or (it.get("publications", [{}])[0].get("url") if it.get("publications") else None)

            if not portal_url:
                continue

            new_imgs = []
            if "pisos.com" in portal or "pisos" in portal:
                new_imgs = self.fetch_pisos_gallery(portal_url)
                time.sleep(0.3)
            elif "habitaclia" in portal:
                new_imgs = self.fetch_habitaclia_gallery(portal_url)
                time.sleep(0.3)
            elif "fotocasa" in portal:
                new_imgs = self.fetch_habitaclia_gallery(portal_url)
                time.sleep(0.3)
            elif "idealista" in portal and is_idealista:
                # Comprobar antes de gastar que no hayamos superado los 10 créditos
                current_quota = self.get_daily_quota()
                if current_quota.get("credits_remaining_today", 0) <= 0:
                    logger.info("[PhotosBackfill] Cupo diario completado en mitad del lote. Deteniendo Idealista.")
                    break

                new_imgs = self.fetch_idealista_gallery(portal_url)
                self.record_idealista_credit_used()
                idealista_credits_consumed += 1
                time.sleep(1.5)

            if new_imgs and len(new_imgs) > initial_count:
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

        updated_quota = self.get_daily_quota()
        return {
            "processed": len(batch_to_process),
            "enriched": enriched_count,
            "idealista_credits_used_batch": idealista_credits_consumed,
            "supadata_quota": updated_quota,
            "remaining_free_candidates": max(0, len(free_candidates) - enriched_count),
            "remaining_idealista_candidates": len(idealista_candidates) - idealista_credits_consumed,
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
    batch_size: int = 25
):
    """
    Inicia un worker daemon autónomo en segundo plano que enriquece silenciosamente
    el catálogo de fotos cada `interval_seconds` (por defecto cada 30 minutos).
    Aplica rigurosamente la cuota de máximo 10 créditos Supadata diarios para Idealista.
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
                # Ejecutar lote respetando la bolsa diaria de 10 créditos Supadata para Idealista
                res = worker.run_backfill_batch(
                    max_items=batch_size,
                    allow_idealista_credits=True
                )
                if res.get("enriched", 0) > 0:
                    logger.info(
                        f"[PhotosBackfill Daemon] Ciclo completado: "
                        f"{res.get('enriched')} enriquecidos (Idealista créditos hoy: "
                        f"{res.get('supadata_quota', {}).get('credits_used_today')}/10)."
                    )
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
