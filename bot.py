import csv
import logging
import os
import time
from datetime import datetime
import numpy as np
import pandas as pd
import pytz
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ==============================================================================
# 1. DUAL TELEGRAM RECIPIENTS (TOKEN + CHAT ID PAIRS)
# ==============================================================================
TELEGRAM_RECIPIENTS = [
    {
        "token": "8721771664:AAFcyCX2TP2KsUrIQoh6utZvHjbLQt8vD-k",
        "chat_id": "846124589",
    },
    {
        "token": "8764996383:AAE_vevTjJ76zfK3g3rYGgsZB3_EtkbvUms",
        "chat_id": "8865083462",
    },
]

LOG_FILE = "trade_log.csv"


def send_telegram_alert(message: str):
    """Dispatches HTML-formatted alerts to each configured bot token & chat_id pair."""
    if not TELEGRAM_RECIPIENTS:
        logging.warning("No Telegram recipients configured. Message:\n" + message)
        return

    for item in TELEGRAM_RECIPIENTS:
        token = item.get("token")
        chat_id = item.get("chat_id")
        if not token or not chat_id:
            continue

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            logging.info(f"Alert sent successfully to chat_id: {chat_id}")
        except Exception as e:
            logging.error(f"Failed to dispatch Telegram alert to {chat_id}: {e}")


# ==============================================================================
# 2. TECHNICAL INDICATORS
# ==============================================================================
def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))


def calculate_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0):
    atr = calculate_atr(df, period)
    hl2 = (df["high"] + df["low"]) / 2
    upperband = hl2 + (multiplier * atr)
    lowerband = hl2 - (multiplier * atr)

    trend = pd.Series(1, index=df.index)
    for i in range(1, len(df)):
        if df["close"].iloc[i] > upperband.iloc[i - 1]:
            trend.iloc[i] = 1
        elif df["close"].iloc[i] < lowerband.iloc[i - 1]:
            trend.iloc[i] = -1
        else:
            trend.iloc[i] = trend.iloc[i - 1]
            if trend.iloc[i] == 1 and lowerband.iloc[i] < lowerband.iloc[i - 1]:
                lowerband.iloc[i] = lowerband.iloc[i - 1]
            if trend.iloc[i] == -1 and upperband.iloc[i] > upperband.iloc[i - 1]:
                upperband.iloc[i] = upperband.iloc[i - 1]
    return trend


def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    cum_vol_price = (typical_price * df["volume"]).cumsum()
    cum_vol = df["volume"].cumsum()
    return cum_vol_price / (cum_vol + 1e-9)


def calculate_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


# ==============================================================================
# 3. STRATEGY ENGINES (S1: Supertrend + RSI + Pivot, S2: Pivot Pullback Old)
# ==============================================================================
def evaluate_strategy_1(df: pd.DataFrame, pivot_level: float) -> dict:
    """
    Strategy 1: Supertrend + RSI + Pivot Point Confluence
    - Bullish: Supertrend Bullish (1), RSI >= 50, Price > Pivot Level
    - Bearish: Supertrend Bearish (-1), RSI <= 50, Price < Pivot Level
    """
    if len(df) < 20 or pd.isna(pivot_level):
        return {"signal": None}
    df = df.copy()
    df["atr"] = calculate_atr(df, 14)
    df["rsi"] = calculate_rsi(df, 14)
    df["supertrend"] = calculate_supertrend(df, 10, 3.0)

    curr = df.iloc[-1]
    prev = df.iloc[-2]
    atr_val = curr["atr"] if not pd.isna(curr["atr"]) else (curr["high"] - curr["low"])

    # Bullish Confluence: Supertrend turns bullish (or is bullish) with RSI >= 50 and price above Pivot
    if curr["supertrend"] == 1 and curr["rsi"] >= 50 and curr["close"] > pivot_level:
        sl = round(max(curr["low"] - (0.8 * atr_val), pivot_level - (0.3 * atr_val)), 2)
        risk = curr["close"] - sl
        if risk > 0:
            return {
                "strategy": "S1 (Supertrend + RSI + Pivot)",
                "signal": "BUY / CE",
                "entry": round(curr["close"], 2),
                "sl": sl,
                "tp1": round(curr["close"] + (1.2 * risk), 2),
                "tp2": round(curr["close"] + (2.5 * risk), 2),
                "notes": f"ST Bullish | RSI: {round(curr['rsi'], 1)} | Above Pivot: ₹{pivot_level}",
            }

    # Bearish Confluence: Supertrend turns bearish (or is bearish) with RSI <= 50 and price below Pivot
    if curr["supertrend"] == -1 and curr["rsi"] <= 50 and curr["close"] < pivot_level:
        sl = round(min(curr["high"] + (0.8 * atr_val), pivot_level + (0.3 * atr_val)), 2)
        risk = sl - curr["close"]
        if risk > 0:
            return {
                "strategy": "S1 (Supertrend + RSI + Pivot)",
                "signal": "SELL / PE",
                "entry": round(curr["close"], 2),
                "sl": sl,
                "tp1": round(curr["close"] - (1.2 * risk), 2),
                "tp2": round(curr["close"] - (2.5 * risk), 2),
                "notes": f"ST Bearish | RSI: {round(curr['rsi'], 1)} | Below Pivot: ₹{pivot_level}",
            }

    return {"signal": None}


def evaluate_strategy_2(df: pd.DataFrame, pivot_level: float) -> dict:
    """
    Strategy 2: Old Pivot Pullback Strategy
    """
    if len(df) < 20 or pd.isna(pivot_level):
        return {"signal": None}
    df = df.copy()
    df["atr"] = calculate_atr(df, 14)
    df["ema20"] = calculate_ema(df["close"], 20)

    curr = df.iloc[-1]
    atr_val = curr["atr"] if not pd.isna(curr["atr"]) else (curr["high"] - curr["low"])

    is_near_pivot = abs(curr["low"] - pivot_level) <= (0.3 * atr_val)
    if is_near_pivot and curr["close"] > curr["ema20"] and curr["close"] > curr["open"]:
        sl = round(min(curr["low"], pivot_level) - (0.5 * atr_val), 2)
        risk = curr["close"] - sl
        if risk > 0:
            return {
                "strategy": "S2 (Pivot Pullback)",
                "signal": "BUY / CE",
                "entry": round(curr["close"], 2),
                "sl": sl,
                "tp1": round(curr["close"] + (1.5 * risk), 2),
                "tp2": round(curr["close"] + (3.0 * risk), 2),
                "notes": f"Pivot Support Test @ ₹{pivot_level}",
            }
    return {"signal": None}


# ==============================================================================
# 4. WATCHLIST UNIVERSE
# ==============================================================================
WATCHLIST_BLOCKS = {
    1: {
        "category": "INDEX & CORE FIN",
        "name": "Block 1: Indices & Top Banking",
        "symbols": [
            "NIFTY 50", "NIFTY BANK", "FINNIFTY", "MIDCPNIFTY",
            "HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK",
            "INDUSINDBK", "BANKBARODA", "PNB", "AUBANK", "FEDERALBNK",
            "BAJFINANCE", "BAJAJFINSV", "CHOLAFIN", "SHRIRAMFIN", "MUTHOOTFIN", "HDFCLIFE"
        ],
    },
    2: {
        "category": "TECH & CONSUMER",
        "name": "Block 2: IT, Tech & Consumer Discretionary",
        "symbols": [
            "TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM", "PERSISTENT", "COFORGE", "MPHASIS",
            "TITAN", "ASIANPAINT", "BERGEPAINT", "HAVANCE", "HAVELLS", "VOLTAS", "DIXON",
            "POLYCAB", "BOSCHLTD", "TRENT", "PAGEIND"
        ],
    },
    3: {
        "category": "AUTO & HEAVY ENG",
        "name": "Block 3: Auto, Industrials & Capital Goods",
        "symbols": [
            "TATAMOTORS", "M&M", "MARUTI", "BAJAJ-AUTO", "HEROMOTOCO", "EICHERMOT", "TVSMOTOR",
            "BHARATFORG", "ASHOKLEY", "LT", "SIEMENS", "ABB", "HAL", "BEL", "BHEL",
            "CUMMINSIND", "ASTRAL", "SUPREMEIND", "ESCORTS", "PIIND"
        ],
    },
    4: {
        "category": "ENERGY & COMMODITIES",
        "name": "Block 4: Oil/Gas, Power & Metals",
        "symbols": [
            "RELIANCE", "ONGC", "BPCL", "IOC", "GAIL", "POWERGRID", "NTPC", "TATAPOWER", "ADANIENT", "ADANIPORTS",
            "TATASTEEL", "HINDALCO", "JSWSTEEL", "JINDALSTEL", "VEDL", "COALINDIA", "NMDC", "NATIONALUM",
            "SAIL", "PETRONET"
        ],
    },
    5: {
        "category": "PHARMA & FMCG",
        "name": "Block 5: Pharma, Healthcare, FMCG & Chemicals",
        "symbols": [
            "SUNPHARMA", "CIPLA", "DRREDDY", "DIVISLAB", "LUPIN", "APOLLOHOSP", "MAXHEALTH", "MANAPPURAM",
            "AUROPHARMA", "BIOCON", "ITC", "HINDUNILVR", "NESTLEIND", "BRITANNIA", "TATACONSUM", "DABUR",
            "GODREJCP", "MARICO", "COLPAL", "SRF"
        ],
    },
}


# ==============================================================================
# 5. ALERT FORMATTING & CACHED ENTRY
# ==============================================================================
def format_alert_message(symbol: str, category: str, result: dict) -> str:
    direction_emoji = "🟢" if "BUY" in result["signal"] else "🔴"
    header_tag = "📊 <b>[INDEX ALERT]</b>" if "INDEX" in category else "📈 <b>[EQUITY F&O ALERT]</b>"

    return (
        f"{header_tag}\n"
        f"<b>Instrument:</b> <code>{symbol}</code>\n"
        f"<b>Strategy:</b> {result['strategy']}\n"
        f"<b>Action:</b> {direction_emoji} <b>{result['signal']}</b>\n"
        f"─────────────────────\n"
        f"🎯 <b>Entry:</b> ₹{result['entry']}\n"
        f"🛑 <b>Stop Loss:</b> ₹{result['sl']}\n"
        f"📌 <b>Target 1 (1R):</b> ₹{result['tp1']}\n"
        f"🚀 <b>Target 2 (2R):</b> ₹{result['tp2']}\n"
        f"─────────────────────\n"
        f"💡 <i>{result['notes']}</i>\n"
        f"⚠️ <i>Rule: Shift SL to Breakeven when Target 1 is reached. Check 6-candle time stop.</i>"
    )


sent_alerts_cache = set()

def record_trade_entry(symbol: str, category: str, setup: dict) -> bool:
    """Logs the entry details and prevents repeated spam within the day."""
    file_exists = os.path.isfile(LOG_FILE)
    today_str = datetime.now().strftime("%Y-%m-%d")

    cache_key = f"{today_str}_{symbol}_{setup['strategy']}_{setup['signal']}"
    if cache_key in sent_alerts_cache:
        return False

    if file_exists:
        try:
            existing = pd.read_csv(LOG_FILE)
            already_logged = existing[
                (existing["Date"] == today_str)
                & (existing["Symbol"] == symbol)
                & (existing["Strategy"] == setup["strategy"])
            ]
            if not already_logged.empty:
                return False
        except Exception:
            pass

    sent_alerts_cache.add(cache_key)

    with open(LOG_FILE, mode="a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "Date", "Symbol", "Category", "Strategy", "Signal",
                "Entry", "SL", "TP1", "TP2", "Status", "PnL_Points", "PnL_Pct",
            ])
        writer.writerow([
            today_str,
            symbol,
            category,
            setup["strategy"],
            setup["signal"],
            setup["entry"],
            setup["sl"],
            setup["tp1"],
            setup["tp2"],
            "OPEN",
            0.0,
            0.0,
        ])
    return True


# ==============================================================================
# 6. SCANNER EXECUTION
# ==============================================================================
def fetch_mock_data(symbol: str):
    np.random.seed(abs(hash(symbol) + int(time.time() // 30)) % 10000)
    base_price = 2500 if "NIFTY" not in symbol else 24000

    dates_15m = pd.date_range(end=pd.Timestamp.now(), periods=50, freq="15min")
    prices_15m = base_price + np.cumsum(np.random.randn(50) * 10)
    df_15m = pd.DataFrame({
        "open": prices_15m + np.random.randn(50),
        "high": prices_15m + abs(np.random.randn(50)) * 5,
        "low": prices_15m - abs(np.random.randn(50)) * 5,
        "close": prices_15m,
        "volume": np.random.randint(5000, 50000, size=50),
    }, index=dates_15m)

    dates_5m = pd.date_range(end=pd.Timestamp.now(), periods=60, freq="5min")
    prices_5m = base_price + np.cumsum(np.random.randn(60) * 5)
    df_5m = pd.DataFrame({
        "open": prices_5m + np.random.randn(60),
        "high": prices_5m + abs(np.random.randn(60)) * 3,
        "low": prices_5m - abs(np.random.randn(60)) * 3,
        "close": prices_5m,
        "volume": np.random.randint(2000, 20000, size=60),
    }, index=dates_5m)

    pdh = round(float(df_15m["high"].max() * 0.999), 2)
    pdl = round(float(df_15m["low"].min() * 1.001), 2)
    pivot = round(float((pdh + pdl + df_15m["close"].iloc[-1]) / 3), 2)
    return df_15m, df_5m, pdh, pdl, pivot


def scan_single_symbol(symbol: str, category: str):
    try:
        df_15m, df_5m, pdh, pdl, pivot = fetch_mock_data(symbol)

        # Strategy 1: Supertrend + RSI + Pivot Point confluence
        res_s1 = evaluate_strategy_1(df_15m, pivot)
        if res_s1["signal"]:
            if record_trade_entry(symbol, category, res_s1):
                send_telegram_alert(format_alert_message(symbol, category, res_s1))
            return

        # Strategy 2: Old Pivot Pullback Strategy
        res_s2 = evaluate_strategy_2(df_15m, pivot)
        if res_s2["signal"]:
            if record_trade_entry(symbol, category, res_s2):
                send_telegram_alert(format_alert_message(symbol, category, res_s2))
            return

    except Exception as e:
        logging.error(f"Error checking {symbol}: {e}")


def scan_all_blocks():
    """Iterates through all 100+ instruments across 5 sectors."""
    for block_id, block_data in WATCHLIST_BLOCKS.items():
        category = block_data["category"]
        for symbol in block_data["symbols"]:
            scan_single_symbol(symbol, category)


def run_continuous_live():
    """Continuously cycles through all instruments non-stop between 09:15 AM and 03:15 PM IST."""
    ist = pytz.timezone("Asia/Kolkata")
    logging.info("Starting NON-STOP continuous scan (09:15 AM to 03:15 PM IST)...")

    market_open = (9, 15)
    market_close = (15, 15)

    while True:
        now_ist = datetime.now(ist)
        current_time = (now_ist.hour, now_ist.minute)
        weekday = now_ist.weekday()

        # Regular trading hours: Mon-Fri 09:15 to 15:15 IST
        if weekday < 5 and market_open <= current_time <= market_close:
            scan_all_blocks()
            time.sleep(5)

        # 3:15 PM reached: cleanly exit
        elif weekday < 5 and current_time > market_close:
            logging.info("3:15 PM IST reached. Trading session finished. Exiting.")
            break

        # Outside hours / weekend: test cycle
        else:
            logging.info("Outside trading hours. Running one test cycle...")
            scan_all_blocks()
            break


if __name__ == "__main__":
    run_continuous_live()
