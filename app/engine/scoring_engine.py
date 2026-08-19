import logging
from typing import List, Dict, Any
from sqlalchemy.orm import Session

from app.db.models import Auction, Opportunity, CadastralParcel, CensusSection
from app.connectors.boe_scraper import BOESubastasScraper
from app.connectors.catastro_client import CatastroClient
from app.connectors.ine_client import INEClient
from app.connectors.osm_client import OSMOverpassClient
from app.engine.kpi_calculator import KPICalculator
from app.core.config import settings

logger = logging.getLogger(__name__)

class OpportunityScoringEngine:
    """
    Motor principal de inteligencia de HIVEX.
    Procesa subastas/inmuebles detectados, cruza información alfanumérica y geográfica,
    calcula la desviación de precio y registra oportunidades de inversión elegibles.
    """

    def __init__(self, db_session: Session):
        self.db = db_session
        self.catastro = CatastroClient()
        self.ine = INEClient()
        self.osm = OSMOverpassClient()

    def process_and_score_auctions(self, raw_auctions: List[Dict[str, Any]]) -> List[Opportunity]:
        """
        Procesa un conjunto de subastas extraídas, calcula sus KPIs y guarda
        las oportunidades que superen el umbral mínimo de descuento (ej. 30%).
        """
        detected_opportunities = []

        for item in raw_auctions:
            try:
                auction_id = item["id_subasta"]
                
                # Check if auction already processed
                existing = self.db.query(Auction).filter(Auction.id_subasta == auction_id).first()
                import json
                images_list = item.get("images", [])
                images_json_str = json.dumps(images_list) if images_list else None

                if not existing:
                    # Crear registro de subasta
                    existing = Auction(
                        id_subasta=auction_id,
                        source=item.get("source", "BOE_SUBASTAS"),
                        title=item.get("title"),
                        description=item.get("description"),
                        property_type=item.get("property_type", "Vivienda"),
                        province=item.get("province"),
                        locality=item.get("locality"),
                        address=item.get("address"),
                        appraisal_value=item.get("appraisal_value", 0.0),
                        starting_bid=item.get("starting_bid", 0.0),
                        deposit_amount=item.get("deposit_amount", 0.0),
                        refcat=item.get("refcat"),
                        lat=item.get("lat"),
                        lon=item.get("lon"),
                        zoning_classification=item.get("zoning_classification"),
                        urbanization_status=item.get("urbanization_status"),
                        buildability_ratio=item.get("buildability_ratio"),
                        permitted_uses=item.get("permitted_uses"),
                        images_json=images_json_str,
                        status=item.get("status", "EJECUCION")
                    )
                    self.db.add(existing)
                    self.db.commit()
                    self.db.refresh(existing)
                else:
                    # Actualizar datos enriquecidos si ya existía
                    existing.address = item.get("address") or existing.address
                    existing.zoning_classification = item.get("zoning_classification") or existing.zoning_classification
                    existing.urbanization_status = item.get("urbanization_status") or existing.urbanization_status
                    existing.buildability_ratio = item.get("buildability_ratio") or existing.buildability_ratio
                    existing.permitted_uses = item.get("permitted_uses") or existing.permitted_uses
                    if images_json_str:
                        existing.images_json = images_json_str
                    self.db.commit()

                # 1. Enriquecer con datos del Catastro
                refcat = item.get("refcat") or f"ES_{auction_id}"
                cat_data = self.catastro.get_parcel_details(refcat)

                # 2. Enriquecer con datos del INE
                ine_data = self.ine.get_census_section_stats(
                    province=item.get("province", "Madrid"),
                    locality=item.get("locality", "Madrid")
                )

                # 3. Enriquecer con datos de POIs (OpenStreetMap)
                lat = item.get("lat", 40.4168)
                lon = item.get("lon", -3.7038)
                poi_data = self.osm.get_poi_metrics(lat, lon, radius_meters=500)

                # 4. Cálculo de KPIs
                strategy = KPICalculator.determine_strategy(item.get("property_type", "Vivienda"))
                
                listing_price = existing.starting_bid if existing.starting_bid > 0 else existing.appraisal_value
                
                estimated_market_value = KPICalculator.calculate_estimated_market_value(
                    surface_m2=cat_data["surface_m2"],
                    reference_price_m2=cat_data["reference_price_m2"],
                    strategy=strategy
                )

                discount_pct = KPICalculator.calculate_discount_percentage(
                    listing_price=listing_price,
                    estimated_market_value=estimated_market_value
                )

                overall_score = KPICalculator.calculate_overall_opportunity_score(
                    discount_percentage=discount_pct,
                    poi_score=poi_data["poi_score"],
                    income_amount=ine_data["avg_household_income"],
                    population_growth=ine_data["population_growth_rate"]
                )

                logger.info(
                    f"Subasta {auction_id}: Precio salida={listing_price}€, Mercado est.={estimated_market_value}€, "
                    f"Descuento={discount_pct * 100:.1f}%, Score={overall_score}"
                )

                # 5. Filtrar según umbral de descuento
                if discount_pct >= settings.MIN_DISCOUNT_THRESHOLD:
                    existing_opp = self.db.query(Opportunity).filter(Opportunity.auction_id == existing.id).first()
                    if existing_opp:
                        existing_opp.strategy = strategy
                        existing_opp.listing_price = listing_price
                        existing_opp.estimated_reference_value = estimated_market_value
                        existing_opp.discount_percentage = discount_pct
                        existing_opp.poi_score = poi_data["poi_score"]
                        existing_opp.income_score = round(ine_data["avg_household_income"] / 500.0, 2)
                        existing_opp.overall_score = overall_score
                        opportunity = existing_opp
                    else:
                        opportunity = Opportunity(
                            auction_id=existing.id,
                            strategy=strategy,
                            listing_price=listing_price,
                            estimated_reference_value=estimated_market_value,
                            discount_percentage=discount_pct,
                            poi_score=poi_data["poi_score"],
                            income_score=round(ine_data["avg_household_income"] / 500.0, 2),
                            overall_score=overall_score,
                            is_alert_sent=False
                        )
                        self.db.add(opportunity)
                    
                    self.db.flush()
                    self.db.commit()
                    detected_opportunities.append(opportunity)

            except Exception as e:
                logger.error(f"Error evaluando subasta {item.get('id_subasta')}: {e}", exc_info=True)
                self.db.rollback()

        return detected_opportunities
