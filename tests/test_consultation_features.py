import pytest
import json
import asyncio
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, SavedConsultation, TelegramConversationMessage
from app.engine.advisor_engine import advisor_engine, AdvisorEngine, normalize_prompt_fingerprint
from app.services.consultation_alerts_worker import ConsultationAlertsWorker
from app.services.telegram_advisor_bot import TelegramAdvisorBot

@pytest.fixture
def in_memory_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

@pytest.mark.asyncio
async def test_cross_user_cache_zero_tokens(in_memory_db, monkeypatch):
    """
    REQUISITO 1: Si un usuario consulta lo mismo que otro, se sirven las mismas fichas
    de oportunidades que ya se sirvieron sin consumir tokens. Se crea una nueva línea
    con la consulta del nuevo usuario y fecha, mismo prompt y mismas fichas en 1ª posición.
    """
    advisor = AdvisorEngine()

    mock_opp = {
        "id": "OPP_MAD_001",
        "title": "Finca rústica en Guadalix de la Sierra",
        "listing_price": 180000,
        "locality": "Guadalix de la Sierra",
        "province": "Madrid",
        "property_type": "RUSTIC",
        "discount_percentage": 15.0,
        "overall_score": 88
    }

    # Mock catalog to return mock_opp
    monkeypatch.setattr(advisor, "get_live_catalog_opportunities", lambda db=None: [mock_opp])
    monkeypatch.setattr(advisor, "filter_opportunities", lambda opps, crit: [mock_opp])

    # Usuario A consulta y tiene ficha guardada
    consultation_user_a = SavedConsultation(
        user_name="Carlos",
        telegram_chat_id="11111",
        title="🔍 Búsqueda: Fincas Rústicas en Madrid",
        description="fincas rústicas en Madrid",
        query_type="SEARCH_OPPORTUNITIES",
        criteria_json=json.dumps({"property_type": "RUSTIC", "province": "Madrid"}),
        matched_opportunity_ids_json=json.dumps(["OPP_MAD_001"]),
        matched_count=1,
        ai_summary="1 finca encontrada",
        is_active=True,
        created_at=datetime(2026, 10, 10, 10, 0, 0)
    )
    in_memory_db.add(consultation_user_a)
    in_memory_db.commit()

    # Usuario B consulta exactamente lo mismo: "Fincas Rústicas en Madrid!"
    res_b = await advisor.process_user_query(
        prompt_text="Fincas Rústicas en Madrid!",
        user_name="Elena",
        telegram_chat_id="22222",
        db=in_memory_db
    )

    # Verificaciones Requisito 1
    assert res_b["success"] is True
    assert res_b["from_cache"] is True
    assert res_b["tokens_consumed"] == 0
    assert len(res_b["matched_opportunities"]) == 1
    assert res_b["matched_opportunities"][0]["id"] == "OPP_MAD_001"

    # Comprobar que en BD se creó una NUEVA línea para Elena
    elena_cons = in_memory_db.query(SavedConsultation).filter(SavedConsultation.user_name == "Elena").first()
    assert elena_cons is not None
    assert elena_cons.id != consultation_user_a.id
    assert elena_cons.telegram_chat_id == "22222"
    assert json.loads(elena_cons.matched_opportunity_ids_json) == ["OPP_MAD_001"]
    assert elena_cons.matched_count == 1
    # Elena debe estar con fecha más reciente que Carlos
    assert elena_cons.created_at > consultation_user_a.created_at

@pytest.mark.asyncio
async def test_non_card_queries_excluded_from_saved_consultations(in_memory_db, monkeypatch):
    """
    REQUISITO 2: Las consultas que no implican entregar fichas en Telegram,
    no se guardan en el módulo visual de oportunidades. Todo el resto de preguntas
    de negocio persisten en la base de conocimiento (TelegramConversationMessage).
    """
    advisor = AdvisorEngine()
    async def mock_gemini(*args, **kwargs):
        return (
            "El ROI (Return on Investment) en una estrategia Buy to Let se calcula dividiendo los ingresos netos anuales entre la inversión total.",
            "gemini-2.5-flash"
        )
    monkeypatch.setattr(advisor, "call_gemini_flash_cascade", mock_gemini)

    # Consulta analítica general de negocio (no pide fichas)
    prompt = "¿Cómo se calcula el ROI en una inversión Buy to Let?"
    
    res = await advisor.process_user_query(
        prompt_text=prompt,
        user_name="InversorPro",
        telegram_chat_id="33333",
        db=in_memory_db
    )

    assert res["success"] is True
    assert res["should_display_cards"] is False

    # NO debe existir en SavedConsultation (módulo visual de oportunidades)
    saved_cons = in_memory_db.query(SavedConsultation).filter(
        SavedConsultation.user_name == "InversorPro"
    ).all()
    assert len(saved_cons) == 0

    # SÍ debe persistir en TelegramConversationMessage (base de conocimiento HIVEX)
    conv_msgs = in_memory_db.query(TelegramConversationMessage).filter(
        TelegramConversationMessage.telegram_chat_id == "33333"
    ).all()
    assert len(conv_msgs) >= 2
    assert any(m.role == "user" and prompt in m.content for m in conv_msgs)
    assert any(m.role == "assistant" for m in conv_msgs)

@pytest.mark.asyncio
async def test_telegram_toggle_alert_commands(in_memory_db, monkeypatch):
    """
    REQUISITO 3: Propiedad activa/inactiva por búsquedas.
    El bot es capaz de activar o inactivar una alerta/búsqueda desde el propio grupo
    de Telegram por petición de un usuario.
    """
    bot = TelegramAdvisorBot()

    # Mock SessionLocal to use in_memory_db
    import app.services.telegram_advisor_bot as tg_module
    from contextlib import contextmanager

    @contextmanager
    def mock_session():
        yield in_memory_db

    monkeypatch.setattr(tg_module, "SessionLocal", mock_session)

    # Mock send_message to record replies
    sent_replies = []
    async def mock_send_message(chat_id, text, **kwargs):
        sent_replies.append({"chat_id": chat_id, "text": text})
        return True
    monkeypatch.setattr(bot, "send_message", mock_send_message)

    # Crear una consulta activa con fichas
    cons = SavedConsultation(
        id=42,
        user_name="Marcos",
        telegram_chat_id="55555",
        title="🔍 Búsqueda: Fincas Rústicas en Madrid",
        description="fincas rústicas en Madrid",
        query_type="SEARCH_OPPORTUNITIES",
        matched_opportunity_ids_json=json.dumps(["OPP_1"]),
        matched_count=1,
        is_active=True
    )
    in_memory_db.add(cons)
    in_memory_db.commit()

    # 1. Usuario pide pausar desde Telegram
    handled_pause = await bot.handle_toggle_alert_command(
        chat_id="55555",
        user_id="123",
        user_display_name="Marcos",
        text_content="desactiva la alerta de fincas rústicas"
    )
    assert handled_pause is True
    in_memory_db.refresh(cons)
    assert cons.is_active is False
    assert any("pausada" in r["text"].lower() for r in sent_replies)

    # 2. Usuario pide listar alertas
    handled_list = await bot.handle_toggle_alert_command(
        chat_id="55555",
        user_id="123",
        user_display_name="Marcos",
        text_content="ver mis alertas"
    )
    assert handled_list is True
    assert any("pausada" in r["text"].lower() and "42" in r["text"] for r in sent_replies)

    # 3. Usuario pide reactivar
    handled_activate = await bot.handle_toggle_alert_command(
        chat_id="55555",
        user_id="123",
        user_display_name="Marcos",
        text_content="activa la alerta #42"
    )
    assert handled_activate is True
    in_memory_db.refresh(cons)
    assert cons.is_active is True
    assert any("activada" in r["text"].lower() for r in sent_replies)

    # 4. Mensaje ordinario no debe ser capturado como comando de alerta
    handled_regular = await bot.handle_toggle_alert_command(
        chat_id="55555",
        user_id="123",
        user_display_name="Marcos",
        text_content="¿Qué oportunidades hay en Barcelona?"
    )
    assert handled_regular is False

@pytest.mark.asyncio
async def test_consultation_alerts_worker_daily_scan(in_memory_db, monkeypatch):
    """
    REQUISITO 4: Cron diario recorre oportunidades activas y descubre si existen oportunidades
    nuevas que cumplan los criterios. Se sirven en Telegram hasta un máximo de 20 al día.
    """
    worker = ConsultationAlertsWorker()

    delivered_cards = []
    delivered_msgs = []

    from app.services.telegram_advisor_bot import telegram_advisor_bot
    async def mock_send_msg(chat_id, text, **kwargs):
        delivered_msgs.append({"chat_id": chat_id, "text": text})
        return True
    async def mock_send_card(chat_id, opp, **kwargs):
        delivered_cards.append({"chat_id": chat_id, "opp": opp})
        return True

    monkeypatch.setattr(telegram_advisor_bot, "send_message", mock_send_msg)
    monkeypatch.setattr(telegram_advisor_bot, "send_photo_card", mock_send_card)

    cons = SavedConsultation(
        id=77,
        user_name="Lucia",
        telegram_chat_id="77777",
        title="Búsqueda: Fincas",
        description="fincas rústicas en Madrid",
        query_type="SEARCH_OPPORTUNITIES",
        criteria_json=json.dumps({"property_type": "RUSTIC", "province": "Madrid"}),
        matched_opportunity_ids_json=json.dumps(["OPP_1"]),
        matched_count=1,
        is_active=True,
        last_alert_at=None
    )
    in_memory_db.add(cons)
    in_memory_db.commit()

    opp1 = {
        "id": "OPP_1",
        "title": "Finca 1",
        "property_type": "RUSTIC",
        "province": "Madrid",
        "locality": "Madrid",
        "listing_price": 100000,
        "images": ["https://img4.idealista.com/blur/WEB_DETAIL/0/id.pro.es.image.master/aa/bb/cc/111111.jpg"]
    }
    opp2 = {
        "id": "OPP_2",
        "title": "Finca 2 Nueva",
        "property_type": "RUSTIC",
        "province": "Madrid",
        "locality": "Madrid",
        "listing_price": 120000,
        "images": ["https://img4.idealista.com/blur/WEB_DETAIL/0/id.pro.es.image.master/aa/bb/cc/222222.jpg"]
    }

    # Mock live catalog to return opp1 and opp2
    monkeypatch.setattr(advisor_engine, "get_live_catalog_opportunities", lambda db=None: [opp1, opp2])
    monkeypatch.setattr(advisor_engine, "filter_opportunities", lambda opps, criteria: opps)

    # Ejecutar escaneo diario
    report = await worker.run_daily_scan(db=in_memory_db, force=True, max_cards_per_consultation=20)

    assert report["scanned_consultations"] == 1
    assert report["alerts_triggered"] == 1
    assert report["new_opportunities_delivered"] == 1
    assert len(delivered_cards) == 1
    assert delivered_cards[0]["opp"]["id"] == "OPP_2"

    in_memory_db.refresh(cons)
    delivered_ids = json.loads(cons.matched_opportunity_ids_json)
    assert "OPP_1" in delivered_ids
    assert "OPP_2" in delivered_ids
    assert cons.matched_count == 2
    assert cons.last_alert_at is not None

def test_specific_consultation_title_formatting_and_id():
    """
    Verifica que la generación de títulos de búsquedas y alertas especifique
    la zona geográfica concreta (e.g. eje, barrio o localidad) y añada el número de ID.
    """
    advisor = AdvisorEngine()

    # Caso 1: Eje específico con tipo Rústico / Terreno y ID #21
    criteria_1 = {
        "query_type": "SEARCH_OPPORTUNITIES",
        "property_type": "Rústico / Terreno",
        "zone_or_neighborhood": "Eje Guadalix de la Sierra - Algete - Colmenar Viejo",
        "province": "Madrid"
    }
    title_1 = advisor.format_consultation_title(criteria_1, consultation_id=21)
    assert title_1 == "🔍 Búsqueda #21: Rústico / Eje Guadalix de la Sierra - Algete - Colmenar Viejo"

    # Caso 2: Alerta con barrio específico y límite de precio
    criteria_2 = {
        "query_type": "SEARCH_OPPORTUNITIES",
        "property_type": "Piso / Apartamento",
        "zone_or_neighborhood": "Chamberí",
        "province": "Madrid",
        "max_price": 450000,
        "is_alert": True
    }
    title_2 = advisor.format_consultation_title(criteria_2, consultation_id=105)
    assert title_2 == "🔔 Alerta #105: Piso / Chamberí (< 450.000€)"

    # Caso 3: Consulta general sin zona específica (fallback a provincia)
    criteria_3 = {
        "query_type": "SEARCH_OPPORTUNITIES",
        "property_type": "Chalet",
        "province": "Valencia",
        "is_alert": False
    }
    title_3 = advisor.format_consultation_title(criteria_3, consultation_id=7)
    assert title_3 == "🔍 Búsqueda #7: Chalet en Valencia"


@pytest.mark.asyncio
async def test_dev_agent_command_dispatch(monkeypatch):
    """
    Verifica que el comando /dev para el administrador dispara la solicitud
    hacia GitHub Actions para el DevAgent y que los usuarios no autorizados son rechazados.
    """
    from app.services.telegram_advisor_bot import telegram_advisor_bot
    from app.core.config import settings

    sent_messages = []
    async def mock_send(chat_id, text, **kwargs):
        sent_messages.append({"chat_id": chat_id, "text": text})
        return True

    monkeypatch.setattr(telegram_advisor_bot, "send_message", mock_send)

    # 1. Usuario no autorizado
    res_unauth = await telegram_advisor_bot.handle_dev_agent_command(
        chat_id=999,
        user_id=999,
        user_display_name="impostor",
        task_text="/dev borra todo"
    )
    assert res_unauth is True
    assert "reservado exclusivamente para el administrador" in sent_messages[-1]["text"]

    # 2. Administrador solicita ayuda o tarea vacía
    res_help = await telegram_advisor_bot.handle_dev_agent_command(
        chat_id=1450113787,
        user_id=1450113787,
        user_display_name="jsaavedra",
        task_text="/dev"
    )
    assert res_help is True
    assert "HIVEX DevAgent" in sent_messages[-1]["text"]

    # 3. Administrador envía tarea con GITHUB_TOKEN configurado (mockeando httpx)
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "mock_gh_token_123")
    dispatched_payload = []

    class MockResponse:
        status_code = 204
        text = ""

    async def mock_post(client, url, json=None, headers=None, **kwargs):
        dispatched_payload.append({"url": url, "json": json, "headers": headers})
        return MockResponse()

    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

    res_dispatch = await telegram_advisor_bot.handle_dev_agent_command(
        chat_id=1450113787,
        user_id=1450113787,
        user_display_name="jsaavedra",
        task_text="/dev Añade un nuevo test unitario y corre pytest"
    )
    assert res_dispatch is True
    assert len(dispatched_payload) == 1
    assert "dev_agent.yml/dispatches" in dispatched_payload[0]["url"]
    assert dispatched_payload[0]["json"]["inputs"]["task"] == "Añade un nuevo test unitario y corre pytest"
    assert "¡DevAgent activado en GitHub Actions!" in sent_messages[-1]["text"]


@pytest.mark.asyncio
async def test_alerts_worker_respects_active_consultations_and_photo_guardian(in_memory_db, monkeypatch):
    """
    Verifica que:
    1. Las consultas pausadas (is_active=False), eliminadas o sin fichas verificadas (matched_count=0)
       NUNCA disparan alertas en el cron.
    2. El Guardian descarta cualquier oportunidad (incluso de subastas BOE o extraída Out-of-HIVEX)
       que carezca de fotografías reales válidas antes de enviar ni siquiera la cabecera de Telegram.
    3. send_photo_card jamás envía texto plano si no hay foto válida.
    """
    worker = ConsultationAlertsWorker()
    delivered_msgs = []
    delivered_cards = []

    from app.services.telegram_advisor_bot import telegram_advisor_bot
    async def mock_send_msg(chat_id, text, **kwargs):
        delivered_msgs.append({"chat_id": chat_id, "text": text})
        return True
    async def mock_send_card(chat_id, opp, **kwargs):
        delivered_cards.append({"chat_id": chat_id, "opp": opp})
        return True

    monkeypatch.setattr(telegram_advisor_bot, "send_message", mock_send_msg)
    monkeypatch.setattr(telegram_advisor_bot, "send_photo_card", mock_send_card)

    # Consulta 1: Pausada (is_active=False) -> No debe escanearse
    c_paused = SavedConsultation(
        id=201,
        user_name="UserPaused",
        telegram_chat_id="88888",
        title="Búsqueda Pausada",
        description="Oportunidades en Urbanización Avenida de las Vegas, 28229 Villanueva del Pardillo, Madrid",
        query_type="SEARCH_OPPORTUNITIES",
        criteria_json=json.dumps({"province": "Madrid"}),
        matched_opportunity_ids_json=json.dumps(["MKT-1"]),
        matched_count=1,
        is_active=False
    )
    # Consulta 2: Huérfana con matched_count=0 -> No debe escanearse
    c_empty = SavedConsultation(
        id=202,
        user_name="UserEmpty",
        telegram_chat_id="88888",
        title="Búsqueda Vacía #25",
        description="Oportunidades en Urbanización Avenida de las Vegas, 28229 Villanueva del Pardillo, Madrid",
        query_type="SEARCH_OPPORTUNITIES",
        criteria_json=json.dumps({"province": "Madrid"}),
        matched_opportunity_ids_json="[]",
        matched_count=0,
        is_active=True
    )
    # Consulta 3: Vigente y activa, pero el catálogo devuelve solo una subasta sin foto y fuera de zona
    c_active = SavedConsultation(
        id=203,
        user_name="UserActive",
        telegram_chat_id="88888",
        title="🔍 Búsqueda #203: Chalet / Las Vegas - Villanueva del Pardillo",
        description="Oportunidades en Urbanización Avenida de las Vegas, 28229 Villanueva del Pardillo, Madrid",
        query_type="SEARCH_OPPORTUNITIES",
        criteria_json=json.dumps({"province": "Madrid", "zone_or_neighborhood": "Las Vegas - Villanueva del Pardillo"}),
        matched_opportunity_ids_json=json.dumps(["MKT-EXISTING"]),
        matched_count=1,
        is_active=True
    )
    in_memory_db.add_all([c_paused, c_empty, c_active])
    in_memory_db.commit()

    bad_subasta_no_photo = {
        "id": "SUB-JC-2026-PALENCIA",
        "source_type": "subastas",
        "primary_portal": "BOE_SUBASTAS",
        "title": "Subasta de Vivienda en Palencia (Palencia)",
        "address": "Santa María de la Cabeza. nº 22. Palencia (Palencia)",
        "locality": "Palencia",
        "province": "Palencia",
        "listing_price": 11540,
        "images": []
    }
    bad_madrid_wrong_zone = {
        "id": "MKT-IDEALISTA-SANTA-MARIA",
        "source_type": "market",
        "primary_portal": "Idealista",
        "title": "Piso en Santa María de la Cabeza, Madrid",
        "address": "Paseo de Santa María de la Cabeza, 28045 Madrid",
        "locality": "Madrid",
        "province": "Madrid",
        "postal_code": "28045",
        "listing_price": 240000,
        "images": ["https://img4.idealista.com/blur/WEB_DETAIL/0/id.pro.es.image.master/aa/bb/cc/999999.jpg"]
    }

    monkeypatch.setattr(
        advisor_engine,
        "get_live_catalog_opportunities",
        lambda db=None: [bad_subasta_no_photo, bad_madrid_wrong_zone]
    )
    async def mock_sync_empty(*args, **kwargs):
        return []
    monkeypatch.setattr(advisor_engine, "sync_portal_opportunities_on_demand", mock_sync_empty)

    report = await worker.run_daily_scan(db=in_memory_db, force=True)
    # Solo c_active (1 consulta) es escaneada; c_paused y c_empty son ignoradas.
    # Y como las 2 candidatas incumplen zona AND y/o foto, se envían 0 alertas y 0 mensajes.
    assert report["scanned_consultations"] == 1
    assert report["alerts_triggered"] == 0
    assert report["new_opportunities_delivered"] == 0
    assert len(delivered_msgs) == 0
    assert len(delivered_cards) == 0

    # Verificar que send_photo_card devuelve False y jamás envía texto plano si una subasta no tiene fotos
    real_bot = TelegramAdvisorBot()
    real_bot_msgs = []
    async def mock_real_send_msg(chat_id, text, **kwargs):
        real_bot_msgs.append(text)
        return True
    monkeypatch.setattr(real_bot, "send_message", mock_real_send_msg)
    sent_ok = await real_bot.send_photo_card("88888", bad_subasta_no_photo)
    assert sent_ok is False
    assert len(real_bot_msgs) == 0


@pytest.mark.asyncio
async def test_out_hivex_triggered_when_zero_catalog_matches_despite_statistically_representative_zone(in_memory_db, monkeypatch):
    """
    REGLA DE INGESTA DE OPORTUNIDADES (Out-of-HIVEX):
    Cuando el usuario solicita oportunidades (ej. "Envíame oportunidades que detectes en Villanueva del pardillo (Urbanización Las Vegas)")
    y hay 0 coincidencias en el catálogo interno de HIVEX, se DEBE activar automáticamente sync_portal_opportunities_on_demand (Out-of-HIVEX)
    incluso si la zona ya cuenta con precios de referencia estadísticamente representativos (2.800 €/m², 17.5 €/m²/mes).
    """
    prompt = "Envíame oportunidades que detectes en Villanueva del pardillo (Urbanización Las Vegas)"
    criteria = advisor_engine._parse_query_intent_heuristics(prompt)
    assert criteria["query_type"] == "SEARCH_OPPORTUNITIES"
    assert criteria["province"] == "Madrid"
    assert "Las Vegas" in (criteria.get("zone_or_neighborhood") or "")
    assert "Villanueva" in (criteria.get("zone_or_neighborhood") or "")
    assert "(" not in (criteria.get("zone_or_neighborhood") or "")
    assert ")" not in (criteria.get("zone_or_neighborhood") or "")

    out_hivex_calls = []
    synced_card = {
        "id": "MKT-FOTOCASA-VDP-LASVEGAS-1",
        "source_type": "market",
        "primary_portal": "Fotocasa",
        "title": "Chalet pareado en Urbanización Las Vegas, Villanueva del Pardillo",
        "address": "Avenida de las Vegas, Urbanización Las Vegas, 28229 Villanueva del Pardillo, Madrid",
        "locality": "Villanueva del Pardillo",
        "province": "Madrid",
        "postal_code": "28229",
        "property_type": "CHALET",
        "listing_price": 465000.0,
        "estimated_reference_value": 540000.0,
        "discount_percentage": 13.9,
        "surface_m2": 210.0,
        "rental_yield": 6.4,
        "overall_score": 84.5,
        "url": "https://www.fotocasa.es/es/comprar/vivienda/villanueva-del-pardillo/las-vegas/189999999/d",
        "images": ["https://static.fotocasa.es/images/ads/aa/bb/cc/189999999_1.jpg"]
    }

    monkeypatch.setattr(advisor_engine, "get_live_catalog_opportunities", lambda db=None: [])
    async def mock_sync_on_demand(criteria, prompt_text="", target_count=5, db=None):
        out_hivex_calls.append({"criteria": criteria, "prompt_text": prompt_text})
        return [synced_card]

    monkeypatch.setattr(advisor_engine, "sync_portal_opportunities_on_demand", mock_sync_on_demand)
    monkeypatch.setattr(advisor_engine, "verify_and_filter_active_market_opportunities", lambda opps, target_count=20: opps)

    res = await advisor_engine.process_user_query(
        user_name="Juanma OMS",
        prompt_text=prompt,
        telegram_chat_id="999111",
        db=in_memory_db
    )

    assert len(out_hivex_calls) == 1
    assert res["matched_count"] == 1
    assert res["matched_opportunities"][0]["id"] == "MKT-FOTOCASA-VDP-LASVEGAS-1"
    assert res["should_display_cards"] is True


def test_same_user_prompt_concatenation_and_reconstruction_without_time_limit(in_memory_db, monkeypatch):
    """
    Verifica que en lugar de depender de ventanas de tiempo (180s / 25m), se comprueba si el
    mensaje anterior en TelegramConversationMessage pertenece al mismo usuario (telegram_user_id).
    Si es del mismo usuario, concatena, reconstruye y devuelve un único prompt unificado para Gemini.
    """
    bot = TelegramAdvisorBot()
    import app.services.telegram_advisor_bot as tg_module
    from contextlib import contextmanager

    @contextmanager
    def mock_session():
        yield in_memory_db

    monkeypatch.setattr(tg_module, "SessionLocal", mock_session)

    # Mensaje previo del asistente proponiendo Madrid (hace 3 horas)
    in_memory_db.add(TelegramConversationMessage(
        telegram_chat_id="-1003904392737",
        telegram_user_id="1450113787",
        role="assistant",
        content="En Madrid la rentabilidad de locales para cambio de uso a vivienda supera el 9,5%.",
        created_at=datetime.utcnow() - timedelta(hours=3)
    ))
    # Primer mensaje del usuario Juanma (hace 2 horas -> fuera de cualquier ventana de 180s o 25m)
    in_memory_db.add(TelegramConversationMessage(
        telegram_chat_id="-1003904392737",
        telegram_user_id="1450113787",
        role="user",
        content="Sí, configura, pero ten en cuenta en la búsqueda que esos locales deben permitir la reconversión?",
        created_at=datetime.utcnow() - timedelta(hours=2)
    ))
    in_memory_db.commit()

    # Segundo mensaje del MISMO usuario (1450113787)
    reconstructed_prompt, clarify = bot.synthesize_conversation_prompt(
        chat_id="-1003904392737",
        user_id="1450113787",
        current_text="Y envíame por aquí las oportunidades q descubras"
    )
    assert clarify is None
    assert "Sí, configura, pero ten en cuenta en la búsqueda que esos locales deben permitir la reconversión?. Y envíame por aquí las oportunidades q descubras" in reconstructed_prompt
    assert "Madrid" in reconstructed_prompt

    # Si un usuario DISTINTO (999999) envía un mensaje en el mismo grupo, NO concatena el mensaje de 1450113787
    other_user_prompt, clarify_other = bot.synthesize_conversation_prompt(
        chat_id="-1003904392737",
        user_id="999999",
        current_text="Quiero ver pisos en Sevilla"
    )
    assert clarify_other is None
    assert other_user_prompt == "Quiero ver pisos en Sevilla"

    # Si entre el mensaje anterior del mismo usuario y el último mensaje YA existe una contestación del bot (role='assistant'),
    # NO se concatena con el mensaje anterior del usuario
    in_memory_db.add(TelegramConversationMessage(
        telegram_chat_id="-1003904392737",
        telegram_user_id="1450113787",
        role="assistant",
        content="He configurado la alerta y aquí tienes las 10 oportunidades detectadas en Madrid."
    ))
    in_memory_db.commit()

    after_bot_reply_prompt, clarify_after = bot.synthesize_conversation_prompt(
        chat_id="-1003904392737",
        user_id="1450113787",
        current_text="Y que tengan salida de humos"
    )
    assert clarify_after is None
    assert "reconversión" not in after_bot_reply_prompt
    assert "Y que tengan salida de humos" in after_bot_reply_prompt


def test_semantic_cohesion_evaluation_ej1_comparative_vs_ej2_independent_searches(in_memory_db, monkeypatch):
    """
    Verifica la regla semántica profunda para decidir si dos o más mensajes seguidos del mismo usuario
    (sin contestación del bot en medio) están relacionados y se pueden responder de una sola vez:
    - Ej1: "¿me puedes decir el yield de la zona de carabanchel?" + "¿me puedes comparar con el yield de Pinto?"
      -> SÍ están relacionados y se contestan en una misma respuesta comparativa (SE CONCATENAN).
    - Ej2: "¿me puedes enviar oportunidades de la zona de carabanchel?" + "¿me puedes enviar oportunidades de la zona de Pinto?"
      -> NO están relacionados para una única respuesta, sino que son 2 búsquedas de oportunidades independientes (NO SE CONCATENAN).
    - También verifica que una pregunta sobre el estado de alertas en plataforma NO herede 'Carabanchel' del mensaje anterior del bot.
    """
    bot = TelegramAdvisorBot()
    import app.services.telegram_advisor_bot as tg_module
    from contextlib import contextmanager

    @contextmanager
    def mock_session():
        yield in_memory_db

    monkeypatch.setattr(tg_module, "SessionLocal", mock_session)

    # --- EJEMPLO 1: Comparativa de Yield entre Carabanchel y Pinto (SÍ concatena) ---
    in_memory_db.query(TelegramConversationMessage).delete()
    in_memory_db.add(TelegramConversationMessage(
        telegram_chat_id="-1003904392737",
        telegram_user_id="1450113787",
        role="user",
        content="¿me puedes decir el yield de la zona de carabanchel?"
    ))
    in_memory_db.commit()

    ej1_prompt, ej1_clarify = bot.synthesize_conversation_prompt(
        chat_id="-1003904392737",
        user_id="1450113787",
        current_text="¿me puedes comparar con el yield de Pinto?"
    )
    assert ej1_clarify is None
    assert "¿me puedes decir el yield de la zona de carabanchel?" in ej1_prompt
    assert "¿me puedes comparar con el yield de Pinto?" in ej1_prompt

    # --- EJEMPLO 2: Dos peticiones independientes de envío de oportunidades (NO concatena) ---
    in_memory_db.query(TelegramConversationMessage).delete()
    in_memory_db.add(TelegramConversationMessage(
        telegram_chat_id="-1003904392737",
        telegram_user_id="1450113787",
        role="user",
        content="¿me puedes enviar oportunidades de la zona de carabanchel?"
    ))
    in_memory_db.commit()

    ej2_prompt, ej2_clarify = bot.synthesize_conversation_prompt(
        chat_id="-1003904392737",
        user_id="1450113787",
        current_text="¿me puedes enviar oportunidades de la zona de Pinto?"
    )
    assert ej2_clarify is None
    assert "carabanchel" not in ej2_prompt.lower()
    assert ej2_prompt == "¿me puedes enviar oportunidades de la zona de Pinto?"

    # --- INCIDENCIA SUPERGRUPO: Pregunta por alertas en plataforma tras respuesta del bot que mencionaba Carabanchel ---
    in_memory_db.query(TelegramConversationMessage).delete()
    in_memory_db.add(TelegramConversationMessage(
        telegram_chat_id="-1003904392737",
        telegram_user_id="1450113787",
        role="assistant",
        content="En Madrid (distritos como Carabanchel, Tetuán o Puente de Vallecas) el cambio de uso supera el 9,5%."
    ))
    in_memory_db.commit()

    alert_check_prompt, alert_clarify = bot.synthesize_conversation_prompt(
        chat_id="-1003904392737",
        user_id="1450113787",
        current_text="estás seguro que no hay oportunidades nuevas de ninguna de las alertas configuradas en plataforma?"
    )
    assert alert_clarify is None
    assert "carabanchel" not in alert_check_prompt.lower()
    assert alert_check_prompt == "estás seguro que no hay oportunidades nuevas de ninguna de las alertas configuradas en plataforma?"





