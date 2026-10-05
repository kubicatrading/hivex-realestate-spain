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
    refcat = Column(String(50), unique=True, index=True, nullable=False) # Referencia Catastral (14, 20 o pseudo-ref)
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
    province = Column(String(100), nullable=True, index=True)
    locality = Column(String(100), nullable=True, index=True)
    address = Column(String(255), nullable=True)
    
    appraisal_value = Column(Float, nullable=True)     # Valor de tasación (€)
    starting_bid = Column(Float, nullable=True)        # Importe de salida / puja mínima (€)
    deposit_amount = Column(Float, nullable=True)      # Depósito requerido (€)
    
    refcat = Column(String(50), ForeignKey("cadastral_parcels.refcat"), nullable=True, index=True)
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
    
    strategy = Column(Enum(StrategyType), nullable=False, index=True) # HOUSE_FLIPPING or LAND_DEVELOPMENT
    listing_price = Column(Float, nullable=False)       # Precio de salida en subasta (€)
    estimated_reference_value = Column(Float, nullable=False) # Valor estimado de mercado de la zona (€)
    discount_percentage = Column(Float, nullable=False, index=True) # Descuento calculado (ej. 0.42 = 42% por debajo de mercado)
    
    poi_score = Column(Float, default=0.0)             # Puntuación de servicios (OSM: transporte, colegios, etc.)
    income_score = Column(Float, default=0.0)          # Puntuación nivel adquisitivo (INE ADREH)
    rental_yield = Column(Float, default=0.0)          # Rentabilidad bruta estimada (%)
    estimated_monthly_rent = Column(Float, default=0.0)# Alquiler mensual estimado (€)
    yield_score = Column(Float, default=0.0)           # Puntuación de rentabilidad (0 - 100)
    yield_color = Column(String(20), default="rojo")   # "verde", "amarillo", "naranja", "rojo"
    btl_score = Column(Float, nullable=True, default=None) # Score BTL (Buy to Let), None para solares
    overall_score = Column(Float, default=0.0)         # Score global de oportunidad (0 - 100)
    
    is_alert_sent = Column(Boolean, default=False)
    alert_sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    auction = relationship("Auction", back_populates="opportunities")

class PipelineSyncState(Base):
    __tablename__ = "pipeline_sync_states"

    id = Column(Integer, primary_key=True, index=True)
    sync_time = Column(DateTime, default=datetime.utcnow)
    new_auction_ids_json = Column(Text, default="[]")
    new_pgou_ids_json = Column(Text, default="[]")
    new_edicto_ids_json = Column(Text, default="[]")
    new_market_ids_json = Column(Text, default="[]")
    summary_json = Column(Text, default="{}")

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    salt = Column(String(64), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_admin = Column(Boolean, default=True, nullable=False)
    telegram_id = Column(String(50), unique=True, index=True, nullable=True)
    telegram_username = Column(String(100), index=True, nullable=True)
    favorites_json = Column(Text, default="[]")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = relationship("TelegramConversationMessage", back_populates="user")
    consultations = relationship("SavedConsultation", back_populates="user")

class TelegramConversationMessage(Base):
    __tablename__ = "telegram_conversation_messages"

    id = Column(Integer, primary_key=True, index=True)
    telegram_chat_id = Column(String(50), index=True, nullable=False)
    telegram_user_id = Column(String(50), index=True, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    role = Column(String(20), nullable=False)  # "user", "assistant", "system"
    content_type = Column(String(20), default="text")  # "text", "voice", "audio", "query_result"
    content = Column(Text, nullable=False)
    transcription = Column(Text, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="messages")

class SavedConsultation(Base):
    __tablename__ = "saved_consultations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    user_name = Column(String(100), nullable=False, default="Usuario Telegram")
    telegram_chat_id = Column(String(50), nullable=True)
    title = Column(String(255), nullable=False)  # Nombre de la alerta / consulta
    description = Column(Text, nullable=False)    # Prompt o texto original del mensaje/audio
    query_type = Column(String(50), default="SEARCH_OPPORTUNITIES") # SEARCH_OPPORTUNITIES, DISTRICT_ANALYSIS, ROI_BTL_CALC, SCORING_CROSSREF, SCHEDULED_ALERT, ADVISORY
    criteria_json = Column(Text, default="{}")    # JSON con criterios parseados
    matched_opportunity_ids_json = Column(Text, default="[]") # IDs de oportunidades encontradas
    matched_count = Column(Integer, default=0)
    ai_summary = Column(Text, nullable=True)      # Resumen / respuesta del asesor inmobiliario
    is_alert = Column(Boolean, default=False)
    alert_frequency = Column(String(20), default="DAILY") # INSTANT, DAILY, WEEKLY
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="consultations")


class CompanyKnowledgeBase(Base):
    """
    Base de Conocimiento Corporativa de HIVEX.
    Almacena y capitaliza inteligencia de mercado (precios/m², rentas, yields, planes urbanísticos
    y diagnósticos) obtenida internamente o mediante prospección exterior con Gemini.
    Permite responder futuras consultas sin volver a incurrir en costes externos.
    """
    __tablename__ = "company_knowledge_base"

    id = Column(Integer, primary_key=True, index=True)
    query_key = Column(String(150), unique=True, index=True, nullable=False) # ej: "madrid:carabanchel", "valencia:ruzafa"
    province = Column(String(100), index=True, nullable=False)
    locality = Column(String(100), index=True, nullable=True)
    zone_or_district = Column(String(100), index=True, nullable=True)
    postal_codes_csv = Column(String(100), nullable=True) # ej: "28019,28025,28054"
    avg_price_sale_sqm = Column(Float, nullable=True)
    avg_rent_sqm = Column(Float, nullable=True)
    gross_yield_pct = Column(Float, nullable=True)
    discount_vs_market_pct = Column(Float, nullable=True)
    urban_planning_summary = Column(Text, nullable=True)
    market_diagnosis = Column(Text, nullable=True)
    source = Column(String(50), default="HIVEX_INTERNAL") # "HIVEX_INTERNAL", "GEMINI_RESEARCH", "OFFICIAL_DATA"
    raw_payload_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MesoMarketTable2x2(Base):
    """
    Tabla Meso de Precios de Mercado 2x2 por Código Postal.
    Eje Y (Clasificación del suelo): [URBANO, RÚSTICO]
    Eje X (Tipología del bien):       [INMUEBLE, SOLAR]
    Indicadores por zonas: precio compra/m2, renta/m2, yield BTL (%), variación trimestral.
    Persistido con fecha de actualización para garantizar ciclo de vida fresco (TTL 2 meses / 60 días).
    """
    __tablename__ = "meso_market_table_2x2"

    id = Column(Integer, primary_key=True, index=True)
    postal_code = Column(String(10), unique=True, index=True, nullable=False)
    zone_label = Column(String(150), nullable=True) # ej: "Carabanchel - Vista Alegre"
    province = Column(String(100), index=True, nullable=False)
    locality = Column(String(100), index=True, nullable=True)

    # Matriz 2x2 (€/m²)
    urbano_inmueble = Column(Float, nullable=False, default=1800.0)
    urbano_solar = Column(Float, nullable=False, default=600.0)
    rustico_inmueble = Column(Float, nullable=False, default=400.0)
    rustico_solar = Column(Float, nullable=False, default=20.0)

    # Indicadores de mercado por zonas e Índices de Referencia MIVAU / INE
    mivau_rent_sqm_min = Column(Float, nullable=True) # Rango inferior oficial MIVAU
    avg_rent_sqm = Column(Float, nullable=True, default=14.0) # Renta media MIVAU/INE
    mivau_rent_sqm_max = Column(Float, nullable=True) # Rango superior oficial MIVAU
    gross_yield_pct = Column(Float, nullable=True, default=6.5) # Yield BTL bruto %
    btl_score = Column(Float, nullable=True, default=80.0) # Score cuantitativo BTL (0-100)
    yield_rating = Column(String(20), nullable=True, default="naranja") # Semáforo HIVEX (verde, amarillo, naranja, rojo)
    quarterly_variation_pct = Column(Float, nullable=True, default=0.0)
    source = Column(String(50), default="MIVAU_INE_2X2")

    # Activos verificados en el catálogo local y representatividad
    verified_active_assets_count = Column(Integer, default=0) # Número de oportunidades activas verificadas en catálogo
    avg_catalog_discount_pct = Column(Float, default=0.0) # Descuento medio vs mercado en catálogo
    is_statistically_representative = Column(Boolean, default=False) # Representatividad estadística verificada

    # Indicadores Sociodemográficos INE (ADREH) y Equipamiento Urbano (POIs) por CP
    ine_avg_income_household = Column(Float, nullable=True, default=34000.0) # Renta media por hogar anual (€) INE
    poi_density_score = Column(Float, nullable=True, default=75.0) # Densidad de servicios y POIs OSM (0-100)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CronExecutionLog(Base):
    """
    Registro histórico y estado de salud de ejecución de los Crons del sistema.
    Permite auditar el estado de salud de los crons diarios y bimensuales.
    """
    __tablename__ = "cron_execution_logs"

    id = Column(Integer, primary_key=True, index=True)
    cron_name = Column(String(100), index=True, nullable=False) # "BIMONTHLY_MESO_REFRESH", "DAILY_PIPELINE", etc.
    status = Column(String(50), default="SUCCESS") # "SUCCESS", "FAILED", "RUNNING"
    details_json = Column(Text, default="{}")
    duration_seconds = Column(Float, default=0.0)
    executed_at = Column(DateTime, default=datetime.utcnow, index=True)





