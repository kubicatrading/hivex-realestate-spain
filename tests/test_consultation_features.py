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

    opp1 = {"id": "OPP_1", "title": "Finca 1", "property_type": "RUSTIC", "province": "Madrid", "locality": "Madrid", "listing_price": 100000}
    opp2 = {"id": "OPP_2", "title": "Finca 2 Nueva", "property_type": "RUSTIC", "province": "Madrid", "locality": "Madrid", "listing_price": 120000}

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
