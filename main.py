import os, time, json, urllib.request, urllib.parse, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")
    def log_message(self, *a):
        pass

def run_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
threading.Thread(target=run_server, daemon=True).start()

def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": text}).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=15) as r:
        print("Telegram:", r.status, flush=True)

def get_btc_price():
    url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
    with urllib.request.urlopen(url, timeout=15) as r:
        return float(json.loads(r.read())["price"])

# SETTINGS - change these if you want
LONG_ENTRY = 60000
LONG_TP = 63600
SHORT_ENTRY = 58000
SHORT_TP = 54120
TRAIL_PCT = 0.03  # 3% trailing

state = "IDLE"  # IDLE, LONG, SHORT
entry_price = 0
highest = 0
lowest = 0
trail_sl = 0

while True:
    try:
        price = get_btc_price()
        print(f"BTC: ${price:,.2f} | State: {state}", flush=True)

        if state == "IDLE":
            if price > LONG_ENTRY:
                state = "LONG"
                entry_price = price
                highest = price
                trail_sl = price * (1 - TRAIL_PCT)
                send_telegram(f"🚀 LONG SETUP\nEntry: ${price:,.2f}\nTP: ${LONG_TP:,.2f}\nTrailing SL: ${trail_sl:,.2f} (follows price)")
            elif price < SHORT_ENTRY:
                state = "SHORT"
                entry_price = price
                lowest = price
                trail_sl = price * (1 + TRAIL_PCT)
                send_telegram(f"🔻 SHORT SETUP\nEntry: ${price:,.2f}\nTP: ${SHORT_TP:,.2f}\nTrailing SL: ${trail_sl:,.2f} (follows price)")

        elif state == "LONG":
            # Follow price up
            if price > highest:
                highest = price
                new_sl = price * (1 - TRAIL_PCT)
                if new_sl > trail_sl:
                    trail_sl = new_sl
                    print(f"Trailing SL moved up to ${trail_sl:,.2f}", flush=True)

            if price >= LONG_TP:
                send_telegram(f"✅ TP HIT - LONG\nEntry: ${entry_price:,.2f}\nExit: ${price:,.2f}\nProfit: +{((price-entry_price)/entry_price*100):.2f}%")
                state = "IDLE"
            elif price <= trail_sl:
                send_telegram(f"❌ SL HIT - LONG\nEntry: ${entry_price:,.2f}\nExit: ${price:,.2f}\nResult: {((price-entry_price)/entry_price*100):+.2f}%")
                state = "IDLE"

        elif state == "SHORT":
            # Follow price down
            if price < lowest:
                lowest = price
                new_sl = price * (1 + TRAIL_PCT)
                if new_sl < trail_sl:
                    trail_sl = new_sl
                    print(f"Trailing SL moved down to ${trail_sl:,.2f}", flush=True)

            if price <= SHORT_TP:
                send_telegram(f"✅ TP HIT - SHORT\nEntry: ${entry_price:,.2f}\nExit: ${price:,.2f}\nProfit: +{((entry_price-price)/entry_price*100):.2f}%")
                state = "IDLE"
            elif price >= trail_sl:
                send_telegram(f"❌ SL HIT - SHORT\nEntry: ${entry_price:,.2f}\nExit: ${price:,.2f}\nResult: {((entry_price-price)/entry_price*100):+.2f}%")
                state = "IDLE"

    except Exception as e:
        print(f"Price error: {e}", flush=True)
    time.sleep(300)
