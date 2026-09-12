import pytest
from app.core.auth import create_access_token
from fastapi.testclient import TestClient
from app.api.main import app, LATEST_SYNC_STATE

@pytest.fixture
def auth_headers():
    token = create_access_token(data={"sub": "admin@hivex.es", "is_admin": True})
    return {"Authorization": f"Bearer {token}"}

def test_zero_false_positives_without_active_sync(auth_headers):
    """Garantizar rigor: si no ha habido sincronización con novedades reales, ningún elemento debe llevar 'New!' ni simulación."""
    LATEST_SYNC_STATE["new_auction_ids"] = set()
    LATEST_SYNC_STATE["new_pgou_ids"] = set()
    LATEST_SYNC_STATE["new_edicto_ids"] = set()

    client = TestClient(app)
    response = client.get("/api/v1/opportunities", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    opps = data.get("opportunities", [])
    assert len(opps) > 0

    new_opps = [o for o in opps if o.get("is_new")]
    assert len(new_opps) == 0, f"No debe haber falsos positivos de 'New!'. Encontrados: {len(new_opps)}"

def test_real_sync_novelties_prioritized_at_top(auth_headers):
    """Verificar que cuando una sincronización real introduce oportunidades nuevas, éstas aparecen exactamente al frente."""
    # Simular una sincronización que detectó 2 oportunidades concretas
    LATEST_SYNC_STATE["new_auction_ids"] = {10}
    LATEST_SYNC_STATE["new_pgou_ids"] = {"PGOU-MAD-2026-003"}
    LATEST_SYNC_STATE["new_edicto_ids"] = set()

    client = TestClient(app)
    response = client.get("/api/v1/opportunities", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    opps = data.get("opportunities", [])

    new_opps = [o for o in opps if o.get("is_new")]
    assert len(new_opps) == 2
    for o in new_opps:
        assert o.get("badge_new") == "New!"

    # Las 2 novedades deben ser estrictamente los primeros 2 elementos de la lista
    assert opps[0].get("is_new") is True
    assert opps[1].get("is_new") is True
    if len(opps) > 2:
        assert opps[2].get("is_new") is not True

    # Limpiar estado
    LATEST_SYNC_STATE["new_auction_ids"] = set()
    LATEST_SYNC_STATE["new_pgou_ids"] = set()
    LATEST_SYNC_STATE["new_edicto_ids"] = set()
