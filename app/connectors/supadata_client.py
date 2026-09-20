"""
Cliente HTTP para Supadata Web Scrape API (https://api.supadata.ai).
Permite extraer el contenido en Markdown de portales inmobiliarios
rotando proxies y superando protecciones anti-bot (DataDome / Cloudflare).
Incluye sistema de caché en memoria/disco con TTL para evitar consumo redundante de créditos.
"""

import os
import time
import json
import logging
import hashlib
from typing import Optional, Dict, Any
import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class SupadataClient:
    """
    Cliente para la API de web scraping de Supadata.
    """

    BASE_URL = "https://api.supadata.ai/v1/web/scrape"

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: float = 35.0,
        cache_dir: Optional[str] = None,
        cache_ttl_seconds: int = 7200  # 2 horas de caché por defecto
    ):
        self.api_key = (api_key or os.environ.get("SUPADATA_API_KEY", "")).strip()
        self.timeout = timeout
        self.cache_ttl_seconds = cache_ttl_seconds
        
        # Directorio de caché local para no consumir créditos en peticiones idénticas
        if cache_dir is None:
            if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
                cache_dir = os.path.join("/tmp", "cache_supadata")
            else:
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                cache_dir = os.path.join(base_dir, "data", "cache_supadata")
        self.cache_dir = cache_dir
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
        except OSError:
            self.cache_dir = os.path.join("/tmp", "cache_supadata")
            try:
                os.makedirs(self.cache_dir, exist_ok=True)
            except Exception:
                pass

    def _get_cache_path(self, url: str) -> str:
        url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
        return os.path.join(self.cache_dir, f"{url_hash}.json")

    def _read_cache(self, url: str) -> Optional[Dict[str, Any]]:
        cache_file = self._get_cache_path(url)
        if not os.path.exists(cache_file):
            return None
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            cached_at = data.get("_cached_at", 0)
            if time.time() - cached_at < self.cache_ttl_seconds:
                logger.info(f"[Supadata Cache HIT] URL={url}")
                return data.get("response")
        except Exception as e:
            logger.warning(f"Error leyendo caché de Supadata para {url}: {e}")
        return None

    def _write_cache(self, url: str, response_data: Dict[str, Any]) -> None:
        cache_file = self._get_cache_path(url)
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump({
                    "url": url,
                    "_cached_at": time.time(),
                    "response": response_data
                }, f, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Error guardando caché de Supadata para {url}: {e}")

    def scrape_url(self, target_url: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """
        Envía una URL a Supadata para extraer su contenido en Markdown.
        Devuelve el diccionario con { url, content, name, description, countCharacters... }
        o None si falla.
        """
        if not self.api_key:
            logger.error("SUPADATA_API_KEY no está configurada.")
            return None

        # Comprobar caché previa
        if not force_refresh:
            cached = self._read_cache(target_url)
            if cached:
                return cached

        headers = {
            "x-api-key": self.api_key,
            "Accept": "application/json"
        }
        params = {
            "url": target_url
        }

        logger.info(f"[Supadata LIVE Request] Extrayendo: {target_url}...")
        try:
            with httpx.Client(timeout=self.timeout) as client:
                res = client.get(self.BASE_URL, headers=headers, params=params)
                
                if res.status_code == 200:
                    data = res.json()
                    content_len = len(data.get("content", ""))
                    logger.info(f"[Supadata Success] {target_url} -> {content_len} caracteres obtenidos.")
                    self._write_cache(target_url, data)
                    return data
                elif res.status_code in (401, 403):
                    logger.error(f"[Supadata Auth Error] Código {res.status_code}: {res.text}")
                    return None
                else:
                    logger.warning(f"[Supadata Warning] Status {res.status_code}: {res.text}")
                    return None
        except Exception as e:
            logger.error(f"[Supadata Exception] Error conectando con Supadata para {target_url}: {e}")
            return None
