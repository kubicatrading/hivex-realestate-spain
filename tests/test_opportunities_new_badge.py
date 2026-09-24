import pytest
from app.core.auth import create_access_token
from fastapi.testclient import TestClient
from app.api.main import app, LATEST_SYNC_STATE

from app.db.session import SessionLocal
from app.db.models import Auction, Opportunity, StrategyType

@pytest.fixture
def auth_headers():
    token = create_access_token(data={"sub": "admin@hivex.es", "is_admin": True})
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture(autouse=True)
def ensure_test_opportunities():
    db = SessionLocal()
    try:
        auc10 = db.query(Auction).filter(Auction.id == 10).first()
        if not auc10:
            auc10 = Auction(
                id=10,
                id_subasta="SUB-TEST-10",
                title="Piso en subasta test 10",
                property_type="Vivienda",
                starting_bid=100000.0,
                appraisal_value=200000.0,
                province="Madrid"
            )
            db.add(auc10)
            db.commit()
            db.refresh(auc10)
        
        opp10 = db.query(Opportunity).filter(Opportunity.auction_id == 10).first()
        if not opp10:
            opp10 = Opportunity(
                auction_id=auc10.id,
                strategy=StrategyType.HOUSE_FLIPPING,
                discount_percentage=0.50,
                potential_gross_profit=100000.0,
                overall_score=85.0,
                rental_yield=7.5
            )
            db.add(opp10)
            db.commit()

        auc20 = db.query(Auction).filter(Auction.id == 20).first()
        if not auc20:
            auc20 = Auction(
                id=20,
                id_subasta="SUB-TEST-20",
                title="Piso en subasta test 20",
                property_type="Vivienda",
                starting_bid=120000.0,
                appraisal_value=200000.0,
                province="Madrid"
            )
            db.add(auc20)
            db.commit()
            db.refresh(auc20)
        
        opp20 = db.query(Opportunity).filter(Opportunity.auction_id == 20).first()
        if not opp20:
            opp20 = Opportunity(
                auction_id=auc20.id,
                strategy=StrategyType.HOUSE_FLIPPING,
                discount_percentage=0.40,
                potential_gross_profit=80000.0,
                overall_score=75.0,
                rental_yield=6.2
            )
            db.add(opp20)
            db.commit()
    finally:
        db.close()

def test_zero_false_positives_without_active_sync(auth_headers):
    """Garantizar rigor: si no ha habido sincronización con novedades reales, ningún elemento debe llevar 'New!' ni simulación."""
    LATEST_SYNC_STATE["new_auction_ids"] = set()
    LATEST_SYNC_STATE["new_pgou_ids"] = set()
    LATEST_SYNC_STATE["new_edicto_ids"] = set()
    LATEST_SYNC_STATE["new_market_ids"] = set()

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
    # Simular una sincronización que detectó 2 oportunidades concretas (usar subasta activa vigente)
    from app.db.session import SessionLocal
    from app.db.models import Auction
    active_auc = SessionLocal().query(Auction).filter(Auction.status == "EJECUCION").first()
    auc_id = active_auc.id if active_auc else 980
    LATEST_SYNC_STATE["new_auction_ids"] = {auc_id}
    LATEST_SYNC_STATE["new_pgou_ids"] = {"PGOU-MAD-2026-003"}
    LATEST_SYNC_STATE["new_edicto_ids"] = set()
    LATEST_SYNC_STATE["new_market_ids"] = set()

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
    LATEST_SYNC_STATE["new_market_ids"] = set()
