import argparse
import datetime as dt
import json
import math
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytz
import requests
import yfinance as yf

# ============================================================
# CONFIGURATION - YAHOO FINANCE ONLY
# ============================================================

IST = pytz.timezone("Asia/Kolkata")
TIMEFRAME = "5m"
ATR_MULTIPLIER = 1.5
S2_RR_RATIO = 2.0
POLL_SECONDS = 300

PIVOT_CACHE = {}
SWING_CACHE = {}

# ============================================================
# FIVE ORIGINAL SECTOR GROUPS
# ============================================================

SECTOR_MAPS = {
    "indices_banking": {
        "^NSEI": 50, "^NSEBANK": 100, "^BSESN": 100,
        "NIFTY_FIN_SERVICE.NS": 50,
        "HDFCBANK.NS": 20, "ICICIBANK.NS": 10,
        "SBIN.NS": 10, "KOTAKBANK.NS": 20,
        "AXISBANK.NS": 10, "BAJFINANCE.NS": 50,
        "BAJAJFINSV.NS": 20, "INDUSINDBK.NS": 20,
        "FEDERALBNK.NS": 2.5, "AUBANK.NS": 10,
        "BANDHANBNK.NS": 2.5, "IDFCFIRSTB.NS": 1,
        "PNB.NS": 1, "BANKBARODA.NS": 2.5,
        "CANBK.NS": 1, "CHOLAFIN.NS": 20,
        "SHRIRAMFIN.NS": 25, "MUTHOOTFIN.NS": 20,
        "M&MFIN.NS": 5, "PFC.NS": 5,
        "RECLTD.NS": 5, "SBICARD.NS": 10,
        "SBILIFE.NS": 20, "HDFCLIFE.NS": 10
    },

    "it_energy": {
        "TCS.NS": 50, "INFY.NS": 20,
        "HCLTECH.NS": 20, "WIPRO.NS": 5,
        "TECHM.NS": 20, "PERSISTENT.NS": 50,
        "COFORGE.NS": 50, "MPHASIS.NS": 25,
        "NAUKRI.NS": 50, "RELIANCE.NS": 20,
        "ONGC.NS": 2.5, "BPCL.NS": 5,
        "IOC.NS": 1, "GAIL.NS": 2.5,
        "NTPC.NS": 5, "POWERGRID.NS": 2.5,
        "TATAPOWER.NS": 5, "ADANIENT.NS": 50,
        "ADANIPORTS.NS": 20, "COALINDIA.NS": 5
    },

    "auto_metals": {
        "MARUTI.NS": 100, "M&M.NS": 20,
        "BAJAJ-AUTO.NS": 100, "EICHERMOT.NS": 50,
        "HEROMOTOCO.NS": 50, "TVSMOTOR.NS": 25,
        "BHARATFORG.NS": 20, "ASHOKLEY.NS": 2.5,
        "MRF.NS": 500, "BALKRISIND.NS": 50,
        "APOLLOTYRE.NS": 5, "TATASTEEL.NS": 1,
        "JSWSTEEL.NS": 10, "HINDALCO.NS": 10,
        "JINDALSTEL.NS": 10, "VEDL.NS": 5,
        "NMDC.NS": 2.5, "SAIL.NS": 1,
        "NATIONALUM.NS": 2.5
    },

    "pharma_fmcg": {
        "SUNPHARMA.NS": 20, "DRREDDY.NS": 50,
        "CIPLA.NS": 20, "DIVISLAB.NS": 50,
        "APOLLOHOSP.NS": 50, "LUPIN.NS": 20,
        "AUROPHARMA.NS": 20, "BIOCON.NS": 5,
        "TORNTPHARM.NS": 50, "ZYDUSLIFE.NS": 10,
        "HINDUNILVR.NS": 20, "ITC.NS": 5,
        "NESTLEIND.NS": 20, "BRITANNIA.NS": 50,
        "TATACONSUM.NS": 10, "DABUR.NS": 5,
        "MARICO.NS": 5, "COLPAL.NS": 25,
        "GODREJCP.NS": 10
    },

    "telecom_infra_chem": {
        "BHARTIARTL.NS": 10, "TRENT.NS": 50,
        "TITAN.NS": 50, "ASIANPAINT.NS": 20,
        "BERGEPAINT.NS": 5, "INDIGO.NS": 50,
        "HAVELLS.NS": 20, "DIXON.NS": 100,
        "POLYCAB.NS": 50, "VOLTAS.NS": 20,
        "JUBLFOOD.NS": 5, "LT.NS": 50,
        "SIEMENS.NS": 50, "ABB.NS": 50,
        "BHEL.NS": 2.5, "HAL.NS": 50,
        "BEL.NS": 2.5, "CUMMINSIND.NS": 50,
        "DLF.NS": 10, "GODREJPROP.NS": 50,
        "OBEROIRLTY.NS": 20, "ULTRACEMCO.NS": 100,
        "GRASIM.NS": 20, "AMBUJACEM.NS": 5,
        "SHREECEM.NS": 250, "PIDILITIND.NS": 20,
        "SRF.NS": 25, "PIIND.NS": 50
    }
}


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    recipients = [
        (
            os.getenv("TELEGRAM_BOT_TOKEN_1", "8721771664:AAFcyCX2TP2KsUrIQoh6utZvHjbLQt8vD-k"),
            os.getenv("TELEGRAM_CHAT_ID_1", "846124589")
        ),
        (
            os.getenv("TELEGRAM_BOT_TOKEN_2", "8764996383:AAE_vevTjJ76zfK3g3rYGgsZB3_EtkbvUms"),
            os.getenv("TELEGRAM_CHAT_ID_2", "8865083462")
        )
    ]

    delivered = 0

    for token, chat_id in recipients:
        if not token or not chat_id:
            continue

        try:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": message,
                    "disable_web_page_preview": True
                },
                timeout=15
            )
            response.raise_for_status()
            delivered += 1

        except requests.RequestException as exc:
            print(f"Telegram delivery error: {exc}")

    if delivered == 0:
        print("Telegram message was not delivered to any configured recipient.")


# ============================================================
# MARKET TIME
# ============================================================

def current_time():
    return dt.datetime.now(IST)


def market_status():
    now = current_time()
    minutes = now.hour * 60 + now.minute

    if now.weekday() >= 5:
        return False, False, False, now

    market_start = 9 * 60 + 30
    market_close = 15 * 60 + 15
    entry_close = 15 * 60

    running = market_start <= minutes <= market_close
    entry_allowed = market_start <= minutes <= entry_close
    squareoff = minutes >= market_close

    return running, entry_allowed, squareoff, now


# ============================================================
# TRADE STATE
# ============================================================

def default_position():
    return {
        "in_trade": False,
        "trade_type": "",
        "entry_price": 0.0,
        "extreme_price": 0.0,
        "trailing_sl": 0.0,
        "initial_risk": 0.0,
        "target_1": 0.0,
        "target_2": 0.0,
        "t1_hit": False,
        "atm_strike": 0,
        "itm_strike": 0,
        "candles_held": 0,
        "entry_time": "",
        "swing_signal_key": ""
    }


def load_state(filename, symbols):
    state = {
        "positions": {
            symbol: default_position() for symbol in symbols
        },
        "closed_trades": [],
        "last_processed": {}
    }

    path = Path(filename)

    if not path.exists():
        return state

    try:
        saved = json.loads(path.read_text(encoding="utf-8"))

        state["closed_trades"] = saved.get("closed_trades", [])
        state["last_processed"] = saved.get("last_processed", {})

        for symbol in symbols:
            if symbol in saved.get("positions", {}):
                position = default_position()
                position.update(saved["positions"][symbol])
                state["positions"][symbol] = position

    except (OSError, ValueError, TypeError) as exc:
        print(f"State load warning {filename}: {exc}")

    return state


def save_state(filename, state):
    Path(filename).write_text(
        json.dumps(state, indent=2, default=str),
        encoding="utf-8"
    )


# ============================================================
# YAHOO FINANCE DATA
# ============================================================

def download_data(ticker, period, interval):
    try:
        data = yf.download(
            ticker,
            period=period,
            interval=interval,
            auto_adjust=False,
            progress=False,
            threads=False
        )

        if data is None or data.empty:
            print(f"{ticker}: no Yahoo data returned.")
            return pd.DataFrame()

        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        data = data.loc[:, ~data.columns.duplicated()]

        required = ["Open", "High", "Low", "Close", "Volume"]

        if not all(column in data.columns for column in required):
            print(f"{ticker}: required OHLCV columns missing.")
            return pd.DataFrame()

        data = data[required].dropna(
            subset=["Open", "High", "Low", "Close"]
        )

        data = data[~data.index.duplicated(keep="last")]

        return data.sort_index()

    except Exception as exc:
        print(f"{ticker}: Yahoo download error: {exc}")
        return pd.DataFrame()


def completed_five_minute_bars(data):
    if data.empty:
        return data

    index = data.index

    if index.tz is None:
        index = index.tz_localize(IST)
    else:
        index = index.tz_convert(IST)

    result = data.copy()
    result.index = index

    cutoff = (
        pd.Timestamp.now(tz=IST).floor("5min")
        - pd.Timedelta(minutes=5)
    )

    return result.loc[result.index <= cutoff]


# ============================================================
# DAILY PIVOT, PDH AND PDL
# ============================================================

def daily_pivot(ticker):
    today = current_time().date().isoformat()

    if ticker in PIVOT_CACHE:
        cached = PIVOT_CACHE[ticker]

        if cached["date"] == today:
            return cached["value"]

    data = download_data(ticker, "1mo", "1d")

    if len(data) < 2:
        return None

    previous = data.iloc[-2]

    high = float(previous.High)
    low = float(previous.Low)
    close = float(previous.Close)

    pivot = (high + low + close) / 3

    result = {
        "p": pivot,
        "r1": 2 * pivot - low,
        "s1": 2 * pivot - high,
        "pdh": high,
        "pdl": low
    }

    PIVOT_CACHE[ticker] = {
        "date": today,
        "value": result
    }

    return result


# ============================================================
# INDICATORS
# ============================================================

def calculate_atr(data, period=14):
    previous_close = data.Close.shift()

    true_range = pd.concat(
        [
            data.High - data.Low,
            (data.High - previous_close).abs(),
            (data.Low - previous_close).abs()
        ],
        axis=1
    ).max(axis=1)

    return true_range.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()


def calculate_rsi(series, period=14):
    delta = series.diff()

    gain = delta.clip(lower=0).ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    loss = (-delta.clip(upper=0)).ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    rs = gain / loss.replace(0, np.nan)
    result = 100 - 100 / (1 + rs)

    return result.mask(loss.eq(0), 100)


def calculate_cci(data, period=20):
    typical = (data.High + data.Low + data.Close) / 3
    average = typical.rolling(period).mean()

    deviation = typical.rolling(period).apply(
        lambda values: np.mean(
            np.abs(values - np.mean(values))
        ),
        raw=True
    )

    return (
        (typical - average)
        / (0.015 * deviation.replace(0, np.nan))
    )


def calculate_williams_r(data, period=14):
    highest = data.High.rolling(period).max()
    lowest = data.Low.rolling(period).min()

    return (
        -100 * (highest - data.Close)
        / (highest - lowest).replace(0, np.nan)
    )


def calculate_bollinger(series, period=20, multiplier=2):
    middle = series.rolling(period).mean()
    deviation = series.rolling(period).std()

    upper = middle + multiplier * deviation
    lower = middle - multiplier * deviation

    return middle, upper, lower


def calculate_supertrend(data, period=10, multiplier=2):
    atr_value = calculate_atr(data, period)
    midpoint = (data.High + data.Low) / 2

    upper = midpoint + multiplier * atr_value
    lower = midpoint - multiplier * atr_value

    final_upper = upper.copy()
    final_lower = lower.copy()

    direction = pd.Series(
        1, index=data.index, dtype=int
    )

    line = pd.Series(
        np.nan, index=data.index, dtype=float
    )

    for i in range(1, len(data)):
        final_upper.iloc[i] = (
            upper.iloc[i]
            if (
                upper.iloc[i] < final_upper.iloc[i - 1]
                or data.Close.iloc[i - 1] > final_upper.iloc[i - 1]
            )
            else final_upper.iloc[i - 1]
        )

        final_lower.iloc[i] = (
            lower.iloc[i]
            if (
                lower.iloc[i] > final_lower.iloc[i - 1]
                or data.Close.iloc[i - 1] < final_lower.iloc[i - 1]
            )
            else final_lower.iloc[i - 1]
        )

        if direction.iloc[i - 1] == -1:
            direction.iloc[i] = (
                1
                if data.Close.iloc[i] > final_upper.iloc[i]
                else -1
            )
        else:
            direction.iloc[i] = (
                -1
                if data.Close.iloc[i] < final_lower.iloc[i]
                else 1
            )

        line.iloc[i] = (
            final_lower.iloc[i]
            if direction.iloc[i] == 1
            else final_upper.iloc[i]
        )

    return line, direction


def calculate_vwap(data):
    typical = (
        data.High + data.Low + data.Close
    ) / 3

    volume = data.Volume.fillna(0)

    dates = pd.Index(data.index.date)

    cumulative_value = (
        typical * volume
    ).groupby(dates).cumsum()

    cumulative_volume = (
        volume.groupby(dates)
        .cumsum()
        .replace(0, np.nan)
    )

    return cumulative_value / cumulative_volume


# ============================================================
# INDICATIVE OPTION STRIKES
# ============================================================

def get_strikes(price, step, direction):
    atm = round(price / step) * step

    if direction == "CALL":
        itm = atm - step
    else:
        itm = atm + step

    def format_strike(value):
        return (
            str(int(value))
            if float(value).is_integer()
            else f"{value:g}"
        )

    return format_strike(atm), format_strike(itm)


# ============================================================
# TRADE CLOSING
# P&L = UNDERLYING SPOT POINTS ONLY
# ============================================================

def close_trade(
    state, ticker, position,
    exit_price, reason, strategy
):
    direction = position["trade_type"]

    if direction == "CALL":
        pnl = exit_price - position["entry_price"]
    else:
        pnl = position["entry_price"] - exit_price

    state["closed_trades"].append({
        "date": current_time().date().isoformat(),
        "time": current_time().strftime("%H:%M:%S"),
        "ticker": ticker,
        "strategy": strategy,
        "type": direction,
        "strike_suggestion": position.get("itm_strike"),
        "entry": round(position["entry_price"], 2),
        "exit": round(exit_price, 2),
        "pnl": round(pnl, 2),
        "pnl_unit": "underlying_spot_points",
        "reason": reason
    })

    return pnl


# ============================================================
# S1 AND S2 - INTRADAY SCANNER
# ============================================================

def scan_intraday_symbol(
    ticker, step, state1, state2,
    data, pivot, entry_allowed, squareoff
):
    if len(data) < 220 or pivot is None:
        return

    df = data.copy()

    # Shared Indicators
    df["VWAP"] = calculate_vwap(df)
    df["ATR"] = calculate_atr(df, 14)
    df["ST"], df["DIR"] = calculate_supertrend(df, 10, 2)
    df["EMA20"] = df.Close.ewm(span=20, adjust=False).mean()
    df["EMA50"] = df.Close.ewm(span=50, adjust=False).mean()
    df["EMA200"] = df.Close.ewm(span=200, adjust=False).mean()
    df["VOL_MA20"] = df.Volume.rolling(20).mean()

    # S1-Specific Indicators
    df["RSI20"] = calculate_rsi(df.Close, 20)
    df["CCI"] = calculate_cci(df)
    df["WR"] = calculate_williams_r(df)
    _, df["BBU"], df["BBL"] = calculate_bollinger(df.Close)

    # S2-Specific Indicators
    df["RSI14"] = calculate_rsi(df.Close, 14)

    df = df.dropna()

    if len(df) < 3:
        return

    current = df.iloc[-1]
    previous = df.iloc[-2]

    bar_id = df.index[-1].isoformat()

    if (
        state1["last_processed"].get(ticker) == bar_id
        and state2["last_processed"].get(ticker) == bar_id
    ):
        return

    state1["last_processed"][ticker] = bar_id
    state2["last_processed"][ticker] = bar_id

    close = float(current.Close)
    high = float(current.High)
    low = float(current.Low)

    st = float(current.ST)
    st_direction = int(current.DIR)

    bear_flip = (st_direction == -1 and int(previous.DIR) == 1)
    bull_flip = (st_direction == 1 and int(previous.DIR) == -1)

    pivot_r1 = pivot["r1"]
    pivot_s1 = pivot["s1"]

    name = ticker.replace(".NS", "")
    name = name.replace("^NSEI", "NIFTY 50")
    name = name.replace("^NSEBANK", "BANK NIFTY")
    name = name.replace("^BSESN", "SENSEX")

    # --------------------------------------------------------
    # S1 ENTRY CONDITIONS (ORIGINAL)
    # --------------------------------------------------------

    s1_call = (
        close > st
        and close > current.EMA200
        and current.RSI20 > 60
        and current.CCI > 100
        and current.WR > -20
        and close > pivot_r1
        and close > current.BBU
    )

    s1_put = (
        close < st
        and close < current.EMA200
        and current.RSI20 < 40
        and current.CCI < -100
        and current.WR < -80
        and close < pivot_s1
        and close < current.BBL
    )

    # --------------------------------------------------------
    # S2 ENTRY CONDITIONS (AI MULTI-FACTOR REGIME & CONFLUENCE)
    # --------------------------------------------------------

    # Regime Filter
    is_bullish_regime = close > current.EMA200
    is_bearish_regime = close < current.EMA200

    # Fast / Slow EMA Crossover
    ema_crossover = (previous.EMA20 <= previous.EMA50) and (current.EMA20 > current.EMA50)
    ema_crossunder = (previous.EMA20 >= previous.EMA50) and (current.EMA20 < current.EMA50)

    # Confluence Scoring (Target >= 2)
    score_long = 0
    score_long += 1 if current.EMA20 > current.EMA50 else 0
    score_long += 1 if (50 < current.RSI14 < 70) else 0
    score_long += 1 if (current.Volume > current.VOL_MA20) else 0

    score_short = 0
    score_short += 1 if current.EMA20 < current.EMA50 else 0
    score_short += 1 if (30 < current.RSI14 < 50) else 0
    score_short += 1 if (current.Volume > current.VOL_MA20) else 0

    s2_call = is_bullish_regime and (score_long >= 2) and ema_crossover
    s2_put = is_bearish_regime and (score_short >= 2) and ema_crossunder

    # ========================================================
    # S1 POSITION MANAGEMENT
    # ========================================================

    pos1 = state1["positions"].setdefault(ticker, default_position())

    if pos1["in_trade"]:
        typ = pos1["trade_type"]

        if squareoff:
            pnl = close_trade(state1, name, pos1, close, "15:15 EOD", "S1")
            send_telegram(f"S1 EOD EXIT {name} {typ}: {pnl:+.2f} underlying spot points")
            pos1 = default_position()

        elif typ == "CALL":
            if not pos1["t1_hit"] and high >= pos1["target_1"]:
                pos1["t1_hit"] = True
                pos1["trailing_sl"] = pos1["entry_price"]
                send_telegram(f"S1 CALL {name}: 1R reached. Illustrative partial-booking alert.")

            if high >= pos1["target_2"]:
                pnl = close_trade(state1, name, pos1, pos1["target_2"], "2R target", "S1")
                send_telegram(f"S1 CALL {name}: 2R exit | {pnl:+.2f} underlying spot points")
                pos1 = default_position()

            elif close <= pos1["trailing_sl"] or bear_flip or close < st:
                pnl = close_trade(state1, name, pos1, close, "Stop / Supertrend reversal", "S1")
                send_telegram(f"S1 CALL EXIT {name}: {pnl:+.2f} underlying spot points")
                pos1 = default_position()

        else:
            if not pos1["t1_hit"] and low <= pos1["target_1"]:
                pos1["t1_hit"] = True
                pos1["trailing_sl"] = pos1["entry_price"]
                send_telegram(f"S1 PUT {name}: 1R reached. Illustrative partial-booking alert.")

            if low <= pos1["target_2"]:
                pnl = close_trade(state1, name, pos1, pos1["target_2"], "2R target", "S1")
                send_telegram(f"S1 PUT {name}: 2R exit | {pnl:+.2f} underlying spot points")
                pos1 = default_position()

            elif close >= pos1["trailing_sl"] or bull_flip or close > st:
                pnl = close_trade(state1, name, pos1, close, "Stop / Supertrend reversal", "S1")
                send_telegram(f"S1 PUT EXIT {name}: {pnl:+.2f} underlying spot points")
                pos1 = default_position()

    elif entry_allowed and (s1_call or s1_put):
        typ = "CALL" if s1_call else "PUT"
        atm, itm = get_strikes(close, step, typ)

        if typ == "CALL":
            stop = min(st, float(df.Low.iloc[-3:].min())) * 0.999
            risk = close - stop
            target1 = close + risk
            target2 = close + 2 * risk
        else:
            stop = max(st, float(df.High.iloc[-3:].max())) * 1.001
            risk = stop - close
            target1 = close - risk
            target2 = close - 2 * risk

        if risk > 0 and math.isfinite(risk):
            pos1.update({
                "in_trade": True,
                "trade_type": typ,
                "entry_price": close,
                "extreme_price": high if typ == "CALL" else low,
                "trailing_sl": stop,
                "initial_risk": risk,
                "target_1": target1,
                "target_2": target2,
                "t1_hit": False,
                "atm_strike": atm,
                "itm_strike": itm,
                "entry_time": current_time().isoformat()
            })

            send_telegram(
                f"S1 {typ} SIGNAL: {name}\n"
                f"Underlying: {close:.2f}\n"
                f"Indicative ATM: {atm} | ITM: {itm}\n"
                f"Underlying SL: {stop:.2f}\n"
                f"Underlying T1: {target1:.2f} | T2: {target2:.2f}\n"
                "Yahoo underlying signal only."
            )

    state1["positions"][ticker] = pos1

    # ========================================================
    # S2 POSITION MANAGEMENT (NEW MULTI-FACTOR ENGINE)
    # ========================================================

    pos2 = state2["positions"].setdefault(ticker, default_position())

    if pos2["in_trade"]:
        pos2["candles_held"] += 1
        typ = pos2["trade_type"]

        exit_price = None
        reason = ""

        if squareoff:
            exit_price = close
            reason = "15:15 EOD"

        elif typ == "CALL":
            # SL hit
            if low <= pos2["trailing_sl"]:
                exit_price = pos2["trailing_sl"]
                reason = "S2 Stop-Loss hit"
            # 2R Target hit
            elif high >= pos2["target_2"]:
                exit_price = pos2["target_2"]
                reason = "S2 2R Target reached"
            # Emergency Exit: Regime breakdown below 200 EMA
            elif close < current.EMA200:
                exit_price = close
                reason = "S2 Regime Breakdown (< 200 EMA)"

        else:  # PUT
            # SL hit
            if high >= pos2["trailing_sl"]:
                exit_price = pos2["trailing_sl"]
                reason = "S2 Stop-Loss hit"
            # 2R Target hit
            elif low <= pos2["target_2"]:
                exit_price = pos2["target_2"]
                reason = "S2 2R Target reached"
            # Emergency Exit: Regime reversal above 200 EMA
            elif close > current.EMA200:
                exit_price = close
                reason = "S2 Regime Reversal (> 200 EMA)"

        if reason and exit_price is not None:
            pnl = close_trade(state2, name, pos2, exit_price, reason, "S2")
            send_telegram(
                f"S2 {typ} EXIT {name}: {reason}\n"
                f"Exit: {exit_price:.2f}\n"
                f"Underlying: {pnl:+.2f} points"
            )
            pos2 = default_position()

    elif entry_allowed and (s2_call or s2_put):
        typ = "CALL" if s2_call else "PUT"
        atm, itm = get_strikes(close, step, typ)
        atr_val = float(current.ATR)
        risk = atr_val * ATR_MULTIPLIER

        if risk > 0 and math.isfinite(risk):
            if typ == "CALL":
                stop = close - risk
                target2 = close + (risk * S2_RR_RATIO)
                target1 = close + risk
            else:
                stop = close + risk
                target2 = close - (risk * S2_RR_RATIO)
                target1 = close - risk

            pos2.update({
                "in_trade": True,
                "trade_type": typ,
                "entry_price": close,
                "extreme_price": high if typ == "CALL" else low,
                "trailing_sl": stop,
                "initial_risk": risk,
                "target_1": target1,
                "target_2": target2,
                "atm_strike": atm,
                "itm_strike": itm,
                "candles_held": 0,
                "entry_time": current_time().isoformat()
            })

            send_telegram(
                f"S2 {typ} CONFLUENCE SIGNAL: {name}\n"
                f"Underlying: {close:.2f}\n"
                f"Indicative ATM: {atm} | ITM: {itm}\n"
                f"Underlying SL: {stop:.2f}\n"
                f"Underlying 2R Target: {target2:.2f}\n"
                "Multi-factor Regime + 20/50 EMA Cross."
            )

    state2["positions"][ticker] = pos2


# ============================================================
# S3 - LIQUIDITY SWEEP AND RECLAIM
# ============================================================

def scan_s3_symbol(
    ticker, step, state3, data, pivot,
    entry_allowed, squareoff
):
    if len(data) < 30 or pivot is None:
        return

    df = data.copy()

    df["VWAP"] = calculate_vwap(df)
    df["ATR"] = calculate_atr(df, 14)
    df["RSI"] = calculate_rsi(df.Close, 14)
    df["VOL_MA"] = df.Volume.rolling(20).mean()

    df = df.dropna()

    if len(df) < 22:
        return

    current = df.iloc[-1]
    bar_id = df.index[-1].isoformat()

    if state3["last_processed"].get(ticker) == bar_id:
        return

    state3["last_processed"][ticker] = bar_id

    close = float(current.Close)
    open_price = float(current.Open)
    high = float(current.High)
    low = float(current.Low)

    atr = float(current.ATR)
    vwap = float(current.VWAP)
    rsi = float(current.RSI)
    volume = float(current.Volume)
    volume_average = float(current.VOL_MA)

    pdh = float(pivot["pdh"])
    pdl = float(pivot["pdl"])

    name = ticker.replace(".NS", "")
    name = name.replace("^NSEI", "NIFTY 50")
    name = name.replace("^NSEBANK", "BANK NIFTY")
    name = name.replace("^BSESN", "SENSEX")

    # Sweep below previous-day low and reclaim.
    bullish_reclaim = (
        low < pdl
        and close > pdl
        and close > open_price
        and close > vwap
        and rsi > 50
        and volume > 1.2 * volume_average
    )

    # Sweep above previous-day high and reject.
    bearish_reclaim = (
        high > pdh
        and close < pdh
        and close < open_price
        and close < vwap
        and rsi < 50
        and volume > 1.2 * volume_average
    )

    pos = state3["positions"].setdefault(ticker, default_position())

    # --------------------------------------------------------
    # MANAGE EXISTING S3 TRADE
    # --------------------------------------------------------

    if pos["in_trade"]:
        typ = pos["trade_type"]

        if typ == "CALL":
            stop_hit = low <= pos["trailing_sl"]
            target_hit = high >= pos["target_2"]
        else:
            stop_hit = high >= pos["trailing_sl"]
            target_hit = low <= pos["target_2"]

        if squareoff:
            exit_price = close
            reason = "15:15 EOD"
        elif stop_hit:
            exit_price = pos["trailing_sl"]
            reason = "S3 stop-loss"
        elif target_hit:
            exit_price = pos["target_2"]
            reason = "S3 2R target"
        else:
            exit_price = None
            reason = ""

        if exit_price is not None:
            pnl = close_trade(state3, name, pos, exit_price, reason, "S3")
            send_telegram(
                f"S3 {typ} EXIT: {name}\n"
                f"Reason: {reason}\n"
                f"Exit: {exit_price:.2f}\n"
                f"Underlying points: {pnl:+.2f}"
            )
            pos = default_position()

    # --------------------------------------------------------
    # NEW S3 CALL
    # --------------------------------------------------------

    elif entry_allowed and bullish_reclaim:
        stop = low - (0.15 * atr)
        risk = close - stop

        if risk > 0 and math.isfinite(risk):
            target = close + (2 * risk)
            atm, itm = get_strikes(close, step, "CALL")

            pos.update({
                "in_trade": True,
                "trade_type": "CALL",
                "entry_price": close,
                "extreme_price": low,
                "trailing_sl": stop,
                "initial_risk": risk,
                "target_1": close + risk,
                "target_2": target,
                "atm_strike": atm,
                "itm_strike": itm,
                "entry_time": current_time().isoformat()
            })

            send_telegram(
                f"S3 CALL LIQUIDITY RECLAIM\n"
                f"Symbol: {name}\n"
                f"Entry: {close:.2f}\n"
                f"Previous Day Low: {pdl:.2f}\n"
                f"Indicative ATM: {atm} | ITM: {itm}\n"
                f"Underlying SL: {stop:.2f}\n"
                f"Underlying 2R target: {target:.2f}\n"
                "Yahoo underlying signal only."
            )

    # --------------------------------------------------------
    # NEW S3 PUT
    # --------------------------------------------------------

    elif entry_allowed and bearish_reclaim:
        stop = high + (0.15 * atr)
        risk = stop - close

        if risk > 0 and math.isfinite(risk):
            target = close - (2 * risk)
            atm, itm = get_strikes(close, step, "PUT")

            pos.update({
                "in_trade": True,
                "trade_type": "PUT",
                "entry_price": close,
                "extreme_price": high,
                "trailing_sl": stop,
                "initial_risk": risk,
                "target_1": close - risk,
                "target_2": target,
                "atm_strike": atm,
                "itm_strike": itm,
                "entry_time": current_time().isoformat()
            })

            send_telegram(
                f"S3 PUT LIQUIDITY RECLAIM\n"
                f"Symbol: {name}\n"
                f"Entry: {close:.2f}\n"
                f"Previous Day High: {pdh:.2f}\n"
                f"Indicative ATM: {atm} | ITM: {itm}\n"
                f"Underlying SL: {stop:.2f}\n"
                f"Underlying 2R target: {target:.2f}\n"
                "Yahoo underlying signal only."
            )

    state3["positions"][ticker] = pos


# ============================================================
# SWING SCANNER
# WEEKLY + DAILY + 4-HOUR TREND ALIGNMENT
# ============================================================

def swing_signal(ticker, step):
    today = current_time().date().isoformat()

    cached = SWING_CACHE.get(ticker)

    if cached and cached["date"] == today:
        return cached["signal"]

    daily = download_data(ticker, "2y", "1d")
    hourly = download_data(ticker, "730d", "1h")

    if len(daily) < 60 or len(hourly) < 80:
        SWING_CACHE[ticker] = {
            "date": today,
            "signal": None
        }
        return None

    daily = daily.copy()
    daily["EMA20"] = daily.Close.ewm(span=20, adjust=False).mean()
    daily["EMA50"] = daily.Close.ewm(span=50, adjust=False).mean()

    weekly = daily.resample("W-FRI").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum"
    }).dropna()

    if len(weekly) < 20:
        SWING_CACHE[ticker] = {
            "date": today,
            "signal": None
        }
        return None

    weekly["EMA20"] = weekly.Close.ewm(span=20, adjust=False).mean()

    four_hour = hourly.resample("4h").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum"
    }).dropna()

    if len(four_hour) < 30:
        SWING_CACHE[ticker] = {
            "date": today,
            "signal": None
        }
        return None

    four_hour["EMA20"] = four_hour.Close.ewm(span=20, adjust=False).mean()
    four_hour["EMA50"] = four_hour.Close.ewm(span=50, adjust=False).mean()

    d = daily.iloc[-1]
    w = weekly.iloc[-1]
    h = four_hour.iloc[-1]

    price = float(d.Close)

    bullish = (
        d.Close > d.EMA20 > d.EMA50
        and w.Close > w.EMA20
        and h.Close > h.EMA20 > h.EMA50
    )

    bearish = (
        d.Close < d.EMA20 < d.EMA50
        and w.Close < w.EMA20
        and h.Close < h.EMA20 < h.EMA50
    )

    if not bullish and not bearish:
        SWING_CACHE[ticker] = {
            "date": today,
            "signal": None
        }
        return None

    typ = "CALL" if bullish else "PUT"
    atm, itm = get_strikes(price, step, typ)

    signal = {
        "type": typ,
        "price": price,
        "atm": atm,
        "itm": itm
    }

    SWING_CACHE[ticker] = {
        "date": today,
        "signal": signal
    }

    return signal


# ============================================================
# MAIN SCAN ENGINE
# ============================================================

def run_scan(group):
    running, entry_allowed, squareoff, now = market_status()

    if not running:
        print(f"{group}: outside market session ({now:%H:%M:%S} IST)")
        return

    symbols = list(SECTOR_MAPS[group])

    file_s1 = f"trade_state_s1_{group}.json"
    file_s2 = f"trade_state_s2_{group}.json"
    file_s3 = f"trade_state_s3_{group}.json"
    file_sw = f"trade_state_swing_{group}.json"

    state1 = load_state(file_s1, symbols)
    state2 = load_state(file_s2, symbols)
    state3 = load_state(file_s3, symbols)
    swing_state = load_state(file_sw, symbols)

    print(f"{group}: scanning {len(symbols)} tickers at {now:%H:%M:%S} IST")

    for ticker, step in SECTOR_MAPS[group].items():
        try:
            raw = download_data(ticker, "7d", TIMEFRAME)
            bars = completed_five_minute_bars(raw)

            if len(bars) >= 220:
                pivot = daily_pivot(ticker)

                scan_intraday_symbol(
                    ticker,
                    step,
                    state1,
                    state2,
                    bars,
                    pivot,
                    entry_allowed,
                    squareoff
                )

                # Strategy 3
                scan_s3_symbol(
                    ticker,
                    step,
                    state3,
                    bars,
                    pivot,
                    entry_allowed,
                    squareoff
                )

            # Swing scan once per ticker per trading day
            last_checked = swing_state["last_processed"].get(ticker, "")
            today = now.date().isoformat()

            if last_checked != today:
                signal = swing_signal(ticker, step)

                if signal:
                    telegram_key = f"{today}:{signal['type']}"

                    old_key = (
                        swing_state["positions"]
                        .get(ticker, {})
                        .get("swing_signal_key", "")
                    )

                    if old_key != telegram_key:
                        send_telegram(
                            f"SWING {signal['type']} SETUP: {ticker}\n"
                            f"Underlying: {signal['price']:.2f}\n"
                            f"Indicative ATM: {signal['atm']} | ITM: {signal['itm']}\n"
                            "Weekly + Daily + 4H alignment.\n"
                            "Yahoo underlying signal only."
                        )

                    swing_state["positions"].setdefault(
                        ticker, default_position()
                    )["swing_signal_key"] = telegram_key

                swing_state["last_processed"][ticker] = today

        except Exception as exc:
            print(f"{group} / {ticker}: scan error: {exc}")

    save_state(file_s1, state1)
    save_state(file_s2, state2)
    save_state(file_s3, state3)
    save_state(file_sw, swing_state)

    print(f"{group}: scan completed.")


# ============================================================
# DAILY REPORT - S1, S2 AND S3
# ============================================================

def generate_report():
    today = current_time().date().isoformat()

    report_lines = [
        f"DAILY SCANNER REPORT | {today}",
        "Yahoo Finance underlying data.",
        "P&L = underlying spot points, NOT option premium P&L."
    ]

    combined = 0.0

    for strategy in ("s1", "s2", "s3"):
        trades = []

        for group in SECTOR_MAPS:
            filename = Path(f"trade_state_{strategy}_{group}.json")

            if not filename.exists():
                continue

            try:
                saved = json.loads(filename.read_text(encoding="utf-8"))
                trades.extend(
                    trade
                    for trade in saved.get("closed_trades", [])
                    if trade.get("date") == today
                )
            except Exception as exc:
                print(f"Report read error {filename}: {exc}")

        wins = [trade for trade in trades if float(trade.get("pnl", 0)) > 0]
        losses = [trade for trade in trades if float(trade.get("pnl", 0)) < 0]
        pnl = sum(float(trade.get("pnl", 0)) for trade in trades)

        combined += pnl
        win_rate = (100 * len(wins) / len(trades) if trades else 0)

        report_lines.extend([
            "",
            f"{strategy.upper()}: {len(trades)} closed trades",
            f"Wins: {len(wins)} | Losses: {len(losses)}",
            f"Win rate: {win_rate:.1f}%",
            f"Net: {pnl:+.2f} underlying spot points"
        ])

    report_lines.extend([
        "",
        f"Combined S1 + S2 + S3: {combined:+.2f} underlying spot points",
        "",
        "Swing alerts are separate trend setups.",
        "No option premium, brokerage, slippage or statutory charges are included."
    ])

    message = "\n".join(report_lines)

    print(message)
    send_telegram(message)


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--group",
        choices=list(SECTOR_MAPS)
    )

    parser.add_argument(
        "--report",
        action="store_true"
    )

    args = parser.parse_args()

    if args.report:
        generate_report()
        return

    if not args.group:
        parser.error("Specify --group or --report")

    group = args.group

    print(f"Yahoo-only scanner started: {group}; {len(SECTOR_MAPS[group])} tickers.")

    while True:
        running, _, _, now = market_status()

        if now.weekday() >= 5:
            print("Weekend. Worker stopped.")
            break

        if now.hour * 60 + now.minute > 15 * 60 + 15:
            print("Market session finished.")
            break

        if running:
            run_scan(group)
        else:
            print(f"Waiting for 09:30 IST. Current time: {now:%H:%M:%S}")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
