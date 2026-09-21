import pytest
from app.connectors.market_scraper import MarketScraper
from app.connectors.pgou_scraper import PGOUScraper
from app.core.auth import create_access_token
from fastapi.testclient import TestClient
from app.api.main import app

client = TestClient(app)
auth_headers = {"Authorization": f"Bearer {create_access_token({'sub': 'testuser'})}"}
def test_market_scraper_no_simulated_fallbacks():
    """Valida la regla de oro: Todas las oportunidades de mercado son reales, verificadas, con coordenadas e info física verídica."""
    scraper = MarketScraper()
    items = scraper.fetch_market_opportunities()
    assert isinstance(items, list)
    assert len(items) > 0
    for item in items:
        assert item.get("source_type") == "market"
        assert item.get("lat") is not None and isinstance(item["lat"], (int, float))
        assert item.get("lon") is not None and isinstance(item["lon"], (int, float))
        assert item.get("listing_price", 0) > 0
        assert item.get("original_listing_price", 0) >= item.get("listing_price", 0)
        assert item.get("discount_percentage", 0) >= 0
        assert len(item.get("address", "")) > 0

def test_market_scraper_deduplication_and_min_price():
    """Valida los algoritmos de precio mínimo, deduplicación y cálculo de descuento."""
    scraper = MarketScraper()
    sample_raw = {
        "id": "MKT-TEST-MAD-001",
        "title": "Piso exterior en Madrid",
        "address": "Calle Mayor 10",
        "locality": "Madrid",
        "province": "Madrid",
        "original_listing_price": 300000.0,
        "surface_m2": 80.0,
        "publications": [
            {"portal": "Idealista", "price": 280000.0, "url": "https://idealista.com/1"},
            {"portal": "Fotocasa", "price": 260000.0, "url": "https://fotocasa.es/1"}, # Precio mínimo
            {"portal": "Habitaclia", "price": 270000.0, "url": "https://habitaclia.com/1"}
        ]
    }
    processed = scraper._process_market_listing(sample_raw)
    
    assert processed["source_type"] == "market"
    assert processed["listing_price"] == 260000.0
    assert processed["original_listing_price"] == 300000.0
    assert processed["price_drop_amount"] == 40000.0
    assert processed["discount_percentage"] == 13.3
    assert processed["distinct_prices_count"] == 3
    assert processed["x_publicacion"] == "x3"

def test_market_scraper_same_price_different_portals_no_increment():
    """Valida la regla estricta: Si se detecta en otra página con el mismo precio, NO debe contar."""
    scraper = MarketScraper()
    sample_raw = {
        "id": "MKT-TEST-002",
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
    raw_sample = {
        "id": "MKT-TEST-VALDECARROS",
        "title": "Vivienda en Valdecarros",
        "address": "Avenida del Mayorazgo 42",
        "locality": "Madrid",
        "description": "Junto al sector UZPp 02.06 Valdecarros",
        "original_listing_price": 250000.0,
        "listing_price": 220000.0,
        "lat": 40.3540,
        "lon": -3.6180,
        "publications": [{"portal": "Idealista", "price": 220000.0}]
    }
    processed = scraper._process_market_listing(raw_sample)
    
    pgou_scraper = PGOUScraper()
    pgou_items = pgou_scraper.fetch_pgou_opportunities()
    
    # Run cross-reference
    MarketScraper.cross_reference_with_pgou([processed], pgou_items)
    
    assert processed["has_pgou_synergy"] is True
    assert processed.get("pgou_id") is not None
    assert processed.get("pgou_title") is not None
    assert processed.get("synergy_reason") is not None
    assert "Valdecarros" in processed.get("pgou_title")

def test_api_market_opportunities_endpoint():
    """Verifica que el endpoint /api/v1/opportunities soporte source_type=market retornando 200."""
    response = client.get("/api/v1/opportunities?source_type=market", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "opportunities" in data
    assert isinstance(data["opportunities"], list)
    # Ninguna oportunidad devuelta debe ser una nave industrial
    for opp in data["opportunities"]:
        title = opp.get("title", "").lower()
        desc = opp.get("description", "").lower()
        ptype = opp.get("property_type", "").lower()
        assert "nave industrial" not in title
        assert "nave" != ptype

def test_market_scraper_discards_naves():
    """Verifica que MarketScraper descarte cualquier oportunidad catalogada como nave."""
    scraper = MarketScraper()
    nave_sample = {
        "id": "MKT-NAVE-001",
        "title": "Nave industrial diáfana en polígono",
        "description": "Excelente nave para almacenaje logístico",
        "property_type": "NAVE",
        "listing_price": 150000.0,
        "original_listing_price": 180000.0,
        "surface_m2": 450.0,
        "publications": [{"portal": "Idealista", "price": 150000.0}]
    }
    processed = scraper._process_market_listing(nave_sample)
    assert processed is None, "La nave debió ser descartada por _process_market_listing"

def test_market_scraper_independent_discounts():
    """Verifica que la bajada comercial del portal y el descuento frente al mercado sean independientes."""
    scraper = MarketScraper()
    sample = {
        "id": "MKT-DISC-001",
        "title": "Piso céntrico rebajado",
        "address": "Gran Vía 28",
        "locality": "Madrid",
        "province": "Madrid",
        "original_listing_price": 500000.0,
        "listing_price": 400000.0,
        "price_drop_date": "2026-03-15",
        "surface_m2": 100.0,
        "publications": [{"portal": "Idealista", "price": 400000.0}]
    }
    processed = scraper._process_market_listing(sample)
    assert processed is not None
    # 1. Bajada Comercial del portal
    assert processed["price_drop_amount"] == 100000.0
    assert processed["price_drop_percentage"] == 20.0
    assert processed["price_drop_date"] == "2026-03-15"
    assert processed["original_listing_price"] == 500000.0
    assert processed["listing_price"] == 400000.0
    # 2. Descuento frente a valor de referencia de mercado
    assert "discount_vs_market" in processed
    assert "discount_vs_market_amount" in processed
    assert processed["discount_vs_market_amount"] == processed["potential_gross_profit"]


