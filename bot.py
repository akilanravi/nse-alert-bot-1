import csv
import logging
import os
import sys
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
# 3. STRATEGY ENGINES (S1, S2, S3, S4)
# ==============================================================================
def evaluate_strategy_1(df: pd.DataFrame) -> dict:
    """Strategy 1: Momentum Breakout (Supertrend + RSI confirmation)."""
    if len(df) < 20:
        return {"signal": None}
    df = df.copy()
    df["atr"] = calculate_atr(df, 14)
    df["rsi"] = calculate_rsi(df, 14)
    df["supertrend"] = calculate_supertrend(df, 10, 3.0)

    curr = df.iloc[-1]
    prev = df.iloc[-2]
    atr_val = curr["atr"] if not pd.isna(curr["atr"]) else (curr["high"] - curr["low"])

    # Bullish CE
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

    # Bearish PE
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

    # Bearish Sweep (PE)
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

    # Bullish Sweep (CE)
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


def evaluate_strategy_4(symbol: str, df_5m: pd.DataFrame, df_15m: pd.DataFrame) -> dict:
    """Strategy 4: Intraday Indian F&O Framework."""
    if len(df_5m) < 25 or len(df_15m) < 20:
        return {"signal": None}

    df_15 = df_15m.copy()
    df_15["vwap"] = calculate_vwap(df_15)
    c_15 = df_15.iloc[-1]
    p_15 = df_15.iloc[-2]

    trend_15m_bullish = (c_15["close"] > c_15["vwap"]) and (c_15["vwap"] >= p_15["vwap"])
    trend_15m_bearish = (c_15["close"] < c_15["vwap"]) and (c_15["vwap"] <= p_15["vwap"])

    df_5 = df_5m.copy()
    df_5["vwap"] = calculate_vwap(df_5)
    df_5["ema9"] = calculate_ema(df_5["close"], 9)
    df_5["ema21"] = calculate_ema(df_5["close"], 21)
    df_5["rsi"] = calculate_rsi(df_5, 14)
    df_5["vol_ma20"] = df_5["volume"].rolling(20).mean()

    curr = df_5.iloc[-1]
    prev = df_5.iloc[-2]

    range_high = df_5["high"].iloc[-21:-1].max()
    range_low = df_5["low"].iloc[-21:-1].min()

    # SETUP A: BREAKOUT & RETEST (CE)
    if trend_15m_bullish and curr["close"] > curr["vwap"]:
        breakout_candidates = [
            i for i in range(2, min(8, len(df_5)))
            if df_5["close"].iloc[-i] > range_high and df_5["volume"].iloc[-i] > df_5["vol_ma20"].iloc[-i]
        ]
        if breakout_candidates:
            if curr["low"] <= (range_high * 1.002) and curr["close"] > range_high and curr["close"] > curr["open"]:
                retest_swing_low = df_5["low"].iloc[-max(breakout_candidates):].min()
                sl = round(min(retest_swing_low, range_high * 0.998), 2)
                risk = curr["close"] - sl
                if risk > 0:
                    return {
                        "strategy": "S4 (Breakout & Retest)",
                        "signal": "BUY / CE",
                        "entry": round(curr["close"], 2),
                        "sl": sl,
                        "tp1": round(curr["close"] + (1.0 * risk), 2),
                        "tp2": round(curr["close"] + (2.0 * risk), 2),
                        "notes": f"5m Retest Confirmed @ ₹{range_high:.2f} | 15m VWAP Rising | Risk: {risk:.2f} pts",
                    }

    # SETUP A: BREAKDOWN & RETEST (PE)
    if trend_15m_bearish and curr["close"] < curr["vwap"]:
        breakdown_candidates = [
            i for i in range(2, min(8, len(df_5)))
            if df_5["close"].iloc[-i] < range_low and df_5["volume"].iloc[-i] > df_5["vol_ma20"].iloc[-i]
        ]
        if breakdown_candidates:
            if curr["high"] >= (range_low * 0.998) and curr["close"] < range_low and curr["close"] < curr["open"]:
                retest_swing_high = df_5["high"].iloc[-max(breakdown_candidates):].max()
                sl = round(max(retest_swing_high, range_low * 1.002), 2)
                risk = sl - curr["close"]
                if risk > 0:
                    return {
                        "strategy": "S4 (Breakout & Retest)",
                        "signal": "SELL / PE",
                        "entry": round(curr["close"], 2),
                        "sl": sl,
                        "tp1": round(curr["close"] - (1.0 * risk), 2),
                        "tp2": round(curr["close"] - (2.0 * risk), 2),
                        "notes": f"5m Breakdown Retest Failed @ ₹{range_low:.2f} | 15m VWAP Falling | Risk: {risk:.2f} pts",
                    }

    # SETUP B: TREND PULLBACK (CE)
    if trend_15m_bullish and curr["close"] > curr["vwap"]:
        ema_aligned = curr["ema9"] > curr["ema21"]
        pulled_to_ema21 = abs(curr["low"] - curr["ema21"]) <= (curr["close"] * 0.003) or (curr["low"] <= curr["ema21"] and curr["close"] >= curr["ema21"])
        rsi_turning_up = curr["rsi"] > prev["rsi"] and curr["rsi"] >= 50
        bullish_close = curr["close"] > curr["open"] and curr["close"] > prev["high"]

        if ema_aligned and pulled_to_ema21 and rsi_turning_up and bullish_close:
            sl = round(df_5["low"].iloc[-5:].min(), 2)
            risk = curr["close"] - sl
            if risk > 0:
                return {
                    "strategy": "S4 (Trend Pullback)",
                    "signal": "BUY / CE",
                    "entry": round(curr["close"], 2),
                    "sl": sl,
                    "tp1": round(curr["close"] + (1.0 * risk), 2),
                    "tp2": round(curr["close"] + (2.0 * risk), 2),
                    "notes": f"Pullback to EMA 21 | RSI: {curr['rsi']:.1f} ↗ | Risk: {risk:.2f} pts",
                }

    # SETUP B: TREND PULLBACK (PE)
    if trend_15m_bearish and curr["close"] < curr["vwap"]:
        ema_aligned = curr["ema9"] < curr["ema21"]
        pulled_to_ema21 = abs(curr["high"] - curr["ema21"]) <= (curr["close"] * 0.003) or (curr["high"] >= curr["ema21"] and curr["close"] <= curr["ema21"])
        rsi_turning_down = curr["rsi"] < prev["rsi"] and curr["rsi"] <= 50
        bearish_close = curr["close"] < curr["open"] and curr["close"] < prev["low"]

        if ema_aligned and pulled_to_ema21 and rsi_turning_down and bearish_close:
            sl = round(df_5["high"].iloc[-5:].max(), 2)
            risk = sl - curr["close"]
            if risk > 0:
                return {
                    "strategy": "S4 (Trend Pullback)",
                    "signal": "SELL / PE",
                    "entry": round(curr["close"], 2),
                    "sl": sl,
                    "tp1": round(curr["close"] - (1.0 * risk), 2),
                    "tp2": round(curr["close"] - (2.0 * risk), 2),
                    "notes": f"Pullback to EMA 21 | RSI: {curr['rsi']:.1f} ↘ | Risk: {risk:.2f} pts",
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
# 5. ALERT FORMATTING & LOGGING
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


def record_trade_entry(symbol: str, category: str, setup: dict):
    """Logs the entry details to trade_log.csv."""
    file_exists = os.path.isfile(LOG_FILE)
    today_str = datetime.now().strftime("%Y-%m-%d")

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
    """Consolidated summary sent to both Telegram recipients at 3:15 PM."""
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
        "S4": {"trades": 0, "wins": 0, "losses": 0, "points": 0.0, "pct_sum": 0.0},
    }

    trade_details_text = []

    for idx, row in today_trades.iterrows():
        symbol = row["Symbol"]
        strat_str = str(row["Strategy"])
        if "S1" in strat_str:
            strat_key = "S1"
        elif "S2" in strat_str:
            strat_key = "S2"
        elif "S3" in strat_str:
            strat_key = "S3"
        elif "S4" in strat_str:
            strat_key = "S4"
        else:
            strat_key = "S1"

        signal = row["Signal"]
        entry = float(row["Entry"])
        sl = float(row["SL"])
        tp1 = float(row["TP1"])
        tp2 = float(row["TP2"])

        df_15m, _, _, _, _ = get_market_data_func(symbol)
        day_high = df_15m["high"].max()
        day_low = df_15m["low"].min()
        close_315 = df_15m["close"].iloc[-1]

        if "BUY" in signal or "CE" in signal:
            if day_low <= sl:
                pnl_pts = sl - entry
                status = "🔴 SL Hit"
            elif day_high >= tp1:
                runner_exit = tp2 if day_high >= tp2 else close_315
                pnl_pts = (0.5 * (tp1 - entry)) + (0.5 * (runner_exit - entry))
                status = "🟢 TP Hit"
            else:
                pnl_pts = close_315 - entry
                status = "⚪ Mkt Close"
        else:
            if day_high >= sl:
                pnl_pts = entry - sl
                status = "🔴 SL Hit"
            elif day_low <= tp1:
                runner_exit = tp2 if day_low <= tp2 else close_315
                pnl_pts = (0.5 * (entry - tp1)) + (0.5 * (entry - runner_exit))
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
# 6. SCANNER EXECUTION & LIVE CONTINUOUS LOOP
# ==============================================================================
def fetch_mock_data(symbol: str):
    """Generates aligned 15m and 5m market data. Replace with your live broker API feed."""
    np.random.seed(abs(hash(symbol)) % 10000)
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


def scan_block(block_id: int):
    """Iterates through instruments in the designated sector block."""
    if block_id not in WATCHLIST_BLOCKS:
        logging.error(f"Invalid block_id: {block_id}. Valid range: 1 to 5.")
        return

    block_data = WATCHLIST_BLOCKS[block_id]
    category = block_data["category"]
    logging.info(f"Scanning {block_data['name']} ({len(block_data['symbols'])} symbols)...")

    for symbol in block_data["symbols"]:
        try:
            df_15m, df_5m, pdh, pdl, pivot = fetch_mock_data(symbol)

            # Strategy 4: Intraday CALL/PUT Framework
            res_s4 = evaluate_strategy_4(symbol, df_5m, df_15m)
            if res_s4["signal"]:
                send_telegram_alert(format_alert_message(symbol, category, res_s4))
                record_trade_entry(symbol, category, res_s4)
                continue

            # Strategy 3: Daily Level Trap & Sweeps
            res_s3 = evaluate_strategy_3(df_15m, pdh, pdl)
            if res_s3["signal"]:
                send_telegram_alert(format_alert_message(symbol, category, res_s3))
                record_trade_entry(symbol, category, res_s3)
                continue

            # Strategy 2: Pivot Pullback
            res_s2 = evaluate_strategy_2(df_15m, pivot)
            if res_s2["signal"]:
                send_telegram_alert(format_alert_message(symbol, category, res_s2))
                record_trade_entry(symbol, category, res_s2)
                continue

            # Strategy 1: Momentum Breakout
            res_s1 = evaluate_strategy_1(df_15m)
            if res_s1["signal"]:
                send_telegram_alert(format_alert_message(symbol, category, res_s1))
                record_trade_entry(symbol, category, res_s1)
                continue

        except Exception as e:
            logging.error(f"Error checking {symbol}: {e}")


def scan_all_blocks():
    """Scans all 5 watchlist blocks sequentially."""
    for block_id in sorted(WATCHLIST_BLOCKS.keys()):
        scan_block(block_id)


def run_continuous_session():
    """Runs continuously from 09:15 AM to 03:15 PM IST."""
    ist = pytz.timezone("Asia/Kolkata")
    logging.info("Starting continuous live market scanning loop (IST timezone)...")

    market_open = (9, 15)
    market_close = (15, 15)
    eod_sent = False

    while True:
        now_ist = datetime.now(ist)
        current_time = (now_ist.hour, now_ist.minute)
        weekday = now_ist.weekday()  # 0 = Monday, 4 = Friday

        logging.info(f"Current IST Time: {now_ist.strftime('%Y-%m-%d %H:%M:%S')} (Day: {weekday})")

        # During live trading hours (Mon-Fri 09:15 - 15:15 IST)
        if weekday < 5 and market_open <= current_time <= market_close:
            logging.info("--- [LIVE SCAN CYCLE STARTED] ---")
            scan_all_blocks()
            logging.info("--- [LIVE SCAN COMPLETED] Sleeping for 15 minutes... ---")
            time.sleep(900)

        # Market close reached (Past 3:15 PM IST)
        elif weekday < 5 and current_time > market_close:
            if not eod_sent:
                logging.info("Market session closed. Generating and dispatching EOD report...")
                summary_msg = generate_eod_summary(fetch_mock_data)
                send_telegram_alert(summary_msg)
                eod_sent = True
            logging.info("Trading day finished. Shutting down runner.")
            break

        # Outside regular trading hours (e.g. testing manual dispatch at night or weekends)
        else:
            logging.warning("Outside regular trading hours (09:15 - 15:15 IST Mon-Fri). Performing a single test scan...")
            scan_all_blocks()
            break


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--eod":
        summary_msg = generate_eod_summary(fetch_mock_data)
        send_telegram_alert(summary_msg)
    elif len(sys.argv) > 1 and sys.argv[1] == "--live":
        run_continuous_session()
    elif len(sys.argv) > 1 and sys.argv[1] == "--all":
        scan_all_blocks()
    elif len(sys.argv) > 1 and sys.argv[1].isdigit():
        target_block = int(sys.argv[1])
        scan_block(target_block)
    else:
        scan_all_blocks()
