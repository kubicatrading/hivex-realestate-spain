from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import UserDefinedType
from geoalchemy2 import Geometry
from datetime import datetime
import enum

class SafeGeometry(UserDefinedType):
    def __init__(self, geometry_type="GEOMETRY", srid=4326):
        self.geometry_type = geometry_type
        self.srid = srid
        self.underlying = Geometry(geometry_type=geometry_type, srid=srid)

    def column_expression(self, col):
        return col

@compiles(SafeGeometry, "sqlite")
def compile_safe_geo_sqlite(type_, compiler, **kw):
    return "TEXT"

@compiles(SafeGeometry)
def compile_safe_geo_default(type_, compiler, **kw):
    return f"geometry({type_.geometry_type}, {type_.srid})"

from app.db.session import Base

class StrategyType(str, enum.Enum):
    HOUSE_FLIPPING = "HOUSE_FLIPPING"
    LAND_DEVELOPMENT = "LAND_DEVELOPMENT"

class CensusSection(Base):
    __tablename__ = "census_sections"

    id = Column(Integer, primary_key=True, index=True)
    cusec = Column(String(10), unique=True, index=True, nullable=False)  # Código de Sección Censal INE (10 dígitos)
    municipality_code = Column(String(5), index=True)
    municipality_name = Column(String(100), index=True)
    province_name = Column(String(100), index=True)
    
    # KPIs INE
    avg_household_income = Column(Float, nullable=True)  # Renta media por hogar (€)
    avg_person_income = Column(Float, nullable=True)     # Renta media por persona (€)
    population_growth_rate = Column(Float, nullable=True) # Variación de población (%)
    
    # Geometría PostGIS (MultiPolygon EPSG:4326 WGS84)
    geom = Column(SafeGeometry("MULTIPOLYGON", 4326), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    parcels = relationship("CadastralParcel", back_populates="census_section")

class CadastralParcel(Base):
    __tablename__ = "cadastral_parcels"

    id = Column(Integer, primary_key=True, index=True)
    refcat = Column(String(20), unique=True, index=True, nullable=False) # Referencia Catastral (14 o 20 chars)
    census_section_id = Column(Integer, ForeignKey("census_sections.id"), nullable=True)
    
    address = Column(String(255), nullable=True)
    surface_m2 = Column(Float, nullable=True)             # Superficie gráfica / construida
    land_use = Column(String(50), nullable=True)              # Suelo urbano, rústico, residencial, etc.
    build_year = Column(Integer, nullable=True)               # Año de construcción
    
    reference_price_m2 = Column(Float, nullable=True)         # Valor fiscal / Precio ref. Catastro (€/m²)
    estimated_market_price = Column(Float, nullable=True)     # Precio mercado estimado (€ total)

    # PostGIS (Polygon/MultiPolygon EPSG:4326)
    geom = Column(SafeGeometry("GEOMETRY", 4326), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    census_section = relationship("CensusSection", back_populates="parcels")
    auctions = relationship("Auction", back_populates="parcel")

class Auction(Base):
    __tablename__ = "auctions"

    id = Column(Integer, primary_key=True, index=True)
    id_subasta = Column(String(50), unique=True, index=True, nullable=False) # Identificador BOE (ej. SUB-JA-2024-12345)
    source = Column(String(50), default="BOE_SUBASTAS") # BOE, Edictos, Concursos
    
    title = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    property_type = Column(String(50), nullable=True) # Vivienda, Solar, Finca Rústica, Garaje
    province = Column(String(100), nullable=True)
    locality = Column(String(100), nullable=True)
    address = Column(String(255), nullable=True)
    
    appraisal_value = Column(Float, nullable=True)     # Valor de tasación (€)
    starting_bid = Column(Float, nullable=True)        # Importe de salida / puja mínima (€)
    deposit_amount = Column(Float, nullable=True)      # Depósito requerido (€)
    
    refcat = Column(String(20), ForeignKey("cadastral_parcels.refcat"), nullable=True, index=True)
    status = Column(String(50), default="EJECUCION")   # EJECUCION, FINALIZADA, CANCELADA
    auction_start_date = Column(DateTime, nullable=True)
    auction_end_date = Column(DateTime, nullable=True)
    
    # Datos Urbanísticos para Solares / Terrenos
    zoning_classification = Column(String(150), nullable=True) # Calificación (ej. Suelo Urbano Consolidado SUC-R)
    urbanization_status = Column(String(200), nullable=True)   # Estado PGOU / Urbanización
    buildability_ratio = Column(String(100), nullable=True)    # Edificabilidad (ej. 0.8 m2t/m2s)
    permitted_uses = Column(String(150), nullable=True)        # Usos (ej. Residencial Colectivo / Unifamiliar)
    images_json = Column(Text, nullable=True)                  # Lista JSON de URLs de imágenes/fotos

    # Geolocalización del inmueble (Coordenadas WGS84 + Point EPSG:4326)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    location = Column(SafeGeometry("POINT", 4326), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    parcel = relationship("CadastralParcel", back_populates="auctions")
    opportunities = relationship("Opportunity", back_populates="auction")

class Opportunity(Base):
    __tablename__ = "opportunities"

    id = Column(Integer, primary_key=True, index=True)
    auction_id = Column(Integer, ForeignKey("auctions.id"), nullable=False)
    
    strategy = Column(Enum(StrategyType), nullable=False) # HOUSE_FLIPPING or LAND_DEVELOPMENT
    
    listing_price = Column(Float, nullable=False)       # Precio de salida en subasta (€)
    estimated_reference_value = Column(Float, nullable=False) # Valor estimado de mercado de la zona (€)
    discount_percentage = Column(Float, nullable=False) # Descuento calculado (ej. 0.42 = 42% por debajo de mercado)
    
    poi_score = Column(Float, default=0.0)             # Puntuación de servicios (OSM: transporte, colegios, etc.)
    income_score = Column(Float, default=0.0)          # Puntuación nivel adquisitivo (INE ADREH)
    overall_score = Column(Float, default=0.0)         # Score global de oportunidad (0 - 100)
    
    is_alert_sent = Column(Boolean, default=False)
    alert_sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    auction = relationship("Auction", back_populates="opportunities")
