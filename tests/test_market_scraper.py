import pytest
from app.connectors.market_scraper import MarketScraper
from app.connectors.pgou_scraper import PGOUScraper
from app.core.auth import create_access_token
from fastapi.testclient import TestClient
from app.api.main import app

client = TestClient(app)
auth_headers = {"Authorization": f"Bearer {create_access_token({'sub': 'testuser'})}"}

def test_market_scraper_deduplication_and_min_price():
    scraper = MarketScraper()
    items = scraper.fetch_market_opportunities()
    
    assert len(items) > 0
    
    for item in items:
        assert item["source_type"] == "market"
        assert item["listing_price"] > 0
        assert "x_publicacion" in item
        assert "distinct_prices_count" in item
        
        # Verify lowest price rule: listing_price must equal minimum price found in all publications
        distinct_prices = [p["price"] for p in item.get("publications", []) if p.get("price")]
        if distinct_prices:
            assert item["listing_price"] == min(distinct_prices)
            # Verify strict rule: len(set(distinct_prices)) equals distinct_prices_count
            assert item["distinct_prices_count"] == len(set(distinct_prices))
            assert item["x_publicacion"] == f"x{len(set(distinct_prices))}"
            
        # Verify discount calculation
        if item.get("original_listing_price") and item["original_listing_price"] > item["listing_price"]:
            expected_discount = round(((item["original_listing_price"] - item["listing_price"]) / item["original_listing_price"]) * 100, 1)
            assert item["discount_percentage"] == expected_discount

def test_market_scraper_same_price_different_portals_no_increment():
    """Valida la regla estricta: Si se detecta en otra página con el mismo precio, NO debe contar."""
    scraper = MarketScraper()
    sample_raw = {
        "id": "MKT-TEST-001",
        "title": "Piso de prueba",
        "original_listing_price": 200000.0,
        "publications": [
            {"portal": "Idealista", "portal_name": "idealista", "price": 180000.0},
            {"portal": "Fotocasa", "portal_name": "fotocasa", "price": 180000.0}, # mismo precio, no debe sumar
            {"portal": "Habitaclia", "portal_name": "habitaclia", "price": 190000.0} # precio distinto, cuenta como 2
        ]
    }
    normalized = scraper._process_market_listing(sample_raw)
    assert normalized["listing_price"] == 180000.0
    assert normalized["distinct_prices_count"] == 2
    assert normalized["x_publicacion"] == "x2"
    assert len(normalized["distinct_prices"]) == 2

def test_market_cross_reference_with_pgou():
    """Valida el cruce de mercado con planeamiento PGOU y detección de sinergias."""
    scraper = MarketScraper()
    market_items = scraper.fetch_market_opportunities()
    pgou_scraper = PGOUScraper()
    pgou_items = pgou_scraper.fetch_pgou_opportunities()
    
    # Run cross-reference
    MarketScraper.cross_reference_with_pgou(market_items, pgou_items)
    
    synergy_items = [m for m in market_items if m.get("has_pgou_synergy")]
    assert len(synergy_items) > 0
    
    for s_item in synergy_items:
        assert s_item["has_pgou_synergy"] is True
        assert s_item.get("pgou_id") is not None
        assert s_item.get("pgou_title") is not None
        assert s_item.get("synergy_reason") is not None

def test_api_market_opportunities_endpoint():
    """Verifica que el endpoint /api/v1/opportunities soporte source_type=market."""
    response = client.get("/api/v1/opportunities?source_type=market", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "opportunities" in data
    opps = data["opportunities"]
    assert len(opps) > 0
    for item in opps:
        assert item["source_type"] == "market"
        assert "x_publicacion" in item
        assert "listing_price" in item
        assert "discount_percentage" in item

def test_api_market_opportunities_filter_synergy():
    """Verifica el filtrado por only_synergy_pgou."""
    response = client.get("/api/v1/opportunities?source_type=market&only_synergy_pgou=true", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    opps = data["opportunities"]
    assert len(opps) > 0
    for item in opps:
        assert item["has_pgou_synergy"] is True
