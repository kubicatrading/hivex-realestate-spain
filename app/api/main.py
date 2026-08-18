from fastapi import FastAPI, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.session import get_db, Base, engine
from app.db.models import Opportunity, Auction, StrategyType
from app.connectors.boe_scraper import BOESubastasScraper
from app.engine.scoring_engine import OpportunityScoringEngine
from app.services.notifier import TelegramNotifier
from app.core.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend API para monitoreo de mercado inmobiliario off-market, subastas del BOE, Catastro, INE y OSM.",
    version="1.0.0"
)

@app.on_event("startup")
def startup_event():
    # Asegurar creación de tablas al arrancar la API
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        print(f"Advertencia al crear tablas en startup: {e}")

@app.get("/")
def health_check():
    return {
        "status": "online",
        "app": settings.PROJECT_NAME,
        "environment": settings.ENV,
        "min_discount_threshold": f"{settings.MIN_DISCOUNT_THRESHOLD * 100:.0f}%"
    }

@app.post("/api/v1/pipeline/run")
def trigger_ingestion_pipeline(db: Session = Depends(get_db)):
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
    db: Session = Depends(get_db)
):
    """Consulta la lista de oportunidades filtradas por estrategia, descuento y provincia."""
    query = db.query(Opportunity).join(Auction)

    if strategy:
        query = query.filter(Opportunity.strategy == strategy)
    if min_discount:
        query = query.filter(Opportunity.discount_percentage >= min_discount)
    if province:
        query = query.filter(Auction.province.ilike(f"%{province}%"))

    opportunities = query.order_by(Opportunity.discount_percentage.desc()).all()

    results = []
    for opp in opportunities:
        auc = opp.auction
        results.append({
            "id": opp.id,
            "id_subasta": auc.id_subasta,
            "strategy": opp.strategy,
            "title": auc.title,
            "province": auc.province,
            "locality": auc.locality,
            "listing_price": opp.listing_price,
            "estimated_reference_value": opp.estimated_reference_value,
            "discount_percentage": round(opp.discount_percentage * 100, 2),
            "potential_gross_profit": round(opp.estimated_reference_value - opp.listing_price, 2),
            "overall_score": opp.overall_score,
            "poi_score": opp.poi_score,
            "boe_url": f"https://subastas.boe.es/detalleSubasta.php?idSub={auc.id_subasta}"
        })

    return {
        "total": len(results),
        "opportunities": results
    }
