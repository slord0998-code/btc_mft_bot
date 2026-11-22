import urllib.request
import json
import time
import logging
import os
import threading
import requests
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- CONFIGURATION ---
SYMBOLS = {
    "BTC-USD": "BTCUSD",
    "GC=F":    "XAUUSD (Gold)",
    "ETH-USD": "ETHUSD"
}

COSTS = {
    "BTC-USD": 0.0010,
    "GC=F":     0.0005,
    "ETH-USD":  0.0010
}

INTERVAL = "30m"
SMA_PERIOD = 200
ATR_PERIOD = 14
BREAKOUT_LOOKBACK = 50
ATR_MULTIPLIER = 2.0

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# PENDING = symbol -> {side, level, expires_idx}
PENDING = {}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# --- FAKE WEB SERVER (Keeps Render Web Service Alive) ---
class WebServerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Trading Bot is running 24/7!")
    def log_message(self, format, *args):
        pass

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), WebServerHandler)
    logging.info(f"Web server listening on port {port}")
    server.serve_forever()

# --- CHART GENERATOR ---
def generate_chart_image(df, side, level, entry, sl, tp1, tp2, symbol_name):
    plot_data = df[-60:]
    opens = [c["open"] for c in plot_data]
    closes = [c["close"] for c in plot_data]
    highs = [c["high"] for c in plot_data]
    lows = [c["low"] for c in plot_data]

    fig, ax = plt.subplots(figsize=(10, 6), facecolor='#131722')
    ax.set_facecolor('#131722')

    for i in range(len(plot_data)):
        color = '#26a69a' if closes[i] >= opens[i] else '#ef5350'
        ax.plot([i, i], [lows[i], highs[i]], color=color, linewidth=1)
        rect = plt.Rectangle((i - 0.3, min(opens[i], closes[i])), 0.6, abs(closes[i] - opens[i]), color=color)
        ax.add_patch(rect)

    ax.axhline(y=level, color='#ff9800', linestyle='--', linewidth=1.5, label='Breakout Level')
    ax.axhline(y=entry, color='#2196f3', linestyle='-', linewidth=1.5, label='Entry')
    ax.axhline(y=sl, color='#f44336', linestyle='-', linewidth=1.5, label='Stop Loss')
    ax.axhline(y=tp1, color='#4caf50', linestyle='--', linewidth=1.5, label='TP1 (50%)')
    ax.axhline(y=tp2, color='#4caf50', linestyle='-', linewidth=1.5, label='TP2 (Runner)')

    ax.set_title(f"{symbol_name} - {side} Setup", color='white', fontsize=14, fontweight='bold', pad=15)
    ax.grid(color='#2a2e39', linestyle='-', linewidth=0.5, alpha=0.5)
    ax.tick_params(colors='white')
    for spine in ax.spines.values():
        spine.set_color('#2a2e39')

    legend = ax.legend(loc='upper left', facecolor='#1e222d', edgecolor='#2a2e39')
    for text in legend.get_texts():
        text.set_color("white")

    ax.set_xlim(-2, len(plot_data) + 5)
    filename = f"chart_{symbol_name.replace(' ', '_')}.png"
    plt.tight_layout()
    plt.savefig(filename, dpi=100, bbox_inches='tight')
    plt.close(fig)
    return filename

# --- TELEGRAM SENDER ---
def send_telegram_photo(photo_path, caption):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.warning("Telegram credentials missing.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    try:
        with open(photo_path, 'rb') as photo:
            payload = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "Markdown"}
            files = {"photo": photo}
            response = requests.post(url, data=payload, files=files, timeout=15)
            response.raise_for_status()
    except Exception as e:
        logging.error(f"Failed to send Telegram photo: {e}")
    finally:
        if os.path.exists(photo_path):
            os.remove(photo_path)

# --- TRADING LOGIC ---
def download_data(symbol_yf: str) -> list:
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{symbol_yf}?range=60d&interval={INTERVAL}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())
    except Exception as e:
        logging.error(f"Network error fetching {symbol_yf}: {e}")
        return []
    try:
        result = data["chart"]["result"][0]
        if "timestamp" not in result: return []
        timestamps = result["timestamp"]
        q = result["indicators"]["quote"][0]
        candles = []
        for i in range(len(timestamps)):
            o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
            if None in (o, h, l, c): continue
            candles.append({"time": timestamps[i], "open": o, "high": h, "low": l, "close": c})
        return candles
    except Exception as e:
        logging.error(f"Data parsing error for {symbol_yf}: {e}")
        return []

def calculate_indicators(df: list, index: int) -> tuple:
    if index < max(SMA_PERIOD, ATR_PERIOD + 1): return None, None
    closes = [c["close"] for c in df[index - SMA_PERIOD:index]]
    sma = sum(closes) / SMA_PERIOD
    trs = []
    for k in range(index - ATR_PERIOD, index):
        tr = max(df[k]["high"] - df[k]["low"], abs(df[k]["high"] - df[k-1]["close"]), abs(df[k]["low"] - df[k-1]["close"]))
        trs.append(tr)
    atr = sum(trs) / ATR_PERIOD
    return sma, atr

def send_signal(symbol_yf, symbol_name, df, i, side, level):
    candle = df[i]
    close = candle["close"]
    cost = COSTS.get(symbol_yf, 0.0005)
    _, atr14 = calculate_indicators(df, i)
    if atr14 is None:
        return

    entry = close * (1 + cost) if side == "BUY" else close * (1 - cost)

    if side == "BUY":
        sl = entry - (atr14 * ATR_MULTIPLIER)
        risk = entry - sl
        tp1 = entry + (risk * 1.5)
        tp2 = entry + (risk * 3.5)
    else:
        sl = entry + (atr14 * ATR_MULTIPLIER)
        risk = sl - entry
        tp1 = entry - (risk * 1.5)
        tp2 = entry - (risk * 3.5)

    chart_path = generate_chart_image(df, side, level, entry, sl, tp1, tp2, symbol_name)

    emoji = "🟢" if side == "BUY" else "🔴"
    caption = (
        f"{emoji} *{side} SIGNAL: {symbol_name}* {emoji}\n\n"
        f"Current: `{close:.5g}`\n"
        f"Entry: `{entry:.5g}`\n"
        f"SL: `{sl:.5g}`\n"
        f"TP1 (50%): `{tp1:.5g}`\n"
        f"TP2: `{tp2:.5g}`\n\n"
        f"_Timeframe: {INTERVAL} | Retest Confirmed_"
    )
    send_telegram_photo(chart_path, caption)
    logging.info(f"Signal & Chart sent for {symbol_name}!")

def scan_for_signals(symbol_yf: str, symbol_name: str):
    logging.info(f"Scanning {symbol_name}...")
    df = download_data(symbol_yf)
    if len(df) < max(SMA_PERIOD, BREAKOUT_LOOKBACK) + 2:
        return

    # Last CLOSED candle
    i = len(df) - 2
    candle = df[i]
    close = candle["close"]

    # STEP 1: Check PENDING retest
    if symbol_yf in PENDING:
        p = PENDING[symbol_yf]
        if i > p["expires_idx"]:
            logging.info(f"Pending expired for {symbol_name}, no retest.")
            del PENDING[symbol_yf]
            return

        retest = False
        if p["side"] == "BUY":
            if candle["low"] <= p["level"] * 1.002 and close > p["level"] and close > candle["open"]:
                retest = True
        else:
            if candle["high"] >= p["level"] * 0.998 and close < p["level"] and close < candle["open"]:
                retest = True

        if not retest:
            logging.info(f"Waiting retest for {symbol_name}... ({p['side']} @ {p['level']:.5g})")
            return

        logging.info(f"Retest confirmed for {symbol_name}!")
        send_signal(symbol_yf, symbol_name, df, i, p["side"], p["level"])
        del PENDING[symbol_yf]
        return

    # STEP 2: Check for NEW breakout
    sma200, atr14 = calculate_indicators(df, i)
    if sma200 is None or atr14 is None:
        return

    lookback = df[i - BREAKOUT_LOOKBACK:i]
    level_high = max(c["high"] for c in lookback)
    level_low = min(c["low"] for c in lookback)

    if close > level_high * 1.0005 and close > sma200:
        PENDING[symbol_yf] = {"side": "BUY", "level": level_high, "expires_idx": i + 3}
        logging.info(f"NEW breakout BUY pending {symbol_name} @ {level_high:.5g}, waiting retest")
    elif close < level_low * 0.9995 and close < sma200:
        PENDING[symbol_yf] = {"side": "SELL", "level": level_low, "expires_idx": i + 3}
        logging.info(f"NEW breakout SELL pending {symbol_name} @ {level_low:.5g}, waiting retest")

def sleep_until_next_candle():
    now = datetime.now()
    if now.minute < 30:
        next_run = now.replace(minute=30, second=5, microsecond=0)
    else:
        next_run = (now + timedelta(hours=1)).replace(minute=0, second=5, microsecond=0)
    sleep_seconds = (next_run - now).total_seconds()
    if sleep_seconds < 0: sleep_seconds = 10
    logging.info(f"Sleeping for {int(sleep_seconds/60)} minutes until {next_run.strftime('%H:%M')}...")
    time.sleep(sleep_seconds)

def trading_bot_loop():
    logging.info("=== V8 FINAL TRADING BOT STARTED - M30 + Retest + Chart ===")
    while True:
        try:
            for yf_sym, name in SYMBOLS.items():
                scan_for_signals(yf_sym, name)
                time.sleep(2)
            sleep_until_next_candle()
        except Exception as e:
            logging.error(f"Unexpected error in main loop: {e}")
            time.sleep(60)

if __name__ == "__main__":
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    trading_bot_loop()
