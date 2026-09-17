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
    
    # Inmueble 1 (Goya)
    item1 = listings[0]
    assert item1["id"] == "MKT-IDEALISTA-112270818"
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

    # Inmueble 2 (Malasaña)
    item2 = listings[1]
    assert item2["id"] == "MKT-IDEALISTA-111433413"
    assert item2["listing_price"] == 750000.0
    assert item2["original_listing_price"] == 798000.0
    assert item2["rooms"] == 2
    assert item2["surface_m2"] == 102.0
    assert item2["publications"][0]["agency"] == "Gilmar Centro"


def test_habitaclia_markdown_parser():
    listings = HabitacliaMarkdownParser.parse_listings(SAMPLE_HABITACLIA_MARKDOWN, default_province="Barcelona")
    assert len(listings) == 1
    item = listings[0]
    assert "24589012" in item["id"]
    assert item["listing_price"] == 320000.0
    assert item["locality"] == "Barcelona"
    assert item["lat"] is not None and item["lon"] is not None
