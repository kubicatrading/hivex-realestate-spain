import pytest
from app.core.auth import create_access_token
from fastapi.testclient import TestClient
from app.api.main import app

@pytest.fixture
def auth_headers():
    token = create_access_token(data={"sub": "admin@hivex.es", "is_admin": True})
    return {"Authorization": f"Bearer {token}"}

def test_opportunities_is_new_ordering(auth_headers):
    client = TestClient(app)
    response = client.get("/api/v1/opportunities", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    opps = data.get("opportunities", [])
    assert len(opps) > 0

    first_non_new_idx = None
    for idx, o in enumerate(opps):
        if not o.get("is_new"):
            first_non_new_idx = idx
            break

    if first_non_new_idx is not None:
        for idx in range(first_non_new_idx, len(opps)):
            assert not opps[idx].get("is_new"), (
                f"Found is_new=True at index {idx} after first non-new at {first_non_new_idx}"
            )

    new_opps = [o for o in opps if o.get("is_new")]
    for o in new_opps:
        assert o.get("badge_new") == "New!"

def test_opportunities_by_source_type_has_new_at_top(auth_headers):
    client = TestClient(app)
    for st in ["subastas", "pgou", "edictos"]:
        res = client.get(f"/api/v1/opportunities?source_type={st}", headers=auth_headers)
        assert res.status_code == 200
        data = res.json().get("opportunities", [])
        first_non_new = next((i for i, o in enumerate(data) if not o.get("is_new")), None)
        if first_non_new is not None:
            for idx in range(first_non_new, len(data)):
                assert not data[idx].get("is_new"), f"Found new item after non-new in source {st}"
