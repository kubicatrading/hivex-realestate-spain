import os
import sys
import asyncio
import logging

# Garantizar que la raíz del proyecto esté en sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.telegram_advisor_bot import telegram_advisor_bot

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

if __name__ == "__main__":
    print("Iniciando servicio de Telegram Polling para HIVEX Advisor...")
    try:
        asyncio.run(telegram_advisor_bot.start_polling())
    except (KeyboardInterrupt, SystemExit):
        print("Polling de Telegram detenido.")
