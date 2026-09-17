import os
import time
import pytest
from app.connectors.supadata_client import SupadataClient


def test_supadata_client_init():
    client = SupadataClient(api_key="test_key_123")
    assert client.api_key == "test_key_123"
    assert client.cache_ttl_seconds == 7200
    assert os.path.exists(client.cache_dir)


def test_supadata_client_cache_read_write(tmp_path):
    client = SupadataClient(api_key="test_key", cache_dir=str(tmp_path), cache_ttl_seconds=60)
    test_url = "https://www.idealista.com/venta-viviendas/madrid-madrid/"
    
    # 1. Cache initially empty
    assert client._read_cache(test_url) is None
    
    # 2. Write to cache
    mock_response = {
        "url": test_url,
        "content": "# 18.000 viviendas en Madrid\n\n[Piso en Goya](https://www.idealista.com/inmueble/123/)",
        "countCharacters": 100
    }
    client._write_cache(test_url, mock_response)
    
    # 3. Read back from cache
    cached = client._read_cache(test_url)
    assert cached is not None
    assert cached["url"] == test_url
    assert "18.000 viviendas" in cached["content"]
    
    # 4. Expired cache returns None
    client.cache_ttl_seconds = 0
    time.sleep(0.05)
    assert client._read_cache(test_url) is None
