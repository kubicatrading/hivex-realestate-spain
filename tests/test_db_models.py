import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.session import Base
from app.db.models import Auction, Opportunity, StrategyType

# Usar SQLite en memoria para tests rápidos de ORM sin PostGIS si no hay DB activa
SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///:memory:"

def test_auction_and_opportunity_models():
    engine = create_engine(SQLALCHEMY_TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    # Ignorar columnas PostGIS para test simple de SQLite
    SessionTest = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    # Simular creación de objetos ORM
    auction = Auction(
        id_subasta="SUB-TEST-001",
        title="Piso en prueba",
        property_type="Vivienda",
        starting_bid=100000.0,
        appraisal_value=200000.0
    )
    
    assert auction.id_subasta == "SUB-TEST-001"
    assert auction.starting_bid == 100000.0
