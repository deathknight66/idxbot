import logging
import requests
import os

logger = logging.getLogger("telegram_notifier")

# Set these via environment variables or replace with your actual tokens
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def send_telegram_message(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.debug(f"Telegram not configured. Message would be: {message}")
        return
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            logger.error(f"Failed to send Telegram message: {response.text}")
    except Exception as e:
        logger.error(f"Telegram API exception: {e}")
