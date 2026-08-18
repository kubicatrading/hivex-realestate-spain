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
    assert details["reference_price_m2"] > 0
    assert details["surface_m2"] > 0

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
