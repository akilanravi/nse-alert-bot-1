import os
import sys
from datetime import datetime
import pytz
import requests
from bs4 import BeautifulSoup

# ==========================================
# 1. TELEGRAM RECIPIENTS (bot_token, chat_id)
# ==========================================
TELEGRAM_RECIPIENTS = [
    ("8721771664:AAFcyCX2TP2KsUrIQoh6utZvHjbLQt8vD-k", "846124589"),
    ("8764996383:AAE_vevTjJ76zfK3g3rYGgsZB3_EtkbvUms", "8865083462"),
]

# Mode: 'LIVE' or 'WATCHLIST'
SCAN_MODE = os.getenv("SCAN_MODE", "WATCHLIST").upper()

# ==========================================
# 2. EXACT VERIFIED SCAN CLAUSES
# ==========================================
SCANNERS = {
    "WATCHLIST_CE": {
        "title": "📈 CE Tomorrow Watchlist (Narrow CPR)",
        "url": "https://chartink.com/screener/ce-tomorrow-watchlist",
        "mode": "WATCHLIST",
        "clause": "( {33489} ( ( {33489} ( daily close > daily ema( daily close , 20 ) and daily ema( daily close , 20 ) > daily ema( daily close , 50 ) and daily rsi( 14 ) > 55 and daily close > 1 day ago high and daily volume > daily sma( daily volume , 20 ) and daily high - daily low / daily close * 100 < 1.5 and daily close > ( daily high + daily low + daily close ) / 3 ) ) ) )"
    },
    "WATCHLIST_PE": {
        "title": "📉 PE Tomorrow Watchlist (Narrow CPR)",
        "url": "https://chartink.com/screener/pe-tomorrow-watchlist",
        "mode": "WATCHLIST",
        "clause": "( {33489} ( daily close < daily ema( daily close , 20 ) and daily ema( daily close , 20 ) < daily ema( daily close , 50 ) and daily rsi( 14 ) < 45 and daily close < 1 day ago low and daily volume > daily sma( daily volume , 20 ) and daily close < ( daily high + daily low + daily close ) / 3 and daily high - daily low / daily close * 100 < 1.5 ) )"
    },
    "LIVE_CE": {
        "title": "🟢 CE 5-Min Live Breakout",
        "url": "https://chartink.com/screener/ce-scanner-934",
        "mode": "LIVE",
        "clause": "( {33489} ( ( {33489} ( [0] 5 minute close > [0] 5 minute vwap and [0] 5 minute ema( [0] 5 minute close , 9 ) > [0] 5 minute ema( [0] 5 minute close , 21 ) and [0] 5 minute close > [0] 5 minute supertrend( 10 , 2 ) and [0] 5 minute rsi( 14 ) > 50 and [0] 5 minute volume > [0] 5 minute sma( [0] 5 minute volume , 20 ) * 1.5 and [0] 5 minute close > [0] 5 minute open and [0] 5 minute close > [-1] 5 minute high ) ) ) )"
    },
    "LIVE_PE": {
        "title": "🔴 PE 5-Min Live Breakdown",
        "url": "https://chartink.com/screener/pe-scanner-929",
        "mode": "LIVE",
        "clause": "( {33489} ( ( {33489} ( [0] 5 minute close < [0] 5 minute vwap and [0] 5 minute ema( [0] 5 minute close , 9 ) < [0] 5 minute ema( [0] 5 minute close , 21 ) and [0] 5 minute close < [0] 5 minute supertrend( 10 , 2 ) and [0] 5 minute rsi( 14 ) < 50 and [0] 5 minute volume > [0] 5 minute sma( [0] 5 minute volume , 20 ) * 1.5 and [0] 5 minute close < [0] 5 minute open and [0] 5 minute close < [-1] 5 minute low ) ) ) )"
    }
}

def broadcast_telegram(message: str):
    """Sends HTML alert to both Telegram bot recipients."""
    for token, chat_id in TELEGRAM_RECIPIENTS:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        try:
            res = requests.post(url, json=payload, timeout=12)
            if res.ok:
                print(f"Message delivered to {chat_id}")
            else:
                print(f"Telegram error for {chat_id}: {res.text}")
        except Exception as e:
            print(f"Connection failure for {chat_id}: {e}")

def run_scanner(clause: str):
    """Fetches session CSRF token and executes scan against Chartink process API."""
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://chartink.com",
        "Referer": "https://chartink.com/screener/"
    }
    
    try:
        home_res = session.get("https://chartink.com/screener/", headers=headers, timeout=15)
        soup = BeautifulSoup(home_res.text, "html.parser")
        csrf_meta = soup.find("meta", {"name": "csrf-token"})
        if not csrf_meta:
            print("Could not obtain CSRF token from Chartink.")
            return None
        csrf_token = csrf_meta["content"]
        
        process_url = "https://chartink.com/screener/process"
        headers["X-CSRF-TOKEN"] = csrf_token
        payload = {"scan_clause": clause}
        
        resp = session.post(process_url, headers=headers, data=payload, timeout=20)
        data = resp.json()
        return data.get("data", [])
    except Exception as err:
        print(f"Error querying Chartink: {err}")
        return None

def main():
    ist_tz = pytz.timezone("Asia/Kolkata")
    now_ist = datetime.now(ist_tz).strftime("%d-%b-%Y %I:%M %p IST")
    
    active_scanners = [s for s in SCANNERS.values() if s["mode"] == SCAN_MODE]
    print(f"--- Running {SCAN_MODE} Scanners at {now_ist} ---")
    
    for item in active_scanners:
        title = item["title"]
        url = item["url"]
        clause = item["clause"]
        
        print(f"Executing: {title}")
        stocks = run_scanner(clause)
        
        if stocks is None:
            continue
            
        if len(stocks) == 0:
            print(f"0 stocks matched for {title}.")
            # Send status ping on manual run from GitHub Actions UI
            if os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch":
                broadcast_telegram(
                    f"🔍 <b>{title}</b>\n"
                    f"🕒 <i>{now_ist}</i>\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"• <i>No qualifying stocks at this moment.</i>\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"🔗 <a href='{url}'>Open on Chartink</a>"
                )
            continue
            
        stock_lines = []
        for stock in stocks[:15]:
            symbol = stock.get("nsecode")
            close_price = stock.get("close", "N/A")
            pct_change = stock.get("per_chg", 0.0)
            kite_url = f"https://kite.zerodha.com/chart/ext/tvc/NSE/{symbol}"
            stock_lines.append(f"• <b><a href='{kite_url}'>{symbol}</a></b>: ₹{close_price} ({pct_change:+.2f}%)")
            
        msg = (
            f"<b>{title}</b>\n"
            f"🕒 <i>{now_ist}</i>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            + "\n".join(stock_lines) +
            f"\n━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <a href='{url}'>Open on Chartink</a>"
        )
        broadcast_telegram(msg)

if __name__ == "__main__":
    main()
    
