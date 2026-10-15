from app.engine.portal_strategy import PortalStrategyEngine
from app.connectors.portal_parsers import MilanunciosMarkdownParser, YaEncontreMarkdownParser
from app.engine.advisor_engine import AdvisorEngine


def test_detect_asset_type_rustico():
    asset = PortalStrategyEngine.detect_asset_type("Busca 20 fincas rusticas en Guadarrama", "Finca Rústica")
    assert asset == "RUSTICO_TERRENOS"

    asset_olivar = PortalStrategyEngine.detect_asset_type("Quiero comprar un olivar con pozo", None)
    assert asset_olivar == "RUSTICO_TERRENOS"


def test_detect_asset_type_particular():
    asset = PortalStrategyEngine.detect_asset_type("Pisos de particular sin comision de agencia", "Piso")
    assert asset == "PARTICULAR_DIRECTO"


def test_detect_asset_type_gangas():
    asset = PortalStrategyEngine.detect_asset_type("Oportunidades de banco con descuento o embargo", "Vivienda")
    assert asset == "GANGAS_DESCUENTO"


def test_detect_geography_madrid_vs_sierra():
    geo_capital = PortalStrategyEngine.detect_geography("Pisos en Chamberi o Salamanca", "Madrid", "Chamberi")
    assert geo_capital == "GRANDES_CAPITALES"

    geo_sierra = PortalStrategyEngine.detect_geography("Fincas en Guadalix de la Sierra", "Madrid", "Guadalix")
    assert geo_sierra == "RURAL_SIERRA"


def test_allocate_portal_quotas_sum():
    # Sierra de Madrid -> rústico
    quotas = PortalStrategyEngine.allocate_portal_quotas(
        total_count=20,
        query_text="Busca 20 fincas rusticas en la Sierra de Madrid",
        property_type="Finca Rústica",
        province="Madrid",
        zone="Guadalix"
    )
    assert sum(quotas.values()) == 20
    # Milanuncios y Habitaclia deben liderar el cupo
    assert quotas["Milanuncios"] >= quotas["Idealista"]
    assert quotas["Habitaclia"] >= quotas["Idealista"]
    assert quotas["Milanuncios"] >= 5

    # Madrid Centro -> BTL
    quotas_urbano = PortalStrategyEngine.allocate_portal_quotas(
        total_count=20,
        query_text="Pisos en Salamanca para alquilar",
        property_type="Piso",
        province="Madrid",
        zone="Salamanca"
    )
    assert sum(quotas_urbano.values()) == 20
    # Idealista debe liderar
    assert quotas_urbano["Idealista"] >= 7
    assert quotas_urbano["Fotocasa"] >= 4


def test_advisor_engine_allocate_portal_counts():
    quotas = AdvisorEngine.allocate_portal_counts(
        total_count=20,
        query_text="Fincas rusticas en Manzanares el Real",
        property_type="Finca Rústica",
        province="Madrid"
    )
    assert sum(quotas.values()) == 20
    assert "Milanuncios" in quotas
    assert "YaEncontré" in quotas


def test_milanuncios_parser_markdown():
    sample_md = """
    # Resultados de búsqueda en Milanuncios
    ![Foto finca Guadalix](https://img.milanuncios.com/fg/5123/45/51234567_1.jpg)
    [Finca rústica con vistas en Guadalix](https://www.milanuncios.com/fincas-rusticas-en-madrid/finca-en-guadalix-51234567.htm)
    Venta de particular a particular. 85.000 € finca rústica de 6.000 m2 con pozo y caseta de aperos.
    """
    items = MilanunciosMarkdownParser.parse_listings(sample_md, default_province="Madrid")
    assert len(items) == 1
    item = items[0]
    assert item["id"] == "MKT-MILANUNCIOS-51234567"
    assert item["listing_price"] == 85000.0
    assert item["primary_portal"] == "Milanuncios"
    assert item["source_type"] == "market"
    assert item["is_solar"] is True
    assert item["is_particular"] is True
    assert len(item["images"]) == 1


def test_yaencontre_parser_markdown():
    sample_md = """
    # Pisos en Madrid YaEncontré
    ![Foto piso Tetuán](https://images.yaencontre.com/inmuebles/foto_tetuan_88776655_1.jpg)
    [Piso reformado en Tetuán](https://www.yaencontre.com/venta/pisos/madrid/inmueble-88776655)
    145.000 € - 75 m² - 2 hab. Segunda planta exterior con ascensor.
    """
    items = YaEncontreMarkdownParser.parse_listings(sample_md, default_province="Madrid")
    assert len(items) == 1
    item = items[0]
    assert item["id"] == "MKT-YAENCONTRE-88776655"
    assert item["listing_price"] == 145000.0
    assert item["primary_portal"] == "YaEncontré"
    assert item["source_type"] == "market"
    assert item["surface_m2"] == 75.0
    assert len(item["images"]) == 1

