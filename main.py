import os, time, json, urllib.request, urllib.parse

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": text}).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=15) as r:
        print("Telegram:", r.status)

def get_btc_price():
    url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.loads(r.read())
        return float(data["price"])

while True:
    try:
        price = get_btc_price()
        print(f"BTC: ${price:,.2f}", flush=True)
        if price > 100000:
            send_telegram(f"🚨 BTC ABOVE $100k! Price: ${price:,.2f}")
        elif price < 90000:
            send_telegram(f"⚠️ BTC BELOW $90k! Price: ${price:,.2f}")
    except Exception as e:
        print(f"Price error: {e}", flush=True)
    time.sleep(300)
        
