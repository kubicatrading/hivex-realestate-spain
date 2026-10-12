import pytest
import json
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.db.models import Base, SavedConsultation, User
from app.engine.advisor_engine import (
    AdvisorEngine,
    normalize_prompt_fingerprint,
    advisor_engine
)
from app.api.main import app


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_normalize_prompt_fingerprint():
    # 1. Puntuación y comillas tipográficas
    p1 = "«búscame gualix de la sierra-algete-colmenar viejo, en ese eje, fincas rústicas de más de 25.000m2 que tengan pozo/río y cuenten con casa»"
    p2 = "buscame gualix de la sierra algete colmenar viejo en ese eje fincas rusticas de mas de 25000m2 que tengan pozo rio y cuenten con casa."
    assert normalize_prompt_fingerprint(p1) == normalize_prompt_fingerprint(p2)

    # 2. Espacios y mayúsculas
    p3 = "  BÚSCAME   Gualix de la   Sierra - Algete - Colmenar Viejo   "
    p4 = "buscame gualix de la sierra algete colmenar viejo"
    assert normalize_prompt_fingerprint(p3) == normalize_prompt_fingerprint(p4)

    # 3. Contexto previo o conversacional inyectado
    p5 = "Haz la misma búsqueda de fincas (Contexto previo: fincas rústicas en Algete)"
    p6 = "Haz la misma búsqueda de fincas"
    assert normalize_prompt_fingerprint(p5) == normalize_prompt_fingerprint(p6)

    # 4. Prompt vacío
    assert normalize_prompt_fingerprint("") == ""
    assert normalize_prompt_fingerprint(None) == ""


def test_deduplicate_saved_consultations_db(test_db):
    prompt_base = "búscame gualix de la sierra-algete-colmenar viejo, en ese eje, fincas rústicas de más de 25.000m2 que tengan pozo/río y cuenten con casa"
    
    # Insertar 3 consultas idénticas (como las que aparecían en la plataforma)
    c1 = SavedConsultation(
        user_name="jsaavedra",
        telegram_chat_id="-1003904392737",
        title="🔍 Búsqueda: Rústico / Terreno en Madrid",
        description=prompt_base,
        matched_opportunity_ids_json=json.dumps(["OPP-1", "OPP-2"]),
        matched_count=2,
        ai_summary="Diagnóstico 1",
        created_at=datetime(2026, 10, 10, 17, 12, 0)
    )
    c2 = SavedConsultation(
        user_name="jsaavedra",
        telegram_chat_id="-1003904392737",
        title="🔍 Búsqueda: Rústico / Terreno en Madrid",
        description=f"«{prompt_base}»",
        matched_opportunity_ids_json=json.dumps(["OPP-1", "OPP-2", "OPP-3"]),
        matched_count=3,
        ai_summary="Diagnóstico 2",
        created_at=datetime(2026, 10, 10, 18, 46, 0)
    )
    c3 = SavedConsultation(
        user_name="jsaavedra",
        telegram_chat_id="-1003904392737",
        title="🔍 Búsqueda: Rústico / Terreno en Madrid",
        description=prompt_base,
        matched_opportunity_ids_json=json.dumps(["OPP-1"]),
        matched_count=1,
        ai_summary="Diagnóstico 3",
        created_at=datetime(2026, 10, 10, 19, 58, 0)
    )
    # Otra consulta distinta de otro usuario
    c_other = SavedConsultation(
        user_name="juanma",
        telegram_chat_id="12345",
        title="🔍 Búsqueda: Pisos en Carabanchel",
        description="enséñame pisos en Carabanchel",
        matched_count=5,
        created_at=datetime(2026, 10, 10, 20, 0, 0)
    )

    test_db.add_all([c1, c2, c3, c_other])
    test_db.commit()

    assert test_db.query(SavedConsultation).count() == 4

    # Ejecutar deduplicación
    removed = AdvisorEngine.deduplicate_saved_consultations(test_db)
    assert removed == 2
    assert test_db.query(SavedConsultation).count() == 2

    # Verificar que la consulta conservada para jsaavedra es la más reciente (c3)
    remaining_js = test_db.query(SavedConsultation).filter(SavedConsultation.user_name == "jsaavedra").all()
    assert len(remaining_js) == 1
    assert remaining_js[0].id == c3.id


@pytest.mark.asyncio
async def test_process_user_query_deduplication(test_db):
    prompt = "búscame gualix de la sierra-algete-colmenar viejo, en ese eje, fincas rústicas de más de 25.000m2 que tengan pozo/río y cuenten con casa"

    # 1. Primera ejecución: debe crear el registro
    res1 = await advisor_engine.process_user_query(
        user_name="jsaavedra",
        telegram_chat_id="-1003904392737",
        prompt_text=prompt,
        db=test_db
    )
    assert res1["success"] is True
    id1 = res1["saved_consultation_id"]
    assert id1 is not None
    assert test_db.query(SavedConsultation).count() == 1

    # 2. Segunda ejecución con el mismo prompt (o con comillas): debe actualizar id1, sin crear una nueva fila
    prompt_var = f"«{prompt.upper()}»"
    res2 = await advisor_engine.process_user_query(
        user_name="jsaavedra",
        telegram_chat_id="-1003904392737",
        prompt_text=prompt_var,
        db=test_db
    )
    assert res2["success"] is True
    id2 = res2["saved_consultation_id"]
    assert id2 == id1
    assert test_db.query(SavedConsultation).count() == 1

    # 3. Tercera ejecución con un prompt completamente distinto: debe crear una nueva consulta
    res3 = await advisor_engine.process_user_query(
        user_name="jsaavedra",
        telegram_chat_id="-1003904392737",
        prompt_text="enséñame áticos en Chamberí con terraza de más de 30m2",
        db=test_db
    )
    assert res3["success"] is True
    id3 = res3["saved_consultation_id"]
    assert id3 != id1
    assert test_db.query(SavedConsultation).count() == 2


def test_api_consultations_deduplicated():
    client = TestClient(app)
    resp = client.get("/api/v1/consultations")
    assert resp.status_code == 200
    data = resp.json()
    consultations = data.get("consultations", [])
    
    # Comprobar que no hay prompts idénticos para el mismo usuario devueltos por la API
    seen = set()
    for c in consultations:
        u = (c.get("user_name") or "").strip().lower()
        fp = normalize_prompt_fingerprint(c.get("description", ""))
        key = (u, fp)
        assert key not in seen, f"Consulta duplicada encontrada en respuesta API: {key}"
        seen.add(key)
