import argparse
import sys
import logging
from sqlalchemy import text

from app.db.session import engine, SessionLocal, Base
from app.connectors.boe_scraper import BOESubastasScraper
from app.engine.scoring_engine import OpportunityScoringEngine
from app.services.notifier import TelegramNotifier
from app.db.models import Opportunity

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def init_db():
    """Crea la extensión PostGIS si no existe y genera todas las tablas en la base de datos."""
    logger.info("Inicializando la base de datos PostgreSQL + PostGIS...")
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
            conn.commit()
        Base.metadata.create_all(bind=engine)
        logger.info("¡Base de datos y tablas creadas exitosamente!")
    except Exception as e:
        logger.error(f"Error inicializando la base de datos: {e}")

def run_ingestion():
    """Ejecuta el pipeline completo de captura, enriquecimiento, scoring y alertas."""
    logger.info("Iniciando pipeline de captura de subastas y cálculo de KPIs...")
    db = SessionLocal()
    try:
        scraper = BOESubastasScraper()
        raw_auctions = scraper.fetch_mock_auctions()
        
        engine_service = OpportunityScoringEngine(db_session=db)
        opportunities = engine_service.process_and_score_auctions(raw_auctions)

        notifier = TelegramNotifier()
        for opp in opportunities:
            if not opp.is_alert_sent:
                sent = notifier.send_opportunity_alert(opp)
                opp.is_alert_sent = True
                db.commit()

        logger.info(f"Pipeline finalizado. Se han procesado {len(raw_auctions)} subastas y detectado {len(opportunities)} oportunidades.")
    finally:
        db.close()

def list_opportunities():
    """Muestra un resumen en consola de todas las oportunidades detectadas."""
    db = SessionLocal()
    try:
        opps = db.query(Opportunity).all()
        print("\n" + "="*80)
        print(f"HIVEX REAL ESTATE - LISTA DE OPORTUNIDADES DETECTADAS ({len(opps)})")
        print("="*80)
        for opp in opps:
            auc = opp.auction
            print(f"ID: {opp.id} | Subasta: {auc.id_subasta} | Estrategia: {opp.strategy}")
            print(f"   Ubicación: {auc.locality}, {auc.province}")
            print(f"   Precio Salida: {opp.listing_price:,.0f}€ | Estimado Mercado: {opp.estimated_reference_value:,.0f}€")
            print(f"   Descuento: {opp.discount_percentage*100:.1f}% | Score: {opp.overall_score}/100")
            print("-" * 80)
    finally:
        db.close()

def main():
    parser = argparse.ArgumentParser(description="HIVEX Real Estate Spain CLI Tool")
    parser.add_argument("command", choices=["init-db", "run-ingestion", "list-opportunities", "test-alert"])

    args = parser.parse_args()

    if args.command == "init-db":
        init_db()
    elif args.command == "run-ingestion":
        run_ingestion()
    elif args.command == "list-opportunities":
        list_opportunities()
    elif args.command == "test-alert":
        db = SessionLocal()
        try:
            opp = db.query(Opportunity).first()
            if opp:
                notifier = TelegramNotifier()
                notifier.send_opportunity_alert(opp)
            else:
                print("No hay oportunidades en BD. Ejecuta primero 'python -m app.cli run-ingestion'")
        finally:
            db.close()

if __name__ == "__main__":
    main()
