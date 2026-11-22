# V5 LIVE BOT - BTC + GBPUSD + XAUUSD - 1H
# Render Web Service - No exchange keys needed, Telegram only
import os, json, time, threading, urllib.request
import requests
from flask import Flask

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
app = Flask(__name__)

def send(msg):
    if not TOKEN or not CHAT_ID: 
        print(msg); return
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": msg}, timeout=15)
    except Exception as e:
        print("TG err", e)

def fetch_binance():
    url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=200"
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.loads(r.read())
    return [[float(c[1]), float(c[2]), float(c[3]), float(c[4])] for c in data]

def fetch_yahoo(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1h&range=60d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    res = data['chart']['result'][0]
    q = res['indicators']['quote'][0]
    rows = []
    for i in range(len(q['close'])):
        if q['close'][i] is None: continue
        rows.append([q['open'][i], q['high'][i], q['low'][i], q['close'][i]])
    return rows

def analyze(sym, rows):
    opens=[r[0] for r in rows]; highs=[r[1] for r in rows]; lows=[r[2] for r in rows]; closes=[r[3] for r in rows]
    i = len(rows)-1
    if i < 40: return None
    if sym=="BTC": min_sl=250
    elif sym=="XAUUSD": min_sl=8.0
    else: min_sl=0.0012

    def atr(i):
        return sum(highs[k]-lows[k] for k in range(i-14, i))/14
    def trend(i):
        h1=sum(highs[i-20:i-10])/10; h2=sum(highs[i-10:i])/10
        l1=sum(lows[i-20:i-10])/10; l2=sum(lows[i-10:i])/10
        if h2>h1 and l2>l1: return "UPTREND"
        if h2<h1 and l2<l1: return "DOWNTREND"
        return "RANGING"
    def near_sr(i, price):
        for k in range(max(0,i-20), i):
            if abs(highs[k]-price)/price<0.004 or abs(lows[k]-price)/price<0.004: return True
        return False
    def liquidity(i, side):
        ph=max(highs[i-10:i-1]); pl=min(lows[i-10:i-1])
        if side=="BUY": return lows[i]<pl and closes[i]>pl
        else: return highs[i]>ph and closes[i]<ph
    def flag(i, side):
        if i<12: return False
        move=abs(closes[i-8]-opens[i-12])/opens[i-12]
        ch=max(highs[i-7:i-1]); cl=min(lows[i-7:i-1])
        rng=(ch-cl)/cl
        if move<0.015 or rng>0.012: return False
        if side=="BUY": return closes[i]>ch
        else: return closes[i]<cl
    def wedge(i, side):
        if i<15: return False, ""
        h=highs[i-15:i]; l=lows[i-15:i]
        hs=(h[-1]-h[0])/15; ls=(l[-1]-l[0])/15
        early=h[0]-l[0]; late=h[-1]-l[-1]
        if late < early*0.85:
            cur=closes[i]
            if hs<0 and ls<0 and side=="BUY" and cur>h[-1]: return True, "Falling Wedge"
            if hs>0 and ls>0 and side=="SELL" and cur<l[-1]: return True, "Rising Wedge"
        return False, ""
    def bos(i, side):
        ph=max(highs[i-25:i-5]); pl=min(lows[i-25:i-5])
        if side=="BUY": return closes[i]>ph*1.0002
        else: return closes[i]<pl*0.9998
    def confirm(i, side):
        o=opens[i]; c=closes[i]; h=highs[i]; l=lows[i]
        po=opens[i-1]; pc=closes[i-1]
        body=abs(c-o); rng=h-l
        if rng==0: return False
        if side=="BUY":
            return (c>o and pc<po and c>po) or ((min(c,o)-l)>body*1.5) or (body/rng>0.6 and c>o)
        else:
            return (c<o and pc>po and c<po) or ((h-max(c,o))>body*1.5) or (body/rng>0.6 and c<o)

    t=trend(i)
    if t=="RANGING": return None
    sides=["BUY"] if t=="UPTREND" else ["SELL"]
    for side in sides:
        score=0; reasons=[]
        score+=1; reasons.append("Trend")
        price=closes[i]
        has_sr=near_sr(i, price)
        if has_sr: score+=1; reasons.append("SR")
        has_liq=liquidity(i, side)
        if has_liq: score+=1; reasons.append("Liq")
        has_flag=flag(i, side)
        if has_flag: score+=1; reasons.append("Flag")
        wd, wname=wedge(i, side)
        if wd: score+=1; reasons.append(wname)
        has_bos=bos(i, side)
        if has_bos: score+=1; reasons.append("BOS")
        if not confirm(i, side): continue
        if score<3: continue
        if not (has_bos or has_liq): continue
        if side=="SELL" and not (has_sr and has_liq): continue
        sl_d=max(min_sl, atr(i)*1.5)
        if side=="BUY":
            sl=price-sl_d; tp1=price+sl_d*1.5; tp2=price+sl_d*3
        else:
            sl=price+sl_d; tp1=price-sl_d*1.5; tp2=price-sl_d*3
        return {"sym":sym,"side":side,"entry":price,"sl":sl,"tp1":tp1,"tp2":tp2,"score":score,"reasons":"+ ".join(reasons),"sl_d":sl_d}
    return None

# --- WATCHER ---
active = {}  # sym -> trade dict + tp1_hit

def watcher():
    while True:
        try:
            jobs = [("BTC", fetch_binance), ("GBPUSD", lambda: fetch_yahoo("GBPUSD=X")), ("XAUUSD", lambda: fetch_yahoo("GC=F"))]
            for sym, fn in jobs:
                try: rows = fn()
                except Exception as e:
                    print(sym, "fetch fail", e); continue
                # If we have an active trade, check SL/TP
                if sym in active:
                    tr = active[sym]
                    last = rows[-1]
                    h, l = last[1], last[2]
                    side, entry, sl, tp1, tp2 = tr["side"], tr["entry"], tr["sl"], tr["tp1"], tr["tp2"]
                    hit = None
                    if side=="BUY":
                        if l<=sl: hit="TP1" if tr["tp1_hit"] else "SL"
                        elif h>=tp2: hit="TP2"
                        elif h>=tp1 and not tr["tp1_hit"]:
                            tr["tp1_hit"]=True; tr["sl"]=entry
                            send(f"✅ {sym} {side} TP1 HIT @ {tp1:.4f}\nSL moved to BE @ {entry:.4f}\nLet it run to TP2 @ {tp2:.4f}")
                            continue
                    else:
                        if h>=sl: hit="TP1" if tr["tp1_hit"] else "SL"
                        elif l<=tp2: hit="TP2"
                        elif l<=tp1 and not tr["tp1_hit"]:
                            tr["tp1_hit"]=True; tr["sl"]=entry
                            send(f"✅ {sym} {side} TP1 HIT @ {tp1:.4f}\nSL moved to BE @ {entry:.4f}\nLet it run to TP2 @ {tp2:.4f}")
                            continue
                    if hit=="TP2":
                        send(f"🎯 {sym} {side} TP2 WIN @ {tp2:.4f}\nEntry {entry:.4f} | +3R"); del active[sym]
                    elif hit=="TP1":
                        send(f"✅ {sym} {side} TP1 WIN (BE hit after TP1) @ {entry:.4f}\n+1.5R"); del active[sym]
                    elif hit=="SL":
                        send(f"❌ {sym} {side} SL HIT @ {sl:.4f}\nEntry {entry:.4f} | -1R"); del active[sym]
                    continue
                # No active trade -> look for new signal
                sig = analyze(sym, rows)
                if sig:
                    active[sym] = {**sig, "tp1_hit": False}
                    send(f"🔔 V5 SIGNAL {sig['sym']} {sig['side']} S{sig['score']}\n"
                         f"POIs: {sig['reasons']}\n"
                         f"Entry: {sig['entry']:.4f}\nSL: {sig['sl']:.4f}\nTP1: {sig['tp1']:.4f} (1:1.5)\nTP2: {sig['tp2']:.4f} (1:3)\n"
                         f"Risk 1% only. Move SL to BE at TP1.")
            # Check every 15 min
            time.sleep(900)
        except Exception as e:
            print("Watcher err", e); time.sleep(60)

@app.route("/")
def home(): return "V5 Bot Running - Active: " + str(list(active.keys()))

threading.Thread(target=watcher, daemon=True).start()
send("🤖 V5 Bot started - Watching BTC + GBPUSD + XAUUSD 1H")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
