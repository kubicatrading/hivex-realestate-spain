import pytest
from app.core.geo_utils import get_spanish_province_coords, normalize_text, MUNICIPALITIES_COORDS_MAP, PROVINCE_COORDS_MAP
from app.connectors.catastro_client import CatastroClient

def test_municipality_geolocation_on_land():
    # Benidorm should be in Benidorm, not Alicante center or sea
    lat_beni, lon_beni = get_spanish_province_coords("Alicante", "Benidorm")
    assert 38.52 <= lat_beni <= 38.56
    assert -0.15 <= lon_beni <= -0.10

    # Torrevieja should be ~37.97, ~-0.68
    lat_torre, lon_torre = get_spanish_province_coords("Alicante", "Torrevieja")
    assert 37.95 <= lat_torre <= 38.00
    assert -0.71 <= lon_torre <= -0.66

    # Denia should be ~38.84, ~0.10
    lat_denia, lon_denia = get_spanish_province_coords("Alicante", "Denia")
    assert 38.80 <= lat_denia <= 38.86
    assert 0.08 <= lon_denia <= 0.13

    # Elche should be ~38.26, ~-0.69
    lat_elx, lon_elx = get_spanish_province_coords("Alicante", "Elche")
    assert 38.24 <= lat_elx <= 38.29
    assert -0.72 <= lon_elx <= -0.67

    # Castalla should be inland ~38.59, ~-0.67
    lat_cas, lon_cas = get_spanish_province_coords("Alicante", "Castalla")
    assert 38.57 <= lat_cas <= 38.62
    assert -0.69 <= lon_cas <= -0.65

def test_coastal_city_no_sea_pins():
    # Test 50 iterations with jitter for Alicante capital to guarantee no pin falls in the sea
    for _ in range(50):
        lat, lon = get_spanish_province_coords("Alicante", "Alicante", apply_jitter=True)
        # Port & sea in Alicante is lat < 38.338 and lon > -0.480
        assert lat >= 38.3410, f"Latitude {lat} fell south towards the sea"
        assert lon <= -0.4810, f"Longitude {lon} fell east towards the sea"

def test_catastro_refcat_normalization_and_method():
    cat = CatastroClient()
    # Invalid or short refcat returns None
    assert cat.get_coordinates_from_refcat("") is None
    assert cat.get_coordinates_from_refcat("NO CONSTA") is None
    assert cat.get_coordinates_from_refcat("1234") is None

def test_opportunity_api_coordinates_not_in_sea():
    from app.db.session import SessionLocal
    from app.db.models import Opportunity, Auction
    db = SessionLocal()
    opps = db.query(Opportunity).join(Auction).filter(Auction.province.ilike("%alicante%")).all()
    for o in opps:
        auc = o.auction
        # Ensure none of the Alicante opportunities in DB are in the sea
        assert not (38.20 <= auc.lat <= 38.338 and -0.52 <= auc.lon <= -0.45), \
            f"Auction {auc.id_subasta} in {auc.locality} has sea coordinates: lat={auc.lat}, lon={auc.lon}"


def test_market_catalog_geolocation_and_integrity():
    import json
    from pathlib import Path

    catalog_path = Path("app/data/verified_market_catalog.json")
    assert catalog_path.exists()

    with open(catalog_path, encoding="utf-8") as f:
        items = json.load(f)

    assert len(items) > 0

    valencia_items = [it for it in items if (it.get("province") or "").lower() == "valencia" or (it.get("locality") or "").lower() == "valencia"]
    barcelona_items = [it for it in items if (it.get("province") or "").lower() == "barcelona" or (it.get("locality") or "").lower() == "barcelona"]

    assert len(valencia_items) >= 25
    assert len(barcelona_items) >= 50

    # Ensure Valencia items are NOT geocoded to Barcelona
    for it in valencia_items:
        lat = float(it["lat"])
        lon = float(it["lon"])
        assert 39.35 <= lat <= 39.60, f"Valencia item {it['id']} has invalid lat {lat}"
        assert -0.55 <= lon <= -0.25, f"Valencia item {it['id']} has invalid lon {lon}"

    # Ensure Barcelona items are in Barcelona
    for it in barcelona_items:
        lat = float(it["lat"])
        lon = float(it["lon"])
        assert 41.30 <= lat <= 41.50, f"Barcelona item {it['id']} has invalid lat {lat}"
        assert 2.05 <= lon <= 2.30, f"Barcelona item {it['id']} has invalid lon {lon}"

    # Ensure no naves in catalog
    for it in items:
        p_type = (it.get("property_type") or "").lower()
        import re
        title = (it.get("title") or "").lower()
        assert "nave" not in p_type, f"Item {it['id']} is a nave: {p_type}"
        assert not re.search(r'\b(nave|naves)\b', title), f"Item {it['id']} title contains nave: {title}"

def test_market_catalog_images_integrity():
    """Valida que las fotos del catálogo cumplen los requisitos de fidelidad y límite de 20."""
    import json
    catalog_path = "app/data/verified_market_catalog.json"
    with open(catalog_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    max_imgs = 0
    twenty_count = 0
    for it in items:
        imgs = it.get("images", [])
        assert len(imgs) <= 20, f"Item {it['id']} has more than 20 images: {len(imgs)}"
        assert len(imgs) == len(set(imgs)), f"Item {it['id']} has duplicate images"
        for img in imgs:
            assert isinstance(img, str) and img.startswith("http"), f"Invalid image in {it['id']}: {img}"
            assert "catastro" not in img.lower(), f"Catastro image found in real estate gallery: {img}"
        if len(imgs) > max_imgs:
            max_imgs = len(imgs)
        if len(imgs) == 20:
            twenty_count += 1

    assert max_imgs == 20, f"Expected maximum of 20 images, found {max_imgs}"
    assert twenty_count >= 5, f"Expected at least 5 listings with 20 real photos, found {twenty_count}"


