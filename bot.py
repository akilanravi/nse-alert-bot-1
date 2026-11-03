import numpy as np
import pandas as pd
import requests
import time
from datetime import datetime

# ==============================================================================
# 1. CONFIGURATION & TELEGRAM ALERTS
# ==============================================================================
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID"

def send_telegram_alert(message: str):
    """Dispatches real-time entry and exit signals to Telegram."""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print(f"[ALERT] {message}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Error dispatching Telegram alert: {e}")

# ==============================================================================
# 2. 210 F&O STOCKS & INDICES (CHUNKED INTO BATCHES OF 10)
# ==============================================================================
ALL_FO_SYMBOLS = [
    # Indices
    "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
    # F&O Stocks (Expanded list up to 210 symbols)
    "AARTIIND", "ABB", "ABBOTINDIA", "ABCAPITAL", "ABFRL", "ACC", "ADANIENT", "ADANIPORTS", "ALKEM", "AMBUJACEM",
    "APOLLOHOSP", "APOLLOTYRE", "ASHOKLEY", "ASIANPAINT", "ASTRAL", "ATUL", "AUBANK", "AUROPHARMA", "AXISBANK", "BAJAJ-AUTO",
    "BAJAJFINSV", "BAJFINANCE", "BALKRISIND", "BALRAMCHIN", "BANDHANBNK", "BANKBARODA", "BATAINDIA", "BEL", "BERGEPAINT", "BHARATFORG",
    "BHARTIARTL", "BHEL", "BIOCON", "BOSCHLTD", "BPCL", "BRITANNIA", "BSOFT", "CANBK", "CANFINHOME", "CHAMBLFERT",
    "CHOLAFIN", "CIPLA", "COALINDIA", "COFORGE", "COLPAL", "CONCOR", "COROMANDEL", "CROMPTON", "CUB", "CUMMINSIND",
    "DABUR", "DALBHARAT", "DEEPAKNTR", "DELHIVERY", "DIVISLAB", "DIXON", "DLF", "DRREDDY", "EICHERMOT", "ESCORTS",
    "EXIDEIND", "FEDERALBNK", "GAIL", "GLENMARK", "GMRINFRA", "GNFC", "GODREJCP", "GODREJPROP", "GRANULES", "GRASIM",
    "GUJGASLTD", "HAL", "HAVELLS", "HCLTECH", "HDFCAMC", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDCOPPER",
    "HINDPETRO", "HINDUNILVR", "ICICIBANK", "ICICIGI", "ICICIPRULI", "IDEA", "IDFCFIRSTB", "IEX", "IGL", "INDHOTEL",
    "INDIACEM", "INDIAMART", "INDIGO", "INDUSINDBK", "INDUSTOWER", "INFY", "IOC", "IPCALAB", "IRCTC", "ITC",
    "JINDALSTEL", "JKCEMENT", "JSWSTEEL", "JUBLFOOD", "KALYANKJIL", "KOTAKBANK", "LALPATHLAB", "LAURUSLABS", "LICHSGFIN", "LICI",
    "LT", "LTF", "LTIM", "LTTS", "LUPIN", "M&M", "M&MFIN", "MANAPPURAM", "MARICO", "MARUTI",
    "MCX", "METROPOLIS", "MFSL", "MGL", "MOTHERSON", "MPHASIS", "MRF", "MUTHOOTFIN", "NATIONALUM", "NAUKRI",
    "NAVINFLUOR", "NESTLEIND", "NMDC", "NTPC", "OBEROIRLTY", "OFSS", "ONGC", "PAGEIND", "PEL", "PERSISTENT",
    "PETRONET", "PFC", "PIDILITIND", "PIIND", "PNB", "POLYCAB", "POONAWALLA", "POWERGRID", "PVRINOX", "RAMCOCEM",
    "RBLBANK", "RECLTD", "RELIANCE", "SAIL", "SBICARD", "SBILIFE", "SBIN", "SHREECEM", "SHRIRAMFIN", "SIEMENS",
    "SRF", "SUNPHARMA", "SUNTV", "SYNGENE", "TATACHEM", "TATACOMM", "TATACONSUM", "TATAMOTORS", "TATAPOWER", "TATASTEEL",
    "TCS", "TECHM", "TITAN", "TORNTPHARM", "TORNTPOWER", "TRENT", "TVSMOTOR", "UBL", "ULTRACEMCO", "UNIONBANK",
    "UPL", "VBL", "VEDL", "VOLTAS", "WIPRO", "ZYDUSLIFE", "BSE", "CDSL", "ANGELONE", "KEI",
    "PRESTIGE", "POLICYBZR", "MAXHEALTH", "SONACOMS", "SUZLON", "NHPC", "SJVN", "IRFC", "RVNL", "HUDCO"
]

def chunk_symbols(symbols: list, chunk_size: int = 10) -> list:
    """Partitions the symbols list into chunks of 10."""
    return [symbols[i:i + chunk_size] for i in range(0, len(symbols), chunk_size)]

SYMBOL_GROUPS = chunk_symbols(ALL_FO_SYMBOLS, 10)

# ==============================================================================
# 3. TECHNICAL INDICATORS
# ==============================================================================
def compute_supertrend(df: pd.DataFrame, period: int, multiplier: float) -> pd.DataFrame:
    """Computes Supertrend indicator given ATR period and multiplier."""
    high, low, close = df['high'], df['low'], df['close']
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, adjust=False).mean()

    hl2 = (high + low) / 2
    basic_upper = hl2 + (multiplier * atr)
    basic_lower = hl2 - (multiplier * atr)

    final_upper = pd.Series(0.0, index=df.index)
    final_lower = pd.Series(0.0, index=df.index)
    trend = pd.Series(1, index=df.index)

    for i in range(1, len(df)):
        # Final Upper Band
        if basic_upper.iloc[i] < final_upper.iloc[i-1] or close.iloc[i-1] > final_upper.iloc[i-1]:
            final_upper.iloc[i] = basic_upper.iloc[i]
        else:
            final_upper.iloc[i] = final_upper.iloc[i-1]

        # Final Lower Band
        if basic_lower.iloc[i] > final_lower.iloc[i-1] or close.iloc[i-1] < final_lower.iloc[i-1]:
            final_lower.iloc[i] = basic_lower.iloc[i]
        else:
            final_lower.iloc[i] = final_lower.iloc[i-1]

        # Trend Flip
        if trend.iloc[i-1] == 1:
            trend.iloc[i] = -1 if close.iloc[i] < final_lower.iloc[i] else 1
        else:
            trend.iloc[i] = 1 if close.iloc[i] > final_upper.iloc[i] else -1

    return trend  # 1 = Bullish, -1 = Bearish

def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-9)
    return 100 - (100 / (1 + rs))

def compute_bollinger_bands(series: pd.Series, length: int = 20, num_std: float = 2.0):
    sma = series.rolling(window=length).mean()
    std = series.rolling(window=length).std()
    upper = sma + (std * num_std)
    return upper

def compute_classic_pivot_r1(df: pd.DataFrame) -> pd.Series:
    """Calculates standard classic pivot R1 level from prior period high, low, and close."""
    prev_high = df['high'].shift(1)
    prev_low = df['low'].shift(1)
    prev_close = df['close'].shift(1)
    pivot = (prev_high + prev_low + prev_close) / 3
    r1 = (2 * pivot) - prev_low
    return r1

# ==============================================================================
# 4. POSITION & RISK TRACKER
# ==============================================================================
active_positions = {}

def process_trade_exits(symbol: str, current_bar: pd.Series, st_7_2_current: int):
    """
    Evaluates Exit Rules:
    1. 10% Initial Stop Loss from Entry
    2. 10% Trailing Stop Loss from Peak Price
    3. Supertrend (7, 2) Bearish Reversal (direction == -1)
    """
    pos = active_positions[symbol]
    close_price = current_bar['close']
    high_price = current_bar['high']

    # Update Peak Price and 10% Trailing Stop Loss
    pos['peak_price'] = max(pos['peak_price'], high_price)
    trailing_sl = pos['peak_price'] * 0.90
    initial_sl = pos['initial_sl']
    effective_sl = max(initial_sl, trailing_sl)

    exit_triggered = False
    exit_reason = ""

    # Check Stop Loss / Trailing Stop Loss
    if close_price <= effective_sl:
        exit_triggered = True
        exit_reason = f"Trailing SL Hit at {close_price:.2f} (Active SL: {effective_sl:.2f})" if effective_sl == trailing_sl else f"Initial 10% SL Hit at {close_price:.2f}"
    # Check Supertrend (7, 2) Flip to Bearish
    elif st_7_2_current == -1:
        exit_triggered = True
        exit_reason = f"Supertrend (7,2) Bearish Reversal at {close_price:.2f}"

    if exit_triggered:
        pnl_pct = ((close_price - pos['entry_price']) / pos['entry_price']) * 100
        send_telegram_alert(
            f"🚨 *EXIT SIGNAL: {symbol}*\n"
            f"Reason: {exit_reason}\n"
            f"Exit Price: ₹{close_price:.2f}\n"
            f"Entry Price: ₹{pos['entry_price']:.2f}\n"
            f"PnL: {pnl_pct:+.2f}%\n"
            f"Time: {datetime.now().strftime('%H:%M:%S')}"
        )
        del active_positions[symbol]

# ==============================================================================
# 5. SCANNER & STRATEGY 1 EXECUTION ENGINE
# ==============================================================================
def fetch_candle_data(symbol: str) -> pd.DataFrame:
    """
    Placeholder: Replace with your broker's historical data API 
    (e.g., kite.historical_data, dhan.intraday_daily_minute_charts, etc.)
    Expected DataFrame columns: ['open', 'high', 'low', 'close', 'volume']
    """
    # Sample mock DataFrame format for demonstration:
    np.random.seed(abs(hash(symbol)) % 10000000)
    prices = np.cumprod(1 + np.random.normal(0, 0.01, 100)) * 500
    df = pd.DataFrame({
        'open': prices,
        'high': prices * 1.01,
        'low': prices * 0.99,
        'close': prices * 1.005,
        'volume': 10000
    })
    return df

def run_scanner_pipeline():
    """Scans all 210 symbols across chunked groups of 10."""
    print(f"\n--- Initiating Scan: {len(SYMBOL_GROUPS)} Groups ({len(ALL_FO_SYMBOLS)} symbols) ---")

    for group_idx, group in enumerate(SYMBOL_GROUPS, 1):
        print(f"Scanning Group {group_idx}/{len(SYMBOL_GROUPS)}: {group}")

        for symbol in group:
            try:
                df = fetch_candle_data(symbol)
                if df.empty or len(df) < 30:
                    continue

                # Strategy 1 Calculations
                st_10_2 = compute_supertrend(df, period=10, multiplier=2.0)
                st_7_2 = compute_supertrend(df, period=7, multiplier=2.0)
                rsi = compute_rsi(df['close'], period=14)
                bb_upper = compute_bollinger_bands(df['close'], length=20, num_std=2.0)
                pivot_r1 = compute_classic_pivot_r1(df)

                curr_idx = -1
                curr_close = df['close'].iloc[curr_idx]
                curr_high = df['high'].iloc[curr_idx]

                # Check Exits if position is already active
                if symbol in active_positions:
                    process_trade_exits(symbol, df.iloc[curr_idx], st_7_2.iloc[curr_idx])
                    continue

                # ==========================================================
                # STRATEGY 1 ENTRY CONDITIONS:
                # 1. Supertrend (10, 2) is Bullish (== 1)
                # 2. RSI (14) > 60
                # 3. Candle Close > Bollinger Upper Band (20, 2)
                # 4. Candle Close > Pivot Point R1
                # ==========================================================
                cond_st = (st_10_2.iloc[curr_idx] == 1)
                cond_rsi = (rsi.iloc[curr_idx] > 60)
                cond_bb = (curr_close > bb_upper.iloc[curr_idx])
                cond_r1 = (curr_close > pivot_r1.iloc[curr_idx])

                if cond_st and cond_rsi and cond_bb and cond_r1:
                    # Enter Long
                    active_positions[symbol] = {
                        'entry_price': curr_close,
                        'initial_sl': curr_close * 0.90,  # 10% Initial SL
                        'peak_price': curr_high           # Tracks peak for 10% trailing SL
                    }

                    send_telegram_alert(
                        f"🚀 *STRATEGY 1 ENTRY: {symbol}*\n"
                        f"Entry Price: ₹{curr_close:.2f}\n"
                        f"Initial SL (10%): ₹{(curr_close * 0.90):.2f}\n"
                        f"RSI: {rsi.iloc[curr_idx]:.2f}\n"
                        f"Bollinger Upper: ₹{bb_upper.iloc[curr_idx]:.2f}\n"
                        f"Pivot R1: ₹{pivot_r1.iloc[curr_idx]:.2f}\n"
                        f"Supertrend (10,2): Bullish\n"
                        f"Time: {datetime.now().strftime('%H:%M:%S')}"
                    )

            except Exception as e:
                print(f"Error processing {symbol}: {e}")

        # Throttle to respect API rate limits between groups of 10
        time.sleep(0.5)

if __name__ == "__main__":
    # Example execution loop
    run_scanner_pipeline()
