import os
import json
import pytest
from unittest.mock import patch, MagicMock

from app.db.session import is_production_environment, init_database_engine, get_db
from app.services.photos_backfill import PhotosBackfillWorker
from app.engine.advisor_engine import AdvisorEngine


def test_production_environment_detection():
    assert is_production_environment({"VERCEL": "1"}) is True
    assert is_production_environment({"VERCEL_ENV": "production"}) is True
    assert is_production_environment({"ENV": "production"}) is True
    assert is_production_environment({"ENVIRONMENT": "production"}) is True
    assert is_production_environment({"HIVEX_ENV": "production"}) is True
    assert is_production_environment({}) is False


def test_production_strictly_prohibits_sqlite_url():
    """En producción está terminantemente prohibido usar SQLite; debe lanzar RuntimeError."""
    with pytest.raises(RuntimeError, match="PROHIBIDO consultar SQLite en el entorno de PRODUCCIÓN"):
        init_database_engine(raw_url="sqlite:///./hivex_local.db", force_prod=True)


def test_production_raises_error_when_postgres_unreachable():
    """En producción, si PostgreSQL/Supabase falla, NO debe hacer fallback a SQLite sino lanzar RuntimeError."""
    with pytest.raises(RuntimeError, match="PROHIBIDO el fallback a SQLite en el entorno de PRODUCCIÓN"):
        init_database_engine(
            raw_url="postgresql://invalid_user:invalid_pass@127.0.0.1:59999/nonexistent_db",
            force_prod=True,
        )


def test_get_db_blocks_sqlite_in_production(monkeypatch):
    """get_db() debe abortar inmediatamente si detecta dialecto sqlite estando en producción."""
    monkeypatch.setenv("VERCEL", "1")
    fake_engine = MagicMock()
    fake_engine.dialect.name = "sqlite"
    monkeypatch.setattr("app.db.session.engine", fake_engine)

    gen = get_db()
    with pytest.raises(RuntimeError, match="PROHIBIDO consultar SQLite en el entorno de PRODUCCIÓN"):
        next(gen)


def test_non_market_streetview_rule_in_hivex_and_external():
    """
    Tanto oportunidades existentes en HIVEX como oportunidades que vienen de fuera (BOE/subastas/pgou/edictos)
    deben recibir su foto de fachada de Google Street View si no tienen fotos o si tenían ortofotos de Catastro.
    """
    # 1. Oportunidad no-market con coordenadas (ej. existente en HIVEX o con geocodificación)
    opp_coords = {
        "id": "SUB-JA-2026-999001",
        "channel": "subastas",
        "title": "Subasta Judicial Vivienda en Calle Serrano 45, Madrid",
        "address": "Calle Serrano 45",
        "locality": "Madrid",
        "province": "Madrid",
        "lat": 40.4265,
        "lon": -3.6865,
        "images": ["https://ovc.catastro.meh.es/Cartografia/WMS/ServidorWMS.aspx?test=1"],
    }
    imgs_1 = PhotosBackfillWorker.ensure_non_market_streetview_photo(opp_coords)
    assert len(imgs_1) >= 1
    assert "maps.googleapis.com/maps/api/streetview" in imgs_1[0]
    assert "40.4265,-3.6865" in imgs_1[0]
    assert all("catastro" not in u.lower() for u in imgs_1)

    # 2. Oportunidad no-market externa sin coordenadas (solo dirección/municipio)
    opp_external = {
        "id": "BOE-EXT-SUB-JA-2026-888111",
        "channel": "subastas",
        "title": "Subasta BOE en Avenida Maisonnave 12",
        "address": "Avenida Maisonnave 12",
        "locality": "Alicante",
        "province": "Alicante",
        "postal_code": "03003",
        "lat": None,
        "lon": None,
        "images": [],
    }
    imgs_2 = PhotosBackfillWorker.ensure_non_market_streetview_photo(opp_external)
    assert len(imgs_2) >= 1
    assert "maps.googleapis.com/maps/api/streetview" in imgs_2[0]
    assert "Maisonnave" in imgs_2[0]

    # 3. AdvisorEngine().verify_and_filter_active_market_opportunities conserva y asegura Street View en no-market
    verified = AdvisorEngine().verify_and_filter_active_market_opportunities([
        {
            "id": "SUB-JA-2026-777222",
            "channel": "subastas",
            "address": "Calle Larios 10",
            "locality": "Málaga",
            "province": "Málaga",
            "images": [],
        }
    ])
    assert len(verified) == 1
    assert len(verified[0]["images"]) >= 1
    assert "maps.googleapis.com/maps/api/streetview" in verified[0]["images"][0]


def test_local_sqlite_replica_has_zero_orphans_and_all_streetview_photos():
    """
    Verifica que la réplica local `hivex_local.db` sincronizada 1:1 desde Supabase
    no tiene ninguna oportunidad huérfana ni ninguna subasta/activo no-market sin foto.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.models import Auction, Opportunity

    db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "hivex_local.db"))
    assert os.path.exists(db_path), "hivex_local.db debe existir como réplica 1:1 de Supabase"

    sq_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SqSession = sessionmaker(bind=sq_engine)
    db = SqSession()
    try:
        aucs = {a.id: a for a in db.query(Auction).all()}
        opps = db.query(Opportunity).all()
        assert len(aucs) >= 500
        assert len(opps) >= 500

        orphans = [o for o in opps if o.auction_id not in aucs]
        assert len(orphans) == 0, f"Encontradas oportunidades huérfanas: {len(orphans)}"

        missing_photos = []
        for o in opps:
            a = aucs[o.auction_id]
            imgs = json.loads(a.images_json) if a.images_json else []
            if not imgs or not any(isinstance(x, str) and x.strip() for x in imgs):
                missing_photos.append(a.id_subasta)
        assert len(missing_photos) == 0, f"Oportunidades sin foto: {missing_photos[:10]}"
    finally:
        db.close()
        sq_engine.dispose()

