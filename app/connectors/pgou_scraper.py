"""
PGOU Urban Planning Connector & Gazette Monitor Module
Simulates and parses urban planning opportunities published in official provincial and regional gazettes
(BOCM, DOGC, BOJA, BOP) and national urban databases (SIU).
"""

from typing import List, Dict, Any

class PGOUScraper:
    """
    Scraper and AI PDF Processor connector for urban planning announcements,
    re-zonings, Partial Plans (Planes Parciales), and PGOU modifications.
    """

    def fetch_pgou_opportunities(self) -> List[Dict[str, Any]]:
        """
        Retrieves active urban planning development opportunities detected across
        official gazettes and municipal urban portals.
        """
        return [
            {
                "id": "PGOU-MAD-2026-001",
                "source_type": "pgou",
                "title": "Desarrollo Urbanístico - Plan Parcial Sector S-14 'Los Berrocales'",
                "address": "Avenida de los Berrocales s/n",
                "locality": "Madrid",
                "province": "Madrid",
                "lat": 40.3650,
                "lon": -3.5850,
                "strategy": "SUELO_DESARROLLO",
                "property_type": "SUELO_URBANIZABLE",
                "listing_price": 1250000.0,
                "estimated_reference_value": 3800000.0,
                "appraisal_value": 3500000.0,
                "discount_percentage": 67.1,
                "surface_m2": 45000.0,
                "ownership_percentage": 100.0,
                "final_score": 92.5,
                "score_components": {
                    "discount_score": 95.0,
                    "poi_score": 88.0,
                    "income_score": 92.0,
                    "demographic_score": 90.0
                },
                "census_tract_data": {
                    "district": "Vicálvaro - Los Berrocales",
                    "avg_household_income": 36500,
                    "avg_person_income": 16200,
                    "area_m2_price": 2800.0
                },
                "planning_status": "Proyecto de Urbanización Aprobado",
                "gazette_source": "BOCM (Boletín Oficial de la Comunidad de Madrid)",
                "gazette_code": "BOCM-20230530-127",
                "gazette_date": "2023-05-30",
                "gazette_url": "https://www.bocm.es/boletin/bocm-20230530-127",
                "buildability_m2": 52000.0,
                "proposed_land_use": "Residencial VPA / VPPO (1.2 m²t/m²s)",
                "proposed_land_use_type": "RESIDENCIAL_VPA",
                "urbanization_cost_m2s": 65.0,
                "total_urbanization_cost": 2925000.0,
                "land_repercussion_m2t": 80.29, # (1250000 + 2925000) / 52000
                "reparcelacion_status": "🟢 Junta de Compensación Constituida & Reparcelación Inscrita en Registro de la Propiedad (BOCM Núm. 16, 19/01/2023)",
                "reparcelacion_verified_free": True,
                "milestones": [
                    {"phase": "Aprobación Reparcelación (BOCM 16)", "status": "COMPLETED", "date": "01/2023", "timeframe": "Concluido", "uplift": "x1.25"},
                    {"phase": "Aprobación Urbanización (BOCM 127)", "status": "COMPLETED", "date": "05/2023", "timeframe": "Concluido", "uplift": "x1.85"},
                    {"phase": "Simultaneidad de Obras", "status": "CURRENT", "date": "06/2024", "timeframe": "En curso", "uplift": "x2.40"},
                    {"phase": "Licencia Directa / Obra Nueva", "status": "PENDING", "date": "12/2026", "timeframe": "3-6 meses", "uplift": "x3.00"}
                ],
                "description": "Aprobación definitiva del Proyecto de Urbanización del Ámbito UZPp 02.04 'Desarrollo del Este-Los Berrocales' (Expediente municipal 714/2003/03039, Presupuesto total: 782,8 M€). Publicado en el BOCM Núm. 127 de 30 de mayo de 2023."
            },
            {
                "id": "PGOU-BCN-2026-002",
                "source_type": "pgou",
                "title": "Convenio Urbanístico & Recalificación - Sector Can Batlló",
                "address": "Carrer de la Constitució 19",
                "locality": "Barcelona",
                "province": "Barcelona",
                "lat": 41.3685,
                "lon": 2.1380,
                "strategy": "SUELO_DESARROLLO",
                "property_type": "URBANO_EDIFICABLE",
                "listing_price": 890000.0,
                "estimated_reference_value": 2400000.0,
                "appraisal_value": 2200000.0,
                "discount_percentage": 62.9,
                "surface_m2": 3200.0,
                "ownership_percentage": 100.0,
                "final_score": 88.4,
                "score_components": {
                    "discount_score": 90.0,
                    "poi_score": 92.0,
                    "income_score": 85.0,
                    "demographic_score": 86.0
                },
                "census_tract_data": {
                    "district": "Sants-Montjuïc",
                    "avg_household_income": 34100,
                    "avg_person_income": 15800,
                    "area_m2_price": 3650.0
                },
                "planning_status": "MPGM Aprobada en Pleno Municipal",
                "gazette_source": "Ajuntament de Barcelona (Portal d'Informació Urbanística)",
                "gazette_code": "Expediente MPGM Can Batlló",
                "gazette_date": "2023-03-24",
                "gazette_url": "https://ajuntament.barcelona.cat/informaciourbanistica/cercador/es/",
                "buildability_m2": 7800.0,
                "proposed_land_use": "Residencial Libre Plurifamiliar (2.4 m²t/m²s)",
                "proposed_land_use_type": "RESIDENCIAL_LIBRE",
                "urbanization_cost_m2s": 42.0,
                "total_urbanization_cost": 134400.0,
                "land_repercussion_m2t": 131.33, # (890000 + 134400) / 7800
                "reparcelacion_status": "🟢 Proyecto de Reparcelación Aprobado en Pleno Municipal & En trámite de Asiento Registral",
                "reparcelacion_verified_free": True,
                "milestones": [
                    {"phase": "Aprobación Inicial MPGM", "status": "COMPLETED", "date": "05/2016", "timeframe": "Concluido", "uplift": "x1.25"},
                    {"phase": "Aprobación Definitiva en Pleno", "status": "COMPLETED", "date": "10/2017", "timeframe": "Concluido", "uplift": "x1.85"},
                    {"phase": "Inscripción Registral Fincas", "status": "CURRENT", "date": "11/2026", "timeframe": "2-4 meses", "uplift": "x2.40"},
                    {"phase": "Solicitud Licencia Obras", "status": "PENDING", "date": "03/2027", "timeframe": "6-8 meses", "uplift": "x3.00"}
                ],
                "description": "Aprobación de la Modificación Puntual del PGM en el ámbito de Can Batlló-Magòria (Districte de Sants-Montjuïc). Tramitado a través del Portal d'Informació Urbanística de l'Ajuntament de Barcelona."
            },
            {
                "id": "PGOU-SEV-2026-003",
                "source_type": "pgou",
                "title": "Desarrollo de Suelo Sector SUS-DBP-02 'Palmas Altas / Isla Natura'",
                "address": "Carretera Isla Menor Km 2.5",
                "locality": "Sevilla",
                "province": "Sevilla",
                "lat": 37.3310,
                "lon": -5.9750,
                "strategy": "SUELO_DESARROLLO",
                "property_type": "SUELO_URBANIZABLE",
                "listing_price": 450000.0,
                "estimated_reference_value": 1350000.0,
                "appraisal_value": 1200000.0,
                "discount_percentage": 66.7,
                "surface_m2": 18500.0,
                "ownership_percentage": 100.0,
                "final_score": 84.1,
                "score_components": {
                    "discount_score": 88.0,
                    "poi_score": 80.0,
                    "income_score": 82.0,
                    "demographic_score": 85.0
                },
                "census_tract_data": {
                    "district": "Bellavista - La Palmera",
                    "avg_household_income": 29800,
                    "avg_person_income": 13400,
                    "area_m2_price": 1950.0
                },
                "planning_status": "Plan Parcial y Convenio Aprobados",
                "gazette_source": "Gerencia de Urbanismo de Sevilla (Planeamiento y Gestión)",
                "gazette_code": "Sector SUS-DBP-02 Palmas Altas",
                "gazette_date": "2022-11-18",
                "gazette_url": "https://www.urbanismosevilla.org/",
                "buildability_m2": 21000.0,
                "proposed_land_use": "Residencial Libre Unifamiliar / Plurifamiliar",
                "proposed_land_use_type": "RESIDENCIAL_LIBRE",
                "urbanization_cost_m2s": 55.0,
                "total_urbanization_cost": 1017500.0,
                "land_repercussion_m2t": 69.88, # (450000 + 1017500) / 21000
                "reparcelacion_status": "🟡 Junta de Compensación en Constitución & Proyecto de Reparcelación en Redacción Técnica",
                "reparcelacion_verified_free": True,
                "milestones": [
                    {"phase": "Aprobación Plan Parcial SUS-DBP-02", "status": "COMPLETED", "date": "03/2019", "timeframe": "Concluido", "uplift": "x1.25"},
                    {"phase": "Convenio de Infraestructuras y Viario", "status": "COMPLETED", "date": "11/2022", "timeframe": "Concluido", "uplift": "x1.85"},
                    {"phase": "Aprobación Reparcelación", "status": "PENDING", "date": "04/2027", "timeframe": "8-12 meses", "uplift": "x2.40"},
                    {"phase": "Recepción Obras Urbanización", "status": "PENDING", "date": "11/2027", "timeframe": "14-18 meses", "uplift": "x3.00"}
                ],
                "description": "Ordenación y desarrollo urbanístico del sector SUS-DBP-02 'Palmas Altas / Isla Natura' (Distrito Bellavista-La Palmera) gestionado por la Gerencia de Urbanismo y Medio Ambiente del Ayuntamiento de Sevilla."
            },
            {
                "id": "PGOU-VAL-2026-004",
                "source_type": "pgou",
                "title": "Aprobación PAI - Sector NPR-4 'El Grau / Delta del Turia'",
                "address": "Carrer de les Moreres 45",
                "locality": "Valencia",
                "province": "Valencia",
                "lat": 39.4520,
                "lon": -0.3340,
                "strategy": "SUELO_DESARROLLO",
                "property_type": "URBANO_EDIFICABLE",
                "listing_price": 980000.0,
                "estimated_reference_value": 2900000.0,
                "appraisal_value": 2700000.0,
                "discount_percentage": 66.2,
                "surface_m2": 5400.0,
                "ownership_percentage": 100.0,
                "final_score": 90.1,
                "score_components": {
                    "discount_score": 92.0,
                    "poi_score": 89.0,
                    "income_score": 88.0,
                    "demographic_score": 91.0
                },
                "census_tract_data": {
                    "district": "Poblats Marítims - El Grau",
                    "avg_household_income": 32500,
                    "avg_person_income": 14900,
                    "area_m2_price": 2600.0
                },
                "planning_status": "PAI en Información Pública y Planeamiento",
                "gazette_source": "Ajuntament de València (Servicio de Planeamiento Urbanístico)",
                "gazette_code": "Sector NPR-4 Grao",
                "gazette_date": "2026-05-18",
                "gazette_url": "https://www.valencia.es/cas/urbanismo/planeamiento",
                "buildability_m2": 11200.0,
                "proposed_land_use": "Terciario / Comercial / Hotelero",
                "proposed_land_use_type": "TERCIARIO_INDUSTRIAL",
                "urbanization_cost_m2s": 38.0,
                "total_urbanization_cost": 205200.0,
                "land_repercussion_m2t": 105.82, # (980000 + 205200) / 11200
                "reparcelacion_status": "🟢 Alternativa Técnica PAI Admitida a Trámite & Exposición Pública Municipal",
                "reparcelacion_verified_free": True,
                "milestones": [
                    {"phase": "Admisión a Trámite Alternativa Técnica", "status": "COMPLETED", "date": "05/2026", "timeframe": "Concluido", "uplift": "x1.25"},
                    {"phase": "Periodo de Exposición Pública", "status": "COMPLETED", "date": "07/2026", "timeframe": "Concluido", "uplift": "x1.85"},
                    {"phase": "Aprobación Definitiva en Pleno", "status": "CURRENT", "date": "12/2026", "timeframe": "3-5 meses", "uplift": "x2.40"},
                    {"phase": "Licencia Directa Construcción", "status": "PENDING", "date": "04/2027", "timeframe": "6-9 meses", "uplift": "x3.00"}
                ],
                "description": "Tramitación del Programa de Actuación Integrada (PAI) del Sector NPR-4 'Grao' (Poblats Marítims) gestionado por el Servicio de Planeamiento del Ayuntamiento de València frente a la desembocadura del antiguo cauce del Turia."
            }
        ]
