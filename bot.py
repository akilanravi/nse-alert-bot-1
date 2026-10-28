import os
import sys
import logging
import requests
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ==============================================================================
# 0. CONFIGURATION & TELEGRAM
# ==============================================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def send_telegram_alert(message: str):
    """Dispatches markdown-formatted alert to Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.warning("Telegram credentials not found. Printing to console:\n" + message)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        logging.error(f"Failed to dispatch Telegram alert: {e}")

# ==============================================================================
# 1. TECHNICAL INDICATORS
# ==============================================================================
def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift(1)).abs(),
        (df['low'] - df['close'].shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))

def calculate_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0):
    atr = calculate_atr(df, period)
    hl2 = (df['high'] + df['low']) / 2
    upperband = hl2 + (multiplier * atr)
    lowerband = hl2 - (multiplier * atr)
    
    trend = pd.Series(1, index=df.index)
    for i in range(1, len(df)):
        if df['close'].iloc[i] > upperband.iloc[i-1]:
            trend.iloc[i] = 1
        elif df['close'].iloc[i] < lowerband.iloc[i-1]:
            trend.iloc[i] = -1
        else:
            trend.iloc[i] = trend.iloc[i-1]
            if trend.iloc[i] == 1 and lowerband.iloc[i] < lowerband.iloc[i-1]:
                lowerband.iloc[i] = lowerband.iloc[i-1]
            if trend.iloc[i] == -1 and upperband.iloc[i] > upperband.iloc[i-1]:
                upperband.iloc[i] = upperband.iloc[i-1]
    return trend

# ==============================================================================
# 2. STRATEGY ENGINES (S1, S2, S3)
# ==============================================================================
def evaluate_strategy_1(df: pd.DataFrame) -> dict:
    """Strategy 1: Momentum Breakout (Supertrend + RSI confirmation with ATR buffer)."""
    if len(df) < 20: return {"signal": None}
    df = df.copy()
    df['atr'] = calculate_atr(df, 14)
    df['rsi'] = calculate_rsi(df, 14)
    df['supertrend'] = calculate_supertrend(df, 10, 3.0)

    curr = df.iloc[-1]
    prev = df.iloc[-2]
    atr_val = curr['atr'] if not pd.isna(curr['atr']) else (curr['high'] - curr['low'])

    # S1 Bullish Momentum Trigger
    if curr['supertrend'] == 1 and prev['supertrend'] == -1 and curr['rsi'] >= 55:
        sl = round(curr['low'] - (0.8 * atr_val), 2)
        risk = curr['close'] - sl
        if risk > 0:
            return {
                "strategy": "S1 (Momentum Breakout)",
                "signal": "BUY / CE",
                "entry": round(curr['close'], 2),
                "sl": sl,
                "tp1": round(curr['close'] + (1.2 * risk), 2),
                "tp2": round(curr['close'] + (2.5 * risk), 2),
                "notes": f"Supertrend Flip Bullish | RSI: {round(curr['rsi'], 1)}"
            }

    # S1 Bearish Momentum Trigger
    if curr['supertrend'] == -1 and prev['supertrend'] == 1 and curr['rsi'] <= 45:
        sl = round(curr['high'] + (0.8 * atr_val), 2)
        risk = sl - curr['close']
        if risk > 0:
            return {
                "strategy": "S1 (Momentum Breakout)",
                "signal": "SELL / PE",
                "entry": round(curr['close'], 2),
                "sl": sl,
                "tp1": round(curr['close'] - (1.2 * risk), 2),
                "tp2": round(curr['close'] - (2.5 * risk), 2),
                "notes": f"Supertrend Flip Bearish | RSI: {round(curr['rsi'], 1)}"
            }
    return {"signal": None}


def evaluate_strategy_2(df: pd.DataFrame, pivot_level: float) -> dict:
    """Strategy 2: Pullback & Value Confirmation (Testing Key HTF Pivot)."""
    if len(df) < 20 or pd.isna(pivot_level): return {"signal": None}
    df = df.copy()
    df['atr'] = calculate_atr(df, 14)
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()

    curr = df.iloc[-1]
    atr_val = curr['atr'] if not pd.isna(curr['atr']) else (curr['high'] - curr['low'])

    # Pullback to Pivot within 0.3 ATR tolerance
    is_near_pivot = abs(curr['low'] - pivot_level) <= (0.3 * atr_val)
    if is_near_pivot and curr['close'] > curr['ema20'] and curr['close'] > curr['open']:
        sl = round(min(curr['low'], pivot_level) - (0.5 * atr_val), 2)
        risk = curr['close'] - sl
        if risk > 0:
            return {
                "strategy": "S2 (Pivot Pullback)",
                "signal": "BUY / CE",
                "entry": round(curr['close'], 2),
                "sl": sl,
                "tp1": round(curr['close'] + (1.5 * risk), 2),
                "tp2": round(curr['close'] + (3.0 * risk), 2),
                "notes": f"Pivot Test Bounce @ ₹{pivot_level}"
            }
    return {"signal": None}


def evaluate_strategy_3(df_15m: pd.DataFrame, pdh: float, pdl: float) -> dict:
    """Strategy 3: Daily Level Trap & Mean Reversal (Liquidity Sweeps)."""
    if len(df_15m) < 20 or pd.isna(pdh) or pd.isna(pdl): return {"signal": None}
    df = df_15m.copy()
    df['atr'] = calculate_atr(df, 14)
    df['vol_ma'] = df['volume'].rolling(window=10).mean()

    curr = df.iloc[-1]
    atr_val = curr['atr'] if not pd.isna(curr['atr']) else (curr['high'] - curr['low'])
    vol_confirmed = curr['volume'] >= (curr['vol_ma'] * 1.05)

    # Bearish Liquidity Sweep (Sweeps PDH, closes inside)
    if curr['high'] > pdh and curr['close'] < pdh and vol_confirmed:
        upper_wick = curr['high'] - max(curr['open'], curr['close'])
        body = abs(curr['close'] - curr['open'])
        if upper_wick >= (body * 0.5):
            sl = round(curr['high'] + (0.5 * atr_val), 2)
            risk = sl - curr['close']
            if risk > 0:
                return {
                    "strategy": "S3 (Daily Level Trap)",
                    "signal": "SELL / PE",
                    "entry": round(curr['close'], 2),
                    "sl": sl,
                    "tp1": round(curr['close'] - (1.3 * risk), 2),
                    "tp2": round(curr['close'] - (2.5 * risk), 2),
                    "notes": f"PDH Sweep & Reject (PDH: ₹{pdh})"
                }

    # Bullish Liquidity Sweep (Sweeps PDL, closes inside)
    if curr['low'] < pdl and curr['close'] > pdl and vol_confirmed:
        lower_wick = min(curr['open'], curr['close']) - curr['low']
        body = abs(curr['close'] - curr['open'])
        if lower_wick >= (body * 0.5):
            sl = round(curr['low'] - (0.5 * atr_val), 2)
            risk = curr['close'] - sl
            if risk > 0:
                return {
                    "strategy": "S3 (Daily Level Trap)",
                    "signal": "BUY / CE",
                    "entry": round(curr['close'], 2),
                    "sl": sl,
                    "tp1": round(curr['close'] + (1.3 * risk), 2),
                    "tp2": round(curr['close'] + (2.5 * risk), 2),
                    "notes": f"PDL Sweep & Reject (PDL: ₹{pdl})"
                }
    return {"signal": None}

# ==============================================================================
# 3. UNIVERSE PARTITIONING (5 DISTINCT BLOCKS)
# ==============================================================================
WATCHLIST_BLOCKS = {
    1: {
        "category": "INDEX",
        "name": "Block 1: Major Indices & Benchmarks",
        "symbols": ["NIFTY 50", "NIFTY BANK", "FINNIFTY", "MIDCPNIFTY"]
    },
    2: {
        "category": "STOCK",
        "name": "Block 2: Banking & Financials",
        "symbols": ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK", "BAJFINANCE"]
    },
    3: {
        "category": "STOCK",
        "name": "Block 3: IT & Tech Services",
        "symbols": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM"]
    },
    4: {
        "category": "STOCK",
        "name": "Block 4: Energy, Autos & Infra",
        "symbols": ["RELIANCE", "TATAMOTORS", "M&M", "MARUTI", "LT", "NTPC"]
    },
    5: {
        "category": "STOCK",
        "name": "Block 5: Metals, Pharma & FMCG",
        "symbols": ["TATASTEEL", "HINDALCO", "SUNPHARMA", "CIPLA", "ITC", "HINDUNILVR"]
    }
}

# ==============================================================================
# 4. TELEGRAM ALERT FORMATTER (Indices vs. Stocks)
# ==============================================================================
def format_alert_message(symbol: str, category: str, result: dict) -> str:
    direction_emoji = "🟢" if "BUY" in result['signal'] else "🔴"
    header_tag = "📊 <b>[INDEX ALERT]</b>" if category == "INDEX" else "📈 <b>[EQUITY ALERT]</b>"
    
    return (
        f"{header_tag}\n"
        f"<b>Instrument:</b> <code>{symbol}</code>\n"
        f"<b>Strategy:</b> {result['strategy']}\n"
        f"<b>Action:</b> {direction_emoji} <b>{result['signal']}</b>\n"
        f"─────────────────────\n"
        f"🎯 <b>Entry:</b> ₹{result['entry']}\n"
        f"🛑 <b>Stop Loss:</b> ₹{result['sl']}\n"
        f"📌 <b>Target 1 (60%):</b> ₹{result['tp1']}\n"
        f"🚀 <b>Target 2 (Runner):</b> ₹{result['tp2']}\n"
        f"─────────────────────\n"
        f"💡 <i>{result['notes']}</i>\n"
        f"⚠️ <i>Rule: Shift SL to Breakeven immediately when Target 1 is reached.</i>"
    )

# ==============================================================================
# 5. SCANNER ORCHESTRATION PIPELINE
# ==============================================================================
def fetch_mock_data(symbol: str):
    """
    Placeholder data generator. Replace with Kite Connect kite.historical_data() 
    or yfinance download in live deployment.
    """
    dates = pd.date_range(end=pd.Timestamp.now(), periods=50, freq='15min')
    np.random.seed(abs(hash(symbol)) % 10000)
    base_price = 2500 if "NIFTY" not in symbol else 22000
    prices = base_price + np.cumsum(np.random.randn(50) * 10)
    df = pd.DataFrame({
        "open": prices + np.random.randn(50),
        "high": prices + abs(np.random.randn(50)) * 5,
        "low": prices - abs(np.random.randn(50)) * 5,
        "close": prices,
        "volume": np.random.randint(5000, 50000, size=50)
    }, index=dates)
    pdh = df['high'].max() * 0.999
    pdl = df['low'].min() * 1.001
    pivot = (pdh + pdl + df['close'].iloc[-1]) / 3
    return df, pdh, pdl, pivot

def scan_block(block_id: int):
    """Executes strategies against a targeted universe block."""
    if block_id not in WATCHLIST_BLOCKS:
        logging.error(f"Invalid block_id: {block_id}. Valid range: 1 to 5.")
        return

    block_data = WATCHLIST_BLOCKS[block_id]
    category = block_data["category"]
    logging.info(f"Initiating scan for {block_data['name']} (Type: {category})...")

    for symbol in block_data["symbols"]:
        try:
            # 1. Obtain market data
            df, pdh, pdl, pivot = fetch_mock_data(symbol)

            # 2. Evaluate Strategies in priority order (S3 -> S2 -> S1)
            # Strategy 3 (Trap) takes precedence for high-probability reversals
            res_s3 = evaluate_strategy_3(df, pdh, pdl)
            if res_s3["signal"]:
                msg = format_alert_message(symbol, category, res_s3)
                send_telegram_alert(msg)
                continue

            # Strategy 2 (Pivot Pullback)
            res_s2 = evaluate_strategy_2(df, pivot)
            if res_s2["signal"]:
                msg = format_alert_message(symbol, category, res_s2)
                send_telegram_alert(msg)
                continue

            # Strategy 1 (Momentum Breakout)
            res_s1 = evaluate_strategy_1(df)
            if res_s1["signal"]:
                msg = format_alert_message(symbol, category, res_s1)
                send_telegram_alert(msg)
                continue

        except Exception as e:
            logging.error(f"Error evaluating {symbol}: {e}")

if __name__ == "__main__":
    # Supply block ID via CLI args: python bot.py 1 (defaults to block 1)
    target_block = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    scan_block(target_block)
