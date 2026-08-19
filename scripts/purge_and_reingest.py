import sys
import logging
from sqlalchemy import text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reingest")

def main():
    logger.info("Initializing DB session...")
    from app.db.session import SessionLocal, engine
    db = SessionLocal()

    logger.info("Purging old database records from opportunities and auctions...")
    try:
        db.execute(text("DELETE FROM opportunities;"))
        db.execute(text("DELETE FROM auctions;"))
        db.commit()
        logger.info("Database successfully purged.")
    except Exception as e:
        logger.error(f"Error purging DB: {e}")
        db.rollback()

    logger.info("Starting live BOE Subastas scraper...")
    from app.connectors.boe_scraper import BOESubastasScraper
    from app.engine.scoring_engine import OpportunityScoringEngine

    scraper = BOESubastasScraper()
    real_items = scraper.scrape_live_auctions(limit=25)
    logger.info(f"Retrieved {len(real_items)} real live BOE subastas.")

    if not real_items:
        logger.warning("No live subastas retrieved.")
        return

    logger.info("Processing and scoring real subastas...")
    engine_scoring = OpportunityScoringEngine(db)
    opps = engine_scoring.process_and_score_auctions(real_items)
    logger.info(f"DONE! Processed and registered {len(opps)} real live opportunities in DB.")

if __name__ == "__main__":
    main()
