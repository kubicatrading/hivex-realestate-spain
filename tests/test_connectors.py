import pytest
from app.connectors.boe_scraper import BOESubastasScraper
from app.connectors.catastro_client import CatastroClient
from app.connectors.ine_client import INEClient
from app.connectors.osm_client import OSMOverpassClient

def test_boe_cadastral_reference_extractor():
    scraper = BOESubastasScraper()
    sample_text = "Finca registrada en la subasta con RefCat 8812301VK4781S0001AB para adjudicación."
    refcat = scraper.extract_cadastral_reference(sample_text)
    assert refcat == "8812301VK4781S0001AB"

def test_catastro_client_mock():
    client = CatastroClient()
    details = client.get_parcel_details("8812301VK4781S0001AB")
    assert details["refcat"] == "8812301VK4781S0001AB"
    assert details["reference_price_m2"] is None or details["reference_price_m2"] > 0
    assert details["surface_m2"] is None or details["surface_m2"] > 0

def test_ine_client_mock():
    ine = INEClient()
    stats = ine.get_census_section_stats("Madrid", "Madrid")
    assert stats["avg_household_income"] > 20000
    assert stats["population_growth_rate"] > 0

def test_osm_client_mock():
    osm = OSMOverpassClient()
    metrics = osm.get_poi_metrics(40.4285, -3.6701, radius_meters=500)
    assert metrics["total_pois"] >= 0
    assert 0.0 <= metrics["poi_score"] <= 100.0

def test_boe_surface_and_ownership_parsing():
    scraper = BOESubastasScraper()
    text = "URBANA:16,67% del pleno dominio privativo de finca... Superficie 92.35m2."
    
    # Test decimal parsing: 92.35m2 should NOT be 9235
    surface = scraper.extract_surface_m2(text)
    assert surface == 92.35

    # Test ownership percentage: 16.67%
    ownership_pct = scraper.extract_ownership_percentage(text)
    assert ownership_pct == 16.67

    # Test land classification: URBANO
    land_type = scraper.extract_land_classification(text)
    assert land_type == "URBANO"

def test_boe_liens_extraction():
    scraper = BOESubastasScraper()
    
    # Libre de cargas
    text_free = "El bien inmueble se subasta libre de cargas preferentes según edicto."
    liens_free = scraper.extract_liens_info(text_free)
    assert liens_free["has_liens"] is False
    assert liens_free["status"] == "SIN CARGAS"

    # Con cargas
    text_liens = "Subasta judicial con cargas y gravámenes preferentes: Hipoteca a favor de entidad bancaria."
    liens_busy = scraper.extract_liens_info(text_liens)
    assert liens_busy["has_liens"] is True
    assert liens_busy["status"] == "CON CARGAS"
