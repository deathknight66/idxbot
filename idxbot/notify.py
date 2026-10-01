import os
import requests


def send(text: str, cfg: dict):
    print(text)
    if not cfg.get("notify", {}).get("telegram"):
        return
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[notify] telegram aktif tapi token/chat id belum diisi di .env")
        return
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": text}, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"[notify] gagal kirim telegram: {e}")
