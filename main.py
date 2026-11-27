import urllib.request
import json
import os
import requests
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime

SYMBOLS = {"BTC-USD": "BTCUSD", "GC=F": "XAUUSD (Gold)", "ETH-USD": "ETHUSD"}
COSTS = {"BTC-USD": 0.0010, "GC=F": 0.0005, "ETH-USD": 0.0010}
INTERVAL = "30m"
SMA_PERIOD = 200
ATR_PERIOD = 14
BREAKOUT_LOOKBACK = 50
ATR_MULTIPLIER = 2.0

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def generate_chart_image(df, side, level, entry, sl, tp1, tp2, symbol_name):
    plot_data = df[-60:]
    fig, ax = plt.subplots(figsize=(10, 6), facecolor='#131722')
    ax.set_facecolor('#131722')
    for i in range(len(plot_data)):
        o, c, h, l = plot_data[i]["open"], plot_data[i]["close"], plot_data[i]["high"], plot_data[i]["low"]
        color = '#26a69a' if c >= o else '#ef5350'
        ax.plot([i, i], [l, h], color=color, linewidth=1)
        ax.add_patch(plt.Rectangle((i - 0.3, min(o, c)), 0.6, abs(c - o), color=color))
    ax.axhline(y=level, color='#ff9800', linestyle='--', linewidth=1.5, label='Breakout Level')
    ax.axhline(y=entry, color='#2196f3', linestyle='-', linewidth=1.5, label='Entry')
    ax.axhline(y=sl, color='#f44336', linestyle='-', linewidth=1.5, label='Stop Loss')
    ax.axhline(y=tp1, color='#4caf50', linestyle='--', linewidth=1.5, label='TP1')
    ax.axhline(y=tp2, color='#4caf50', linestyle='-', linewidth=1.5, label='TP2')
    ax.set_title(f"{symbol_name} - {side} Setup", color='white', fontweight='bold')
    ax.grid(color='#2a2e39', linestyle='-', linewidth=0.5, alpha=0.5)
    ax.tick_params(colors='white')
    for spine in ax.spines.values(): spine.set_color('#2a2e39')
    legend = ax.legend(loc='upper left', facecolor='#1e222d', edgecolor='#2a2e39')
    for text in legend.get_texts(): text.set_color("white")
    ax.set_xlim(-2, len(plot_data) + 5)
    filename = f"chart_{symbol_name.replace(' ', '_')}.png"
    plt.tight_layout()
    plt.savefig(filename, dpi=100, bbox_inches='tight')
    plt.close(fig)
    return filename

def send_telegram_photo(photo_path, caption):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    try:
        with open(photo_path, 'rb') as photo:
            requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "Markdown"}, files={"photo": photo}, timeout=15)
    except Exception as e:
        print(f"Telegram error: {e}")
    finally:
        if os.path.exists(photo_path): os.remove(photo_path)

def download_data(symbol_yf):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol_yf}?range=60d&interval={INTERVAL}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())
            result = data["chart"]["result"][0]
            q = result["indicators"]["quote"][0]
            return [{"time": result["timestamp"][i], "open": q["open"][i], "high": q["high"][i], "low": q["low"][i], "close": q["close"][i]} for i in range(len(result["timestamp"])) if None not in (q["open"][i], q["high"][i], q["low"][i], q["close"][i])]
    except: return []

def calculate_indicators(df, index):
    if index < max(SMA_PERIOD, ATR_PERIOD + 1): return None, None
    closes = [c["close"] for c in df[index - SMA_PERIOD:index]]
    sma = sum(closes) / SMA_PERIOD
    trs = [max(df[k]["high"] - df[k]["low"], abs(df[k]["high"] - df[k-1]["close"]), abs(df[k]["low"] - df[k-1]["close"])) for k in range(index - ATR_PERIOD, index)]
    return sma, sum(trs) / ATR_PERIOD

def scan(symbol_yf, symbol_name):
    df = download_data(symbol_yf)
    if len(df) < 250: return

    # The current closed candle is the LAST one in the list
    current_idx = len(df) - 1
    current_close = df[current_idx]["close"]
    current_open = df[current_idx]["open"]

    # Look backwards up to 3 candles to see if a breakout happened
    for lookback in range(1, 4):
        breakout_idx = current_idx - lookback
        breakout_candle = df[breakout_idx]
        sma200, atr14 = calculate_indicators(df, breakout_idx)
        if not sma200 or not atr14: continue

        # Get the 50-bar high/low BEFORE the breakout
        hist = df[breakout_idx - BREAKOUT_LOOKBACK:breakout_idx]
        level_high = max(c["high"] for c in hist)
        level_low = min(c["low"] for c in hist)

        side, level = None, None

        # 1. Was it a BREAKOUT?
        if breakout_candle["close"] > level_high * 1.0005 and breakout_candle["close"] > sma200:
            side, level = "BUY", level_high
        elif breakout_candle["close"] < level_low * 0.9995 and breakout_candle["close"] < sma200:
            side, level = "SELL", level_low
        else:
            continue

        # 2. Is the CURRENT candle a valid RETEST of that breakout?
        retest = False
        if side == "BUY" and df[current_idx]["low"] <= level * 1.002 and current_close > level and current_close > current_open:
            retest = True
        elif side == "SELL" and df[current_idx]["high"] >= level * 0.998 and current_close < level and current_close < current_open:
            retest = True

        if retest:
            cost = COSTS.get(symbol_yf, 0.0005)
            entry = current_close * (1 + cost) if side == "BUY" else current_close * (1 - cost)
            
            if side == "BUY":
                sl = entry - (atr14 * ATR_MULTIPLIER)
                risk = entry - sl
                tp1, tp2 = entry + (risk * 1.5), entry + (risk * 3.5)
            else:
                sl = entry + (atr14 * ATR_MULTIPLIER)
                risk = sl - entry
                tp1, tp2 = entry - (risk * 1.5), entry - (risk * 3.5)

            chart_path = generate_chart_image(df, side, level, entry, sl, tp1, tp2, symbol_name)
            emoji = "🟢" if side == "BUY" else "🔴"
            caption = (
                f"{emoji} *{side} SIGNAL: {symbol_name}* {emoji}\n\n"
                f"Current: `{current_close:.5g}`\nEntry: `{entry:.5g}`\nSL: `{sl:.5g}`\nTP1: `{tp1:.5g}`\nTP2: `{tp2:.5g}`\n\n"
                f"_Timeframe: {INTERVAL} | Retest Confirmed_"
            )
            send_telegram_photo(chart_path, caption)
            print(f"Signal Fired for {symbol_name}")
            return # Stop checking other lookbacks, we found the setup

if __name__ == "__main__":
    print("=== GITHUB ACTIONS BOT STARTED ===")
    for yf_sym, name in SYMBOLS.items():
        scan(yf_sym, name)
    print("=== SCAN COMPLETE ===")
