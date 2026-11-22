import os
import time
import json
import urllib.request
import urllib.parse

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

def get_btc_price():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        return float(data["bitcoin"]["usd"])
    except Exception as e:
        print(f"Price error: {e}", flush=True)
        return None

def send_telegram(text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": text}).encode()
        req = urllib.request.Request(url, data=payload)
        with urllib.request.urlopen(req, timeout=15) as r:
            print(f"Telegram: {r.status}", flush=True)
    except Exception as e:
        print(f"Telegram error: {e}", flush=True)

last_alert_price = None
send_telegram("Bot started - tracking BTC price")
while True:
    price = get_btc_price()
    if price:
        print(f"BTC: ${price}", flush=True)
        if last_alert_price is None:
            last_alert_price = price
        elif abs(price - last_alert_price) / last_alert_price >= 0.01:
            change = (price - last_alert_price) / last_alert_price * 100
            send_telegram(f"BTC moved {change:+.2f}%: ${last_alert_price:,.0f} -> ${price:,.0f}")
            last_alert_price = price
    time.sleep(60)
        
