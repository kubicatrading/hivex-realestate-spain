import pytest
from app.services.alert_engine import RealEstateAlertEngine

def test_select_four_opportunities():
    engine = RealEstateAlertEngine()
    
    mock_market = [
        {
            "id": "MKT-1",
            "title": "Piso en Benarraba, Madrid",
            "province": "Madrid",
            "locality": "Madrid",
            "property_type": "Piso",
            "strategy": "BUY_TO_LET",
            "min_price": 110000.0,
            "monthly_rent": 885.0,
            "rental_yield": 8.8,
            "btl_score": 100.0,
            "overall_score": 90.0,
            "discount_vs_market": 62.4,
            "potential_gross_profit": 182800.0,
            "has_pgou_synergy": False
        },
        {
            "id": "MKT-2",
            "title": "Chalet en Aravaca, Madrid",
            "province": "Madrid",
            "locality": "Madrid",
            "property_type": "Chalet",
            "strategy": "HOUSE_FLIPPING",
            "min_price": 250000.0,
            "overall_score": 95.0,
            "discount_vs_market": 45.0,
            "potential_gross_profit": 120000.0,
            "has_pgou_synergy": False
        },
        {
            "id": "MKT-3",
            "title": "Edificio Residencial en Vicálvaro",
            "province": "Madrid",
            "locality": "Madrid",
            "property_type": "Edificio",
            "strategy": "HOUSE_FLIPPING",
            "min_price": 350000.0,
            "overall_score": 88.0,
            "discount_vs_market": 40.0,
            "potential_gross_profit": 150000.0,
            "has_pgou_synergy": True,
            "pgou_title": "Sector UZPp 02.04 Los Berrocales",
            "pgou_sector": "Vicálvaro"
        },
        {
            "id": "MKT-4",
            "title": "Solar Urbanizable en Los Ahijones",
            "province": "Madrid",
            "locality": "Madrid",
            "property_type": "Solar",
            "strategy": "LAND_DEVELOPMENT",
            "min_price": 180000.0,
            "property_m2_price": 450.0,
            "overall_score": 85.0,
            "discount_percentage": 50.0,
            "has_pgou_synergy": True,
            "pgou_title": "Sector UZP 2.03 Los Ahijones"
        }
    ]

    selected = engine.select_four_opportunities(mock_market, force_all=True)
    assert len(selected) == 4
    
    titles = [t[0] for t in selected]
    assert "ALERTA PRECIO BTL MADRID" in titles
    assert "ALERTA DTO. MADRID" in titles
    assert "ALERTA INMUEBLE PGOU" in titles
    assert "ALERTA SOLAR PGOU" in titles

    # Test single opportunity alert card builder
    btl_tuple = next(item for item in selected if item[0] == "ALERTA PRECIO BTL MADRID")
    card_msg = engine.build_single_opportunity_alert(btl_tuple[0], btl_tuple[1], btl_tuple[2])
    
    assert "🎯 *ALERTA PRECIO BTL MADRID*" in card_msg
    assert "110.000 €" in card_msg
    assert "Renta & BTL:" in card_msg
    assert "885 €/mes" in card_msg
    assert "100/100 pts BTL 🟢" in card_msg
    assert "Descuento vs Mercado:" in card_msg

def test_cockpit_health_message_structure():
    engine = RealEstateAlertEngine(bot_token="test_token", chat_id="12345")
    # Simulation without real DB connection
    res = engine.send_cockpit_health_alert(db=None)
    assert res is not None
    msg = res["message"]
    assert "ESTADO DEL SERVIDOR (VERCEL)" in msg
    assert "Timeout" in msg
    assert "ESTADO DE LA BASE DE DATOS" in msg
    assert "ESTADO DE LA PLATAFORMA / OPORTUNIDADES" in msg
    assert "ESTADO DE SINCRONIZACIÓN Y CRONS" in msg
