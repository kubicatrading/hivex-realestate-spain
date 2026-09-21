import pytest
from app.connectors.portal_parsers import IdealistaMarkdownParser, HabitacliaMarkdownParser


SAMPLE_IDEALISTA_MARKDOWN = """
# 18.413 casas y pisos en Madrid

Top+
1/31
![Primera foto del inmueble](https://img4.idealista.com/blur/189_120_mq/0/id.pro.es.image.master/c9/01/36/1464444214.jpg)
[![Gilmar Barrio de Salamanca](https://st3.idealista.com/90/79/01/gilmarsalamanca.gif)](https://www.idealista.com/pro/gilmarsalamanca/ "Gilmar Barrio de Salamanca")
[ComercializaGilmar Barrio de Salamanca](https://www.idealista.com/pro/gilmarsalamanca/)

[Piso en Calle del Conde de Peñalver, Goya, Madrid](https://www.idealista.com/inmueble/112270818/ "Piso en Calle del Conde de Peñalver, Goya, Madrid")

1.350.000€10.305 €/m²
1.450.000 €
7%

Garaje incluido 3 hab.131 m²3ª planta exterior con ascensor

Vivienda exterior con dos plazas de garaje en la zona de Goya. En una de las zonas más consolidadas y demandadas de Madrid.

ContactarLlamarVer teléfonoDescartarGuardar

Top+
1/36
![Foto Malasaña](https://img4.idealista.com/blur/189_120_mq/0/id.pro.es.image.master/6c/dd/2c/1441278735.jpg)
[ComercializaGilmar Centro](https://www.idealista.com/pro/gilmar-centro/)

[Piso en Calle del Barco, Malasaña-Universidad, Madrid](https://www.idealista.com/inmueble/111433413/ "Piso en Calle del Barco, Malasaña-Universidad, Madrid")

750.000€
798.000 €
6%

2 hab.102 m²1ª planta interior con ascensor

GILMAR Consulting Inmobiliario pone a su disposición este sofisticado piso.
"""

SAMPLE_HABITACLIA_MARKDOWN = """
# Pisos en venta en Barcelona

[Piso con terraza en Poblenou](https://www.habitaclia.com/comprar-viviendas-barcelona/sant_marti_poblenou-i24589012.htm)

320.000 €

3 hab. 85 m² 2ª planta exterior con ascensor
Espectacular piso reformado en Poblenou.
"""


def test_idealista_markdown_parser():
    listings = IdealistaMarkdownParser.parse_listings(SAMPLE_IDEALISTA_MARKDOWN, default_province="Madrid")
    
    assert len(listings) == 2
    # Comprobar que dentro de cada página vienen ordenadas por score general y yield descendente
    assert listings[0]["overall_score"] >= listings[1]["overall_score"]
    
    # Inmueble Goya
    item1 = next(x for x in listings if "112270818" in x["id"])
    assert "Conde de Peñalver" in item1["title"]
    assert item1["listing_price"] == 1350000.0
    assert item1["original_listing_price"] == 1450000.0
    assert item1["rooms"] == 3
    assert item1["surface_m2"] == 131.0
    assert item1["has_elevator"] is True
    assert item1["publications"][0]["agency"] == "Gilmar Barrio de Salamanca"
    assert len(item1["images"]) > 0
    assert item1["lat"] is not None and item1["lon"] is not None
    assert item1["census_tract_data"]["avg_household_income"] > 50000
    assert item1.get("rental_yield") is not None

    # Inmueble Malasaña
    item2 = next(x for x in listings if "111433413" in x["id"])
    assert item2["listing_price"] == 750000.0
    assert item2["original_listing_price"] == 798000.0
    assert item2["rooms"] == 2
    assert item2["surface_m2"] == 102.0
    assert item2["publications"][0]["agency"] == "Gilmar Centro"
    assert item2.get("rental_yield") is not None


def test_habitaclia_markdown_parser():
    listings = HabitacliaMarkdownParser.parse_listings(SAMPLE_HABITACLIA_MARKDOWN, default_province="Barcelona")
    assert len(listings) == 1
    item = listings[0]
    assert "24589012" in item["id"]
    assert item["listing_price"] == 320000.0
    assert item["locality"] == "Barcelona"
    assert item["lat"] is not None and item["lon"] is not None


SAMPLE_FOTOCASA_MARKDOWN = """
# Pisos en venta en Madrid

[Piso en venta en Palomeras sureste, Madrid](https://www.fotocasa.es/es/comprar/vivienda/madrid-capital/palomeras-sureste/182746190/d)

110.000 €
1.803 €/m²

61 m² 2 habs. 1ª planta con ascensor
Bonito piso en Palomeras sureste ideal inversión.
"""

SAMPLE_PISOSCOM_MARKDOWN = """
# Casas y pisos en Valencia

[Piso en venta en Torrefiel](https://www.pisos.com/comprar/piso-torrefiel-46019-12345678/)

85.000 €
950 €/m²

3 habs. 78 m² 2ª planta sin ascensor
Ocasión en Torrefiel con excelente rentabilidad para inversores.
"""


def test_fotocasa_markdown_parser():
    from app.connectors.portal_parsers import FotocasaMarkdownParser
    listings = FotocasaMarkdownParser.parse_listings(SAMPLE_FOTOCASA_MARKDOWN, default_province="Madrid")
    assert len(listings) == 1
    item = listings[0]
    assert "182746190" in item["id"]
    assert item["listing_price"] == 110000.0
    assert item["surface_m2"] == 61.0
    assert item["rooms"] == 2
    assert item["has_elevator"] is True
    assert item["postal_code"] == "28018"
    assert item["census_tract_data"]["area_m2_price"] == 2300.0
    assert item["discount_vs_market"] > 20.0
    assert item["rental_yield"] > 7.0


def test_pisoscom_markdown_parser():
    from app.connectors.portal_parsers import PisosComMarkdownParser
    listings = PisosComMarkdownParser.parse_listings(SAMPLE_PISOSCOM_MARKDOWN, default_province="Valencia")
    assert len(listings) == 1
    item = listings[0]
    assert "12345678" in item["id"]
    assert item["listing_price"] == 85000.0
    assert item["surface_m2"] == 78.0
    assert item["rooms"] == 3
    assert item["has_elevator"] is False
    assert item["postal_code"] == "46019"
    assert item["census_tract_data"]["area_m2_price"] == 1700.0
    assert item["rental_yield"] > 7.0


def test_meso_market_price_by_postal_code():
    from app.connectors.portal_parsers import IdealistaMarkdownParser
    # Vallecas / Palomeras (debe ser 28018 y 2300 €/m², no promedio de 4500 €/m²)
    loc_vallecas = IdealistaMarkdownParser._resolve_location_and_kpis(
        "Piso en Benarraba, Palomeras sureste, Madrid", default_province="Madrid"
    )
    assert loc_vallecas["postal_code"] == "28018"
    assert loc_vallecas["area_m2_price"] == 2300.0
    assert "Vallecas" in loc_vallecas["district_label"]

    # Santa Eugenia (Villa de Vallecas 28031)
    loc_eugenia = IdealistaMarkdownParser._resolve_location_and_kpis(
        "Piso en venta en Calle de Fuentespina, Santa Eugenia", default_province="Madrid"
    )
    assert loc_eugenia["postal_code"] == "28031"
    assert loc_eugenia["area_m2_price"] == 2400.0

    # Salamanca Recoletos (28001)
    loc_salamanca = IdealistaMarkdownParser._resolve_location_and_kpis(
        "Piso señorial en Calle de Serrano, Recoletos, Madrid", default_province="Madrid"
    )
    assert loc_salamanca["postal_code"] == "28001"
    assert loc_salamanca["area_m2_price"] == 7500.0
