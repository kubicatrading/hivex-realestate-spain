import os
from fastapi import FastAPI, Depends, Query, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from geoalchemy2.shape import to_shape
from typing import List, Optional

from app.db.session import get_db, Base, engine
from app.db.models import Opportunity, Auction, StrategyType
from app.connectors.boe_scraper import BOESubastasScraper
from app.engine.scoring_engine import OpportunityScoringEngine
from app.services.notifier import TelegramNotifier
from app.core.config import settings
from app.core.auth import (
    verify_credentials,
    create_access_token,
    get_current_user
)

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend API y Dashboard para monitoreo de mercado inmobiliario off-market, subastas del BOE, Catastro, INE y OSM.",
    version="1.0.0"
)

class LoginRequest(BaseModel):
    login: str
    password: str

# Coordinates fallback map for Spanish provinces/cities
PROVINCE_COORDS = {
    "madrid": (40.4168, -3.7038),
    "barcelona": (41.3851, 2.1734),
    "málaga": (36.7213, -4.4214),
    "malaga": (36.7213, -4.4214),
    "valencia": (39.4699, -0.3763),
    "sevilla": (37.3891, -5.9845),
    "zaragoza": (41.6488, -0.8896),
    "alicante": (38.3452, -0.4810),
    "bizkaia": (43.2630, -2.9350),
    "balears": (39.5696, 2.6502),
    "las palmas": (28.1235, -15.4363)
}

# Calculate absolute path to project root
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
static_dir = os.path.join(BASE_DIR, "static")

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.on_event("startup")
def startup_event():
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        print(f"Advertencia al crear tablas en startup: {e}")

@app.get("/")
def serve_dashboard():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        "status": "online",
        "app": settings.PROJECT_NAME,
        "environment": settings.ENV
    }

@app.get("/api/v1/health")
def health_check():
    return {
        "status": "online",
        "app": settings.PROJECT_NAME,
        "environment": settings.ENV
    }

@app.post("/api/v1/auth/login")
def login(request: LoginRequest):
    """Autentica un usuario por nombre de usuario O correo electrónico."""
    user = verify_credentials(request.login, request.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario/Email o contraseña incorrectos"
        )
    
    access_token = create_access_token(data={"sub": user["username"], "email": user["email"]})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }

@app.get("/api/v1/auth/me")
def get_me(current_user: dict = Depends(get_current_user)):
    """Verifica el estado de la sesión activa."""
    return {"status": "authenticated", "user": current_user}

@app.post("/api/v1/pipeline/run")
def trigger_ingestion_pipeline(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Ejecuta la captura de subastas y actualización de oportunidades en tiempo real."""
    scraper = BOESubastasScraper()
    raw_auctions = scraper.fetch_mock_auctions()
    
    scoring_engine = OpportunityScoringEngine(db_session=db)
    opportunities = scoring_engine.process_and_score_auctions(raw_auctions)

    notifier = TelegramNotifier()
    alerts_sent = 0
    for opp in opportunities:
        if not opp.is_alert_sent:
            if notifier.send_opportunity_alert(opp):
                opp.is_alert_sent = True
                alerts_sent += 1

    db.commit()

    return {
        "status": "success",
        "processed_auctions": len(raw_auctions),
        "detected_opportunities": len(opportunities),
        "alerts_sent": alerts_sent
    }

@app.get("/api/v1/opportunities")
def get_opportunities(
    strategy: Optional[StrategyType] = None,
    min_discount: Optional[float] = Query(0.30, ge=0.0, le=1.0),
    province: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Consulta la lista de oportunidades filtradas por estrategia, descuento y provincia."""
    results = []
    try:
        query = db.query(Opportunity).outerjoin(Auction)

        if strategy:
            query = query.filter(Opportunity.strategy == strategy)
        if min_discount is not None:
            query = query.filter(Opportunity.discount_percentage >= min_discount)
        if province:
            query = query.filter(Auction.province.ilike(f"%{province}%"))

        opportunities = query.order_by(Opportunity.discount_percentage.desc()).all()

        for opp in opportunities:
            auc = opp.auction
            strategy_val = opp.strategy.value if hasattr(opp.strategy, "value") else str(opp.strategy)
            
            # Extract coordinates from geometry or fallback by province
            lat, lon = None, None
            if auc and auc.location_geom:
                try:
                    point = to_shape(auc.location_geom)
                    lat, lon = point.y, point.x
                except Exception:
                    pass
            
            if (not lat or not lon) and auc and auc.province:
                prov_clean = auc.province.strip().lower()
                if prov_clean in PROVINCE_COORDS:
                    lat, lon = PROVINCE_COORDS[prov_clean]
                else:
                    lat, lon = (40.4168, -3.7038) # Default Spain

            results.append({
                "id": opp.id,
                "id_subasta": auc.id_subasta if auc else "N/A",
                "strategy": strategy_val,
                "title": auc.title if auc else "N/A",
                "province": auc.province if auc else "N/A",
                "locality": auc.locality if auc else "N/A",
                "listing_price": opp.listing_price,
                "estimated_reference_value": opp.estimated_reference_value,
                "discount_percentage": round(opp.discount_percentage * 100, 2),
                "potential_gross_profit": round(opp.estimated_reference_value - opp.listing_price, 2),
                "overall_score": opp.overall_score,
                "poi_score": opp.poi_score,
                "lat": lat,
                "lon": lon,
                "boe_url": f"https://subastas.boe.es/detalleSubasta.php?idSub={auc.id_subasta}" if auc else ""
            })
    except Exception as e:
        print(f"Error consultando oportunidades: {e}")

    return {
        "total": len(results),
        "opportunities": results
    }
