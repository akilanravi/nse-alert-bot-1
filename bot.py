import os
import re
import sys
from datetime import datetime
import pytz
import requests
from bs4 import BeautifulSoup

# ==========================================
# 1. TELEGRAM RECIPIENTS
# ==========================================
TELEGRAM_RECIPIENTS = [
    ("8721771664:AAFcyCX2TP2KsUrIQoh6utZvHjbLQt8vD-k", "846124589"),
    ("8764996383:AAE_vevTjJ76zfK3g3rYGgsZB3_EtkbvUms", "8865083462"),
]

# Mode: 'LIVE' (5-minute scans) or 'WATCHLIST' (post-market narrow CPR)
SCAN_MODE = os.getenv("SCAN_MODE", "LIVE").upper()

# ==========================================
# 2. YOUR 4 CHARTINK SCANNERS
# ==========================================
SCANNERS = {
    "LIVE_CE": {
        "title": "🟢 CE 5-Min Live Breakout",
        "url": "https://chartink.com/screener/ce-scanner-934",
        "mode": "LIVE"
    },
    "LIVE_PE": {
        "title": "🔴 PE 5-Min Live Breakdown",
        "url": "https://chartink.com/screener/pe-scanner-929",
        "mode": "LIVE"
    },
    "WATCHLIST_CE": {
        "title": "📈 CE Tomorrow Watchlist (Narrow CPR)",
        "url": "https://chartink.com/screener/ce-tomorrow-watchlist",
        "mode": "WATCHLIST"
    },
    "WATCHLIST_PE": {
        "title": "📉 PE Tomorrow Watchlist (Narrow CPR)",
        "url": "https://chartink.com/screener/pe-tomorrow-watchlist",
        "mode": "WATCHLIST"
    }
}

def broadcast_telegram(message: str):
    """Broadcasts alert to all registered Telegram bot/chat pairs."""
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
            if not res.ok:
                print(f"Telegram API response for {chat_id}: {res.text}")
            else:
                print(f"Alert delivered to chat {chat_id}")
        except Exception as e:
            print(f"Connection failure for {chat_id}: {e}")

def fetch_chartink_stocks(scanner_url: str):
    """Extracts CSRF token, sends scan clause to Chartink process endpoint, and extracts matches."""
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": scanner_url
    }
    
    try:
        page = session.get(scanner_url, headers=headers, timeout=20)
        soup = BeautifulSoup(page.text, "html.parser")
        
        csrf_meta = soup.find("meta", {"name": "csrf-token"})
        if not csrf_meta:
            print(f"CSRF token missing on {scanner_url}")
            return None
        csrf_token = csrf_meta["content"]
        
        # Extract clause from input field, textarea, or JavaScript variable
        scan_clause = None
        input_elem = soup.find("input", {"id": "scan_clause"}) or soup.find("input", {"name": "scan_clause"})
        if input_elem and input_elem.get("value"):
            scan_clause = input_elem.get("value")
        else:
            match = re.search(r'scan_clause\s*[:=]\s*["\'](.*?)["\']', page.text)
            if match:
                scan_clause = match.group(1)

        if not scan_clause:
            print(f"Could not locate scan_clause string on {scanner_url}")
            return None
            
        process_url = "https://chartink.com/screener/process"
        session.headers.update({
            "X-CSRF-TOKEN": csrf_token,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
        })
        
        resp = session.post(process_url, data={"scan_clause": scan_clause}, timeout=20)
        resp_data = resp.json()
        return resp_data.get("data", [])
        
    except Exception as e:
        print(f"Error executing scan for {scanner_url}: {e}")
        return None

def main():
    ist_tz = pytz.timezone("Asia/Kolkata")
    now_ist = datetime.now(ist_tz).strftime("%d-%b-%Y %I:%M %p IST")
    
    active_scanners = [s for s in SCANNERS.values() if s["mode"] == SCAN_MODE]
    print(f"--- Running {SCAN_MODE} Scanners at {now_ist} ---")
    
    for item in active_scanners:
        title = item["title"]
        url = item["url"]
        
        stocks = fetch_chartink_stocks(url)
        
        if stocks is None:
            # Diagnostics if Chartink blocked or changed clause
            print(f"Could not retrieve data for {title}.")
            continue
            
        if len(stocks) == 0:
            print(f"0 stocks matched {title}.")
            # Send a confirmation ping when triggered manually so you know the bot is alive
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
            
        # Format matching stocks with Zerodha links
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
