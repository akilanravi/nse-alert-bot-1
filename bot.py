import csv
import logging
import os
import sys
from datetime import datetime
import numpy as np
import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ==============================================================================
# 0. CONFIGURATION & TELEGRAM
# ==============================================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
LOG_FILE = "trade_log.csv"


def send_telegram_alert(message: str):
    """Dispatches HTML-formatted alert to Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.warning("Telegram credentials not configured. Printing message to stdout:\n" + message)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
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


# ==============================================================================
# 2. STRATEGY ENGINES (S1, S2, S3)
# ==============================================================================
def evaluate_strategy_1(df: pd.DataFrame) -> dict:
    """Strategy 1: Momentum Breakout (Supertrend + RSI confirmation with ATR buffer)."""
    if len(df) < 20:
        return {"signal": None}
    df = df.copy()
    df["atr"] = calculate_atr(df, 14)
    df["rsi"] = calculate_rsi(df, 14)
    df["supertrend"] = calculate_supertrend(df, 10, 3.0)

    curr = df.iloc[-1]
    prev = df.iloc[-2]
    atr_val = curr["atr"] if not pd.isna(curr["atr"]) else (curr["high"] - curr["low"])

    # Bullish Momentum
    if curr["supertrend"] == 1 and prev["supertrend"] == -1 and curr["rsi"] >= 55:
        sl = round(curr["low"] - (0.8 * atr_val), 2)
        risk = curr["close"] - sl
        if risk > 0:
            return {
                "strategy": "S1 (Momentum Breakout)",
                "signal": "BUY / CE",
                "entry": round(curr["close"], 2),
                "sl": sl,
                "tp1": round(curr["close"] + (1.2 * risk), 2),
                "tp2": round(curr["close"] + (2.5 * risk), 2),
                "notes": f"Supertrend Bullish Flip | RSI: {round(curr['rsi'], 1)}",
            }

    # Bearish Momentum
    if curr["supertrend"] == -1 and prev["supertrend"] == 1 and curr["rsi"] <= 45:
        sl = round(curr["high"] + (0.8 * atr_val), 2)
        risk = sl - curr["close"]
        if risk > 0:
            return {
                "strategy": "S1 (Momentum Breakout)",
                "signal": "SELL / PE",
                "entry": round(curr["close"], 2),
                "sl": sl,
                "tp1": round(curr["close"] - (1.2 * risk), 2),
                "tp2": round(curr["close"] - (2.5 * risk), 2),
                "notes": f"Supertrend Bearish Flip | RSI: {round(curr['rsi'], 1)}",
            }
    return {"signal": None}


def evaluate_strategy_2(df: pd.DataFrame, pivot_level: float) -> dict:
    """Strategy 2: Pullback & Value Confirmation (Testing Key HTF Pivot)."""
    if len(df) < 20 or pd.isna(pivot_level):
        return {"signal": None}
    df = df.copy()
    df["atr"] = calculate_atr(df, 14)
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()

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


def evaluate_strategy_3(df_15m: pd.DataFrame, pdh: float, pdl: float) -> dict:
    """Strategy 3: Daily Level Trap & Mean Reversal (Liquidity Sweeps)."""
    if len(df_15m) < 20 or pd.isna(pdh) or pd.isna(pdl):
        return {"signal": None}
    df = df_15m.copy()
    df["atr"] = calculate_atr(df, 14)
    df["vol_ma"] = df["volume"].rolling(window=10).mean()

    curr = df.iloc[-1]
    atr_val = curr["atr"] if not pd.isna(curr["atr"]) else (curr["high"] - curr["low"])
    vol_confirmed = curr["volume"] >= (curr["vol_ma"] * 1.05)

    # Bearish Sweep: Breaks PDH and closes back inside
    if curr["high"] > pdh and curr["close"] < pdh and vol_confirmed:
        upper_wick = curr["high"] - max(curr["open"], curr["close"])
        body = abs(curr["close"] - curr["open"])
        if upper_wick >= (body * 0.5):
            sl = round(curr["high"] + (0.5 * atr_val), 2)
            risk = sl - curr["close"]
            if risk > 0:
                return {
                    "strategy": "S3 (Daily Level Trap)",
                    "signal": "SELL / PE",
                    "entry": round(curr["close"], 2),
                    "sl": sl,
                    "tp1": round(curr["close"] - (1.3 * risk), 2),
                    "tp2": round(curr["close"] - (2.5 * risk), 2),
                    "notes": f"PDH Sweep & Reversal (PDH: ₹{pdh})",
                }

    # Bullish Sweep: Breaks PDL and closes back inside
    if curr["low"] < pdl and curr["close"] > pdl and vol_confirmed:
        lower_wick = min(curr["open"], curr["close"]) - curr["low"]
        body = abs(curr["close"] - curr["open"])
        if lower_wick >= (body * 0.5):
            sl = round(curr["low"] - (0.5 * atr_val), 2)
            risk = curr["close"] - sl
            if risk > 0:
                return {
                    "strategy": "S3 (Daily Level Trap)",
                    "signal": "BUY / CE",
                    "entry": round(curr["close"], 2),
                    "sl": sl,
                    "tp1": round(curr["close"] + (1.3 * risk), 2),
                    "tp2": round(curr["close"] + (2.5 * risk), 2),
                    "notes": f"PDL Sweep & Reversal (PDL: ₹{pdl})",
                }
    return {"signal": None}


# ==============================================================================
# 3. UNIVERSE PARTITIONING (5 DISTINCT BLOCKS)
# ==============================================================================
WATCHLIST_BLOCKS = {
    1: {
        "category": "INDEX",
        "name": "Block 1: Major Indices",
        "symbols": ["NIFTY 50", "NIFTY BANK", "FINNIFTY", "MIDCPNIFTY"],
    },
    2: {
        "category": "STOCK",
        "name": "Block 2: Banking & Financials",
        "symbols": ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK", "BAJFINANCE"],
    },
    3: {
        "category": "STOCK",
        "name": "Block 3: IT & Tech Services",
        "symbols": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM"],
    },
    4: {
        "category": "STOCK",
        "name": "Block 4: Energy, Autos & Infra",
        "symbols": ["RELIANCE", "TATAMOTORS", "M&M", "MARUTI", "LT", "NTPC"],
    },
    5: {
        "category": "STOCK",
        "name": "Block 5: Metals, Pharma & FMCG",
        "symbols": ["TATASTEEL", "HINDALCO", "SUNPHARMA", "CIPLA", "ITC", "HINDUNILVR"],
    },
}


# ==============================================================================
# 4. LOGGING & TELEGRAM FORMATTING
# ==============================================================================
def format_alert_message(symbol: str, category: str, result: dict) -> str:
    direction_emoji = "🟢" if "BUY" in result["signal"] else "🔴"
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


def record_trade_entry(symbol: str, category: str, setup: dict):
    """Logs the entry details to trade_log.csv."""
    file_exists = os.path.isfile(LOG_FILE)
    today_str = datetime.now().strftime("%Y-%m-%d")

    # Prevent recording identical triggers within the same day
    if file_exists:
        try:
            existing = pd.read_csv(LOG_FILE)
            already_logged = existing[
                (existing["Date"] == today_str)
                & (existing["Symbol"] == symbol)
                & (existing["Strategy"] == setup["strategy"])
            ]
            if not already_logged.empty:
                return
        except Exception:
            pass

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


def generate_eod_summary(get_market_data_func) -> str:
    """Evaluates all trades taken today and sends a consolidated report after 3:15 PM."""
    if not os.path.isfile(LOG_FILE):
        return "⚠️ <b>[EOD REPORT]</b> No trade log found for today."

    df_log = pd.read_csv(LOG_FILE)
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_trades = df_log[df_log["Date"] == today_str].copy()

    if today_trades.empty:
        return f"📅 <b>EOD Report ({today_str})</b>\nNo trades were recorded today."

    stats = {
        "S1": {"trades": 0, "wins": 0, "losses": 0, "points": 0.0, "pct_sum": 0.0},
        "S2": {"trades": 0, "wins": 0, "losses": 0, "points": 0.0, "pct_sum": 0.0},
        "S3": {"trades": 0, "wins": 0, "losses": 0, "points": 0.0, "pct_sum": 0.0},
    }

    trade_details_text = []

    for idx, row in today_trades.iterrows():
        symbol = row["Symbol"]
        strat_key = "S1" if "S1" in row["Strategy"] else ("S2" if "S2" in row["Strategy"] else "S3")
        signal = row["Signal"]
        entry = float(row["Entry"])
        sl = float(row["SL"])
        tp1 = float(row["TP1"])
        tp2 = float(row["TP2"])

        df_hist, _, _, _ = get_market_data_func(symbol)
        day_high = df_hist["high"].max()
        day_low = df_hist["low"].min()
        close_315 = df_hist["close"].iloc[-1]

        # Calculate outcomes
        if "BUY" in signal or "CE" in signal:
            if day_low <= sl:
                pnl_pts = sl - entry
                status = "🔴 SL Hit"
            elif day_high >= tp1:
                runner_exit = tp2 if day_high >= tp2 else close_315
                pnl_pts = (0.6 * (tp1 - entry)) + (0.4 * (runner_exit - entry))
                status = "🟢 TP Hit"
            else:
                pnl_pts = close_315 - entry
                status = "⚪ Mkt Close"
        else:  # SELL / PE
            if day_high >= sl:
                pnl_pts = entry - sl
                status = "🔴 SL Hit"
            elif day_low <= tp1:
                runner_exit = tp2 if day_low <= tp2 else close_315
                pnl_pts = (0.6 * (entry - tp1)) + (0.4 * (entry - runner_exit))
                status = "🟢 TP Hit"
            else:
                pnl_pts = entry - close_315
                status = "⚪ Mkt Close"

        pnl_pct = (pnl_pts / entry) * 100
        stats[strat_key]["trades"] += 1
        stats[strat_key]["points"] += pnl_pts
        stats[strat_key]["pct_sum"] += pnl_pct

        if pnl_pts > 0:
            stats[strat_key]["wins"] += 1
        else:
            stats[strat_key]["losses"] += 1

        trade_details_text.append(
            f"• <b>{symbol}</b> ({strat_key}): {status} | Entry: ₹{entry:.2f} | P&L: <b>{pnl_pct:+.2f}%</b> ({pnl_pts:+.2f} pts)"
        )

    total_trades = len(today_trades)
    total_wins = sum(s["wins"] for s in stats.values())
    total_losses = sum(s["losses"] for s in stats.values())
    overall_win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
    total_pct = sum(s["pct_sum"] for s in stats.values())

    message = (
        f"📋 <b>DAILY PERFORMANCE SUMMARY (3:15 PM)</b>\n"
        f"📅 Date: {today_str}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Total Trades:</b> {total_trades} (Win: {total_wins} | Loss: {total_losses})\n"
        f"🎯 <b>Win Rate:</b> {overall_win_rate:.1f}%\n"
        f"💰 <b>Total Gross Return:</b> <b>{total_pct:+.2f}%</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"<b>STRATEGY BREAKDOWN:</b>\n"
    )

    for strat, data in stats.items():
        if data["trades"] > 0:
            strat_wr = (data["wins"] / data["trades"]) * 100
            message += (
                f"🔹 <b>{strat}:</b> {data['trades']} Trades | "
                f"W: {data['wins']} L: {data['losses']} ({strat_wr:.0f}%) | "
                f"Net: <b>{data['pct_sum']:+.2f}%</b>\n"
            )
        else:
            message += f"🔹 <b>{strat}:</b> 0 Trades triggered\n"

    message += "\n<b>INDIVIDUAL TRADES:</b>\n" + "\n".join(trade_details_text)
    return message


# ==============================================================================
# 5. SCANNER RUNNER & CLI DISPATCH
# ==============================================================================
def fetch_mock_data(symbol: str):
    """
    Market data fetcher. Replace this with live Kite Connect or yfinance calls.
    """
    dates = pd.date_range(end=pd.Timestamp.now(), periods=50, freq="15min")
    np.random.seed(abs(hash(symbol)) % 10000)
    base_price = 2500 if "NIFTY" not in symbol else 24000
    prices = base_price + np.cumsum(np.random.randn(50) * 10)
    df = pd.DataFrame({
        "open": prices + np.random.randn(50),
        "high": prices + abs(np.random.randn(50)) * 5,
        "low": prices - abs(np.random.randn(50)) * 5,
        "close": prices,
        "volume": np.random.randint(5000, 50000, size=50),
    }, index=dates)

    pdh = round(float(df["high"].max() * 0.999), 2)
    pdl = round(float(df["low"].min() * 1.001), 2)
    pivot = round(float((pdh + pdl + df["close"].iloc[-1]) / 3), 2)
    return df, pdh, pdl, pivot


def scan_block(block_id: int):
    """Iterates through instruments in the designated sector block."""
    if block_id not in WATCHLIST_BLOCKS:
        logging.error(f"Invalid block_id: {block_id}. Valid range: 1 to 5.")
        return

    block_data = WATCHLIST_BLOCKS[block_id]
    category = block_data["category"]
    logging.info(f"Scanning {block_data['name']} (Type: {category})...")

    for symbol in block_data["symbols"]:
        try:
            df, pdh, pdl, pivot = fetch_mock_data(symbol)

            # Strategy 3 (Liquidity Trap) evaluated first for high win-rate priority
            res_s3 = evaluate_strategy_3(df, pdh, pdl)
            if res_s3["signal"]:
                send_telegram_alert(format_alert_message(symbol, category, res_s3))
                record_trade_entry(symbol, category, res_s3)
                continue

            # Strategy 2 (Pivot Pullback)
            res_s2 = evaluate_strategy_2(df, pivot)
            if res_s2["signal"]:
                send_telegram_alert(format_alert_message(symbol, category, res_s2))
                record_trade_entry(symbol, category, res_s2)
                continue

            # Strategy 1 (Momentum Breakout)
            res_s1 = evaluate_strategy_1(df)
            if res_s1["signal"]:
                send_telegram_alert(format_alert_message(symbol, category, res_s1))
                record_trade_entry(symbol, category, res_s1)
                continue

        except Exception as e:
            logging.error(f"Error checking {symbol}: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--eod":
        summary_msg = generate_eod_summary(fetch_mock_data)
        send_telegram_alert(summary_msg)
    else:
        target_block = int(sys.argv[1]) if len(sys.argv) > 1 else 1
        scan_block(target_block)
