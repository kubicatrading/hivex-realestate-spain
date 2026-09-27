import json
import pytest
from pathlib import Path
from app.services.catalog_guardian import CatalogGuardian


def test_catalog_guardian_detection():
    guardian = CatalogGuardian()

    # Patrones de baja en portales españoles
    assert guardian.is_delisted_content("Lo sentimos, este anuncio ya no está publicado")[0] is True
    assert guardian.is_delisted_content("El anunciante lo dio de baja el 16/03/2024")[0] is True
    assert guardian.is_delisted_content("Este inmueble ya no está disponible")[0] is True
    assert guardian.is_delisted_content("404 - Página no encontrada")[0] is True
    assert guardian.is_delisted_content("Anuncio caducado por la agencia")[0] is True

    # Anuncio normal activo
    assert guardian.is_delisted_content("Gran oportunidad en Madrid centro, 80m2 reformado")[0] is False


def test_catalog_guardian_purge(tmp_path):
    catalog_file = tmp_path / "test_catalog.json"
    dummy_data = [
        {"id": "MKT-1", "title": "Piso activo"},
        {"id": "MKT-CADUCADO-99", "title": "Piso caducado"},
        {"id": "MKT-3", "title": "Chalet activo"},
    ]
    catalog_file.write_text(json.dumps(dummy_data), encoding="utf-8")

    guardian = CatalogGuardian(catalog_path=catalog_file)
    res = guardian.purge_opportunity("MKT-CADUCADO-99")
    assert res is True

    remaining = json.loads(catalog_file.read_text(encoding="utf-8"))
    assert len(remaining) == 2
    assert all(it["id"] != "MKT-CADUCADO-99" for it in remaining)
