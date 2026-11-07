import os
import re
import sys
from datetime import datetime
import pytz
import requests
from bs4 import BeautifulSoup

# ==========================================
# 1. TELEGRAM RECIPIENTS CONFIGURATION
# (bot_token, chat_id)
# ==========================================
TELEGRAM_RECIPIENTS = [
    ("8721771664:AAFcyCX2TP2KsUrIQoh6utZvHjbLQt8vD-k", "846124589"),
    ("8764996383:AAE_vevTjJ76zfK3g3rYGgsZB3_EtkbvUms", "8865083462"),
]

# Execution mode: 'LIVE' (5-minute scans) or 'WATCHLIST' (daily narrow CPR scans)
SCAN_MODE = os.getenv("SCAN_MODE", "LIVE").upper()

# ==========================================
# 2. CHARTINK SCANNERS
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

# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================
def broadcast_telegram_alert(message: str):
    """Sends HTML formatted message to all configured bots and chats."""
    for token, chat_id in TELEGRAM_RECIPIENTS:
        if not token or not chat_id:
            continue
            
        api_url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        
        try:
            res = requests.post(api_url, json=payload, timeout=15)
            res.raise_for_status()
            print(f"Message sent to chat {chat_id}")
        except Exception as e:
            print(f"Failed delivering to chat {chat_id} via token {token[:10]}...: {e}")

def fetch_chartink_data(scanner_url: str):
    """Fetches real-time scan results from Chartink backend API."""
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest"
    }
    
    try:
        # Step 1: Extract CSRF token and scan clause from page HTML
        res = session.get(scanner_url, headers=headers, timeout=20)
        res.raise_for_status()
        
        soup = BeautifulSoup(res.text, "html.parser")
        csrf_meta = soup.find("meta", {"name": "csrf-token"})
        if not csrf_meta:
            print(f"Missing CSRF token on {scanner_url}")
            return []
        csrf_token = csrf_meta["content"]
        
        scan_clause = None
        input_elem = soup.find("input", {"id": "scan_clause"}) or soup.find("input", {"name": "scan_clause"})
        if input_elem:
            scan_clause = input_elem.get("value")
        else:
            match = re.search(r'name=["\']scan_clause["\']\s+value=["\'](.*?)["\']', res.text)
            if match:
                scan_clause = match.group(1)
            else:
                match_js = re.search(r'scan_clause\s*=\s*["\'](.*?)["\']', res.text)
                if match_js:
                    scan_clause = match_js.group(1)

        if not scan_clause:
            print(f"Could not parse scan clause from {scanner_url}")
            return []
            
        # Step 2: Query Chartink backend process endpoint
        process_url = "https://chartink.com/screener/process"
        headers["X-CSRF-TOKEN"] = csrf_token
        payload = {"scan_clause": scan_clause}
        
        post_res = session.post(process_url, headers=headers, data=payload, timeout=20)
        post_res.raise_for_status()
        json_data = post_res.json()
        
        return json_data.get("data", [])
        
    except Exception as err:
        print(f"Error fetching data from {scanner_url}: {err}")
        return []

def main():
    ist_tz = pytz.timezone("Asia/Kolkata")
    now_ist = datetime.now(ist_tz).strftime("%d-%b-%Y %I:%M %p IST")
    
    selected_scanners = [s for s in SCANNERS.values() if s["mode"] == SCAN_MODE]
    
    for item in selected_scanners:
        title = item["title"]
        url = item["url"]
        
        print(f"Processing scan: {title}")
        results = fetch_chartink_data(url)
        
        if not results:
            print(f"No qualifying stocks found for {title}.")
            continue
            
        stock_lines = []
        for stock in results[:15]:
            symbol = stock.get("nsecode")
            close_price = stock.get("close", "N/A")
            pct_change = stock.get("per_chg", 0.0)
            
            # Interactive link directly opens the 5-minute chart in Zerodha Kite
            kite_url = f"https://kite.zerodha.com/chart/ext/tvc/NSE/{symbol}"
            stock_lines.append(
                f"• <b><a href='{kite_url}'>{symbol}</a></b>: ₹{close_price} ({pct_change:+.2f}%)"
            )
            
        msg = (
            f"<b>{title}</b>\n"
            f"🕒 <i>{now_ist}</i>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            + "\n".join(stock_lines) +
            f"\n━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <a href='{url}'>Open on Chartink</a>"
        )
        
        broadcast_telegram_alert(msg)
        print(f"Broadcast completed for {title} ({len(results)} matches).")

if __name__ == "__main__":
    main()
