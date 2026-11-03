import argparse
import datetime as dt
import json
import logging
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
# CONFIGURATION & RECIPIENTS
# ============================================================

TELEGRAM_RECIPIENTS = [
    ("8721771664:AAFcyCX2TP2KsUrIQoh6utZvHjbLQt8vD-k", "846124589"),
    ("8764996383:AAE_vevTjJ76zfK3g3rYGgsZB3_EtkbvUms", "8865083462"),
]

WATCHLIST = {
    # INDICES & BANKING
    "^NSEI": 50, "^NSEBANK": 100, "^BSESN": 100, "NIFTY_FIN_SERVICE.NS": 50,
    "HDFCBANK.NS": 20, "ICICIBANK.NS": 10, "SBIN.NS": 10, "KOTAKBANK.NS": 20,
    "AXISBANK.NS": 10, "BAJFINANCE.NS": 50, "BAJAJFINSV.NS": 20, "INDUSINDBK.NS": 20,
    "FEDERALBNK.NS": 2.5, "AUBANK.NS": 10, "BANDHANBNK.NS": 2.5, "IDFCFIRSTB.NS": 1,
    "PNB.NS": 1, "BANKBARODA.NS": 2.5, "CANBK.NS": 1, "CHOLAFIN.NS": 20,
    "SHRIRAMFIN.NS": 25, "MUTHOOTFIN.NS": 20, "M&MFIN.NS": 5, "PFC.NS": 5,
    "RECLTD.NS": 5, "SBICARD.NS": 10, "SBILIFE.NS": 20, "HDFCLIFE.NS": 10,
    # IT & ENERGY
    "TCS.NS": 50, "INFY.NS": 20, "HCLTECH.NS": 20, "WIPRO.NS": 5,
    "TECHM.NS": 20, "PERSISTENT.NS": 50, "COFORGE.NS": 50, "MPHASIS.NS": 25, "NAUKRI.NS": 50,
    "RELIANCE.NS": 20, "ONGC.NS": 2.5, "BPCL.NS": 5, "IOC.NS": 1,
    "GAIL.NS": 2.5, "NTPC.NS": 5, "POWERGRID.NS": 2.5, "TATAPOWER.NS": 5,
    "ADANIENT.NS": 50, "ADANIPORTS.NS": 20, "COALINDIA.NS": 5,
    # AUTO & METALS
    "MARUTI.NS": 100, "M&M.NS": 20, "BAJAJ-AUTO.NS": 100, "EICHERMOT.NS": 50,
    "HEROMOTOCO.NS": 50, "TVSMOTOR.NS": 25, "BHARATFORG.NS": 20, "ASHOKLEY.NS": 2.5,
    "MRF.NS": 500, "BALKRISIND.NS": 50, "APOLLOTYRE.NS": 5,
    "TATASTEEL.NS": 1, "JSWSTEEL.NS": 10, "HINDALCO.NS": 10, "JINDALSTEL.NS": 10,
    "VEDL.NS": 5, "NMDC.NS": 2.5, "SAIL.NS": 1, "NATIONALUM.NS": 2.5,
    # PHARMA & FMCG
    "SUNPHARMA.NS": 20, "DRREDDY.NS": 50, "CIPLA.NS": 20, "DIVISLAB.NS": 50,
    "APOLLOHOSP.NS": 50, "LUPIN.NS": 20, "AUROPHARMA.NS": 20, "BIOCON.NS": 5,
    "TORNTPHARM.NS": 50, "ZYDUSLIFE.NS": 10, "HINDUNILVR.NS": 20, "ITC.NS": 5,
    "NESTLEIND.NS": 20, "BRITANNIA.NS": 50, "TATACONSUM.NS": 10, "DABUR.NS": 5,
    "MARICO.NS": 5, "COLPAL.NS": 25, "GODREJCP.NS": 10,
    # TELECOM, INFRA & CHEMICALS
    "BHARTIARTL.NS": 10, "TRENT.NS": 50, "TITAN.NS": 50, "ASIANPAINT.NS": 20,
    "BERGEPAINT.NS": 5, "INDIGO.NS": 50, "HAVELLS.NS": 20, "DIXON.NS": 100,
    "POLYCAB.NS": 50, "VOLTAS.NS": 20, "JUBLFOOD.NS": 5, "LT.NS": 50,
    "SIEMENS.NS": 50, "ABB.NS": 50, "BHEL.NS": 2.5, "HAL.NS": 50,
    "BEL.NS": 2.5, "CUMMINSIND.NS": 50, "DLF.NS": 10, "GODREJPROP.NS": 50,
    "OBEROIRLTY.NS": 20, "ULTRACEMCO.NS": 100, "GRASIM.NS": 20, "AMBUJACEM.NS": 5,
    "SHREECEM.NS": 250, "PIDILITIND.NS": 20, "SRF.NS": 25, "PIIND.NS": 50
}

TIMEFRAME = "5m"
ATR_PERIOD = 14
ATR_MULTIPLIER = 1.5
S2_MIN_ATR = 20.0
VOLUME_MULTIPLIER = 1.20
STATE_FILE = Path(os.getenv("STATE_FILE", "trade_state_master.json"))
IST = pytz.timezone("Asia/Kolkata")
SCAN_START_MINUTES = 9 * 60 + 30
SCAN_END_MINUTES = 15 * 60 + 15
SCAN_INTERVAL_SECONDS = 300
PULSE_MINUTES = (15, 45)
YF_BATCH_SIZE = 30

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)

def send_telegram(message):
    """Dispatches Telegram notifications with automatic plain text fallback."""
    for token, chat_id in TELEGRAM_RECIPIENTS:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            # 1. Attempt with Markdown parsing
            res = requests.post(
                url,
                json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True},
                timeout=15,
            )
            # 2. If Markdown fails due to special characters, fallback to plain text immediately
            if not res.ok:
                logging.warning("Markdown formatting rejected (%s). Retrying as plain text...", res.text)
                requests.post(
                    url,
                    json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
                    timeout=15,
                )
        except requests.RequestException as exc:
            logging.error("Telegram network failure for chat %s: %s", chat_id, exc)

def get_default_item_state():
    return {
        "in_trade": False, "pending_stage": None, "trade_type": "",
        "entry_price": 0.0, "entry_time": None, "extreme_price": 0.0,
        "trailing_sl": 0.0, "trail_buffer": 0.0, "atm_strike": 0,
        "itm_strike": 0, "strategy": ""
    }

def load_state(symbols):
    state = {
        "s1_positions": {s: get_default_item_state() for s in symbols},
        "s2_positions": {s: get_default_item_state() for s in symbols},
        "closed_trades": []
    }
    if not STATE_FILE.exists():
        return state
    try:
        saved = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        state["closed_trades"] = saved.get("closed_trades", [])
        
        saved_s1 = saved.get("s1_positions", saved.get("positions", {}))
        saved_s2 = saved.get("s2_positions", {})
        
        for symbol in symbols:
            if symbol in saved_s1 and isinstance(saved_s1[symbol], dict):
                m1 = get_default_item_state()
                m1.update(saved_s1[symbol])
                state["s1_positions"][symbol] = m1
            if symbol in saved_s2 and isinstance(saved_s2[symbol], dict):
                m2 = get_default_item_state()
                m2.update(saved_s2[symbol])
                state["s2_positions"][symbol] = m2
    except Exception as exc:
        logging.exception("Could not parse existing state; reinitializing: %s", exc)
    return state

def save_state(state):
    tmp = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    tmp.replace(STATE_FILE)

def get_options_strikes(price, step, direction="CALL"):
    step = float(step)
    if step <= 0:
        return None, None
    atm = round(float(price) / step) * step
    itm = atm - step if direction == "CALL" else atm + step
    def fmt(value):
        return int(value) if float(value).is_integer() else round(value, 2)
    return fmt(atm), fmt(itm)

def extract_ticker_frame(data, ticker):
    if data is None or data.empty:
        return pd.DataFrame()
    if not isinstance(data.columns, pd.MultiIndex):
        return data.copy()
    for level in range(data.columns.nlevels):
        values = data.columns.get_level_values(level)
        if ticker in values:
            try:
                frame = data.xs(ticker, axis=1, level=level, drop_level=True)
                if isinstance(frame.columns, pd.MultiIndex):
                    frame.columns = frame.columns.get_level_values(-1)
                return frame.copy()
            except (KeyError, ValueError):
                pass
    return pd.DataFrame()

def normalize_ohlcv(frame):
    if frame is None or frame.empty:
        return pd.DataFrame()
    frame = frame.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(-1)
    frame.columns = [str(c).title() for c in frame.columns]
    required = ["Open", "High", "Low", "Close", "Volume"]
    if not all(c in frame.columns for c in required):
        return pd.DataFrame()
    frame = frame[required].apply(pd.to_numeric, errors="coerce").dropna(subset=["Open", "High", "Low", "Close"])
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    return frame

def keep_completed_intraday_bars(frame, now=None):
    if frame.empty:
        return frame
    now = now or dt.datetime.now(IST)
    idx = pd.DatetimeIndex(frame.index)
    if idx.tz is None:
        idx = idx.tz_localize(IST)
    else:
        idx = idx.tz_convert(IST)
    frame = frame.copy()
    frame.index = idx
    cutoff = pd.Timestamp(now).tz_convert(IST) if pd.Timestamp(now).tzinfo else pd.Timestamp(now, tz=IST)
    return frame.loc[(frame.index + pd.Timedelta(minutes=5)) <= cutoff]

def calculate_vwap(frame):
    typical_price = (frame["High"] + frame["Low"] + frame["Close"]) / 3.0
    vol = frame["Volume"].replace(0, 1)
    return (typical_price * vol).cumsum() / vol.cumsum()

def calculate_atr(frame, period=ATR_PERIOD):
    prev_close = frame["Close"].shift(1)
    tr = pd.concat([
        frame["High"] - frame["Low"],
        (frame["High"] - prev_close).abs(),
        (frame["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.mask((loss == 0) & (gain > 0), 100)
    rsi = rsi.mask((gain == 0) & (loss > 0), 0)
    return rsi

def calculate_bollinger_bands(series, period=20, mult=2.0):
    middle = series.rolling(period).mean()
    std = series.rolling(period).std()
    return middle + mult * std, middle - mult * std

def calculate_supertrend(frame, period=10, multiplier=3.0):
    atr = calculate_atr(frame, period)
    hl2 = (frame["High"] + frame["Low"]) / 2
    basic_upper = hl2 + multiplier * atr
    basic_lower = hl2 - multiplier * atr
    final_upper = basic_upper.copy()
    final_lower = basic_lower.copy()
    close = frame["Close"]

    for i in range(1, len(frame)):
        if pd.isna(final_upper.iloc[i - 1]) or pd.isna(final_lower.iloc[i - 1]):
            continue
        final_upper.iloc[i] = (
            basic_upper.iloc[i]
            if basic_upper.iloc[i] < final_upper.iloc[i - 1] or close.iloc[i - 1] > final_upper.iloc[i - 1]
            else final_upper.iloc[i - 1]
        )
        final_lower.iloc[i] = (
            basic_lower.iloc[i]
            if basic_lower.iloc[i] > final_lower.iloc[i - 1] or close.iloc[i - 1] < final_lower.iloc[i - 1]
            else final_lower.iloc[i - 1]
        )

    st = pd.Series(index=frame.index, dtype=float)
    direction = pd.Series(index=frame.index, dtype=float)
    for i in range(len(frame)):
        if pd.isna(final_upper.iloc[i]) or pd.isna(final_lower.iloc[i]):
            continue
        if i == 0 or pd.isna(direction.iloc[i - 1]):
            direction.iloc[i] = 1
            st.iloc[i] = final_lower.iloc[i]
        elif direction.iloc[i - 1] == 1:
            if close.iloc[i] < final_lower.iloc[i]:
                direction.iloc[i] = -1
                st.iloc[i] = final_upper.iloc[i]
            else:
                direction.iloc[i] = 1
                st.iloc[i] = final_lower.iloc[i]
        else:
            if close.iloc[i] > final_upper.iloc[i]:
                direction.iloc[i] = 1
                st.iloc[i] = final_lower.iloc[i]
            else:
                direction.iloc[i] = -1
                st.iloc[i] = final_upper.iloc[i]
    return st, direction

def get_daily_context(tickers):
    context = {}
    for start in range(0, len(tickers), YF_BATCH_SIZE):
        batch = tickers[start:start + YF_BATCH_SIZE]
        try:
            raw = yf.download(
                batch, period="1mo", interval="1d", progress=False,
                group_by="ticker", threads=True, auto_adjust=False,
            )
        except Exception as exc:
            logging.warning("Daily download failed for batch %s: %s", batch[0], exc)
            continue
        for ticker in batch:
            frame = normalize_ohlcv(extract_ticker_frame(raw, ticker))
            if len(frame) < 3:
                continue
            prev = frame.iloc[-2]
            high, low, close = map(float, (prev["High"], prev["Low"], prev["Close"]))
            pivot = (high + low + close) / 3.0
            context[ticker] = {
                "pivot_p": pivot, "pivot_r1": 2 * pivot - low,
                "pivot_s1": 2 * pivot - high, "prev_close": close,
            }
    return context

def download_intraday(tickers):
    frames = {}
    for start in range(0, len(tickers), YF_BATCH_SIZE):
        batch = tickers[start:start + YF_BATCH_SIZE]
        try:
            raw = yf.download(
                batch, period="3d", interval=TIMEFRAME, progress=False,
                group_by="ticker", threads=True, auto_adjust=False,
            )
        except Exception as exc:
            logging.warning("Intraday download failed for batch %s: %s", batch[0], exc)
            continue
        for ticker in batch:
            frame = normalize_ohlcv(extract_ticker_frame(raw, ticker))
            frame = keep_completed_intraday_bars(frame)
            if not frame.empty:
                frames[ticker] = frame
    return frames

def make_s1_signal_message(side, name, spot, pivot, ema9, ema21, volume_ratio, rsi, strike_atm, strike_itm, stage):
    option = "CE" if side == "CALL" else "PE"
    return (
        f"{'🟢' if side == 'CALL' else '🔴'} *[STRATEGY 1: BREAKOUT] {side} {stage}*\n"
        f"• `{name}` | Spot: ₹{spot:,.2f}\n"
        f"• Strike: Rec ITM `{strike_itm} {option}` (ATM: `{strike_atm} {option}`)\n"
        f"• EMA 9/21: `{ema9:.2f} / {ema21:.2f}` | RSI: `{rsi:.1f}`\n"
        f"• Volume: `{volume_ratio:.2f}x` (20-bar avg)\n"
        f"• Daily {'R1' if side == 'CALL' else 'S1'}: ₹{pivot:,.2f}"
    )

def make_s2_signal_message(side, name, spot, vwap_val, ema9, ema21, atr_val, strike_atm, strike_itm, stage):
    option = "CE" if side == "CALL" else "PE"
    cross_desc = "EMA 9 Crossed Above 21" if side == "CALL" else "EMA 9 Crossed Below 21"
    vwap_desc = "Above VWAP" if side == "CALL" else "Below VWAP"
    return (
        f"{'🟢' if side == 'CALL' else '🔴'} *[STRATEGY 2: EMA+VWAP] {side} {stage}*\n"
        f"• `{name}` | Spot: ₹{spot:,.2f}\n"
        f"• Strike: Rec ITM `{strike_itm} {option}` (ATM: `{strike_atm} {option}`)\n"
        f"• Signal: *{cross_desc}* & *{vwap_desc}*\n"
        f"• EMA 9/21: `{ema9:.2f} / {ema21:.2f}` | VWAP: ₹{vwap_val:,.2f}\n"
        f"• ATR(14): `{atr_val:.2f}` (Filter: > {S2_MIN_ATR})"
    )

def run_scan_cycle(state, is_pulse_cycle, current_time_str):
    symbols = list(WATCHLIST)
    context_map = get_daily_context(symbols)
    intraday_map = download_intraday(symbols)
    rankings = []
    processed = 0

    for ticker in symbols:
        try:
            frame = intraday_map.get(ticker, pd.DataFrame())
            if len(frame) < 60 or ticker not in context_map:
                continue
            frame = frame.copy()
            ctx = context_map[ticker]
            pivot_r1, pivot_s1 = ctx["pivot_r1"], ctx["pivot_s1"]

            close = frame["Close"]
            ema9 = close.ewm(span=9, adjust=False).mean()
            ema21 = close.ewm(span=21, adjust=False).mean()
            rsi = calculate_rsi(close)
            bb_upper, bb_lower = calculate_bollinger_bands(close)
            atr = calculate_atr(frame)
            vwap = calculate_vwap(frame)
            st1, st1_dir = calculate_supertrend(frame, 10, 3.0)
            st2, st2_dir = calculate_supertrend(frame, 7, 2.0)

            last = frame.iloc[-1]
            spot = float(last["Close"])
            open_price, high, low = float(last["Open"]), float(last["High"]), float(last["Low"])

            current_atr = float(atr.iloc[-1])
            current_rsi = float(rsi.iloc[-1])
            current_vwap = float(vwap.iloc[-1])
            current_ema9, current_ema21 = float(ema9.iloc[-1]), float(ema21.iloc[-1])
            prev_ema9, prev_ema21 = float(ema9.iloc[-2]), float(ema21.iloc[-2])
            current_st1 = float(st1.iloc[-1])
            current_bb_upper, current_bb_lower = float(bb_upper.iloc[-1]), float(bb_lower.iloc[-1])

            if not all(math.isfinite(x) for x in (
                current_atr, current_rsi, current_vwap, current_ema9,
                current_ema21, prev_ema9, prev_ema21, current_st1,
                current_bb_upper, current_bb_lower,
            )):
                continue

            volume_avg = float(frame["Volume"].iloc[-21:-1].mean())
            volume_now = float(last["Volume"])
            volume_ratio = volume_now / volume_avg if volume_avg > 0 else 0.0
            volume_confirm = volume_ratio >= VOLUME_MULTIPLIER

            name = ticker.replace(".NS", "").replace("^NSEI", "NIFTY 50").replace("^NSEBANK", "BANK NIFTY").replace("^BSESN", "SENSEX")
            prev_close = float(ctx["prev_close"])
            pct_change = ((spot - prev_close) / prev_close * 100.0) if prev_close else 0.0
            trail_buffer = max(round(current_atr * ATR_MULTIPLIER, 2), 0.05)

            green = spot > open_price
            red = spot < open_price
            st1_bull = float(st1_dir.iloc[-1]) == 1
            st1_bear = float(st1_dir.iloc[-1]) == -1
            st2_flip_bear = float(st2_dir.iloc[-1]) == -1 and float(st2_dir.iloc[-2]) == 1
            st2_flip_bull = float(st2_dir.iloc[-1]) == 1 and float(st2_dir.iloc[-2]) == -1

            # STRATEGY 1: CLASSICAL BREAKOUT
            s1_call = (
                green and st1_bull and spot > current_st1 and current_rsi > 55
                and spot > current_bb_upper and spot > pivot_r1
                and (current_ema9 > current_ema21) and volume_confirm
            )
            s1_put = (
                red and st1_bear and spot < current_st1 and current_rsi < 45
                and spot < current_bb_lower and spot < pivot_s1
                and (current_ema9 < current_ema21) and volume_confirm
            )

            # STRATEGY 2: EMA 9/21 CROSSOVER + VWAP + ATR > 20
            ema_cross_bull = (prev_ema9 <= prev_ema21) and (current_ema9 > current_ema21)
            s2_call = (
                ema_cross_bull
                and (spot > current_ema9)
                and (spot > current_ema21)
                and (spot > current_vwap)
                and (current_atr > S2_MIN_ATR)
            )

            ema_cross_bear = (prev_ema9 >= prev_ema21) and (current_ema9 < current_ema21)
            s2_put = (
                ema_cross_bear
                and (spot < current_ema9)
                and (spot < current_ema21)
                and (spot < current_vwap)
                and (current_atr > S2_MIN_ATR)
            )

            atm_ce, itm_ce = get_options_strikes(spot, WATCHLIST[ticker], "CALL")
            atm_pe, itm_pe = get_options_strikes(spot, WATCHLIST[ticker], "PUT")

            verdicts = []
            if s1_call: verdicts.append(f"S1: 🟢 CALL ({itm_ce} CE)")
            if s2_call: verdicts.append(f"S2: 🟢 CALL ({itm_ce} CE)")
            if s1_put: verdicts.append(f"S1: 🔴 PUT ({itm_pe} PE)")
            if s2_put: verdicts.append(f"S2: 🔴 PUT ({itm_pe} PE)")
            if not verdicts:
                if spot > pivot_r1 and spot > current_vwap:
                    verdicts.append("WAIT — Bullish bias; setup pending")
                elif spot < pivot_s1 and spot < current_vwap:
                    verdicts.append("WAIT — Bearish bias; setup pending")
                else:
                    verdicts.append("WAIT — In neutral range")

            rankings.append({"name": name, "spot": spot, "pct": pct_change, "verdict": " | ".join(verdicts)})
            processed += 1

            # PIPELINE: STRATEGY 1 TRADES
            pos1 = state["s1_positions"].setdefault(ticker, get_default_item_state())
            if pos1.get("in_trade"):
                side = pos1.get("trade_type")
                buf = float(pos1.get("trail_buffer") or trail_buffer)
                if side == "CALL":
                    pos1["extreme_price"] = max(float(pos1["extreme_price"]), high)
                    pos1["trailing_sl"] = max(float(pos1["trailing_sl"]), round(pos1["extreme_price"] - buf, 2))
                    exit_reason = (
                        "Trailing spot stop" if spot <= float(pos1["trailing_sl"])
                        else "Daily R1 lost" if spot < pivot_r1
                        else "ST2 flip" if st2_flip_bear else None
                    )
                    pnl = spot - float(pos1["entry_price"])
                else:
                    pos1["extreme_price"] = min(float(pos1["extreme_price"]), low)
                    candidate = round(pos1["extreme_price"] + buf, 2)
                    old_sl = float(pos1.get("trailing_sl") or candidate)
                    pos1["trailing_sl"] = min(old_sl, candidate)
                    exit_reason = (
                        "Trailing spot stop" if spot >= float(pos1["trailing_sl"])
                        else "Daily S1 reclaimed" if spot > pivot_s1
                        else "ST2 flip" if st2_flip_bull else None
                    )
                    pnl = float(pos1["entry_price"]) - spot

                if exit_reason:
                    state["closed_trades"].append({
                        "strategy": "S1", "ticker": name, "symbol": ticker, "type": side,
                        "strike": pos1.get("itm_strike"), "entry": pos1["entry_price"],
                        "exit": spot, "pnl": round(pnl, 2), "reason": exit_reason,
                        "closed_at": dt.datetime.now(IST).isoformat(),
                    })
                    option = "CE" if side == "CALL" else "PE"
                    send_telegram(
                        f"{'🔴' if side == 'CALL' else '🟢'} *[S1: BREAKOUT] {side} EXIT*\n"
                        f"`{name}` | Spot: ₹{spot:,.2f} ({pnl:+.2f} pts)\n"
                        f"Reason: {exit_reason} | Close `{pos1.get('itm_strike')} {option}`"
                    )
                    state["s1_positions"][ticker] = get_default_item_state()
            else:
                pending = pos1.get("pending_stage")
                if pending == "PENDING_CALL":
                    if s1_call and spot > float(st1.iloc[-1]) and spot > pivot_r1:
                        pos1.update({
                            "in_trade": True, "pending_stage": None, "trade_type": "CALL",
                            "entry_price": spot, "entry_time": dt.datetime.now(IST).isoformat(),
                            "extreme_price": high, "trailing_sl": round(spot - trail_buffer, 2),
                            "trail_buffer": trail_buffer, "atm_strike": atm_ce, "itm_strike": itm_ce,
                            "strategy": "S1"
                        })
                        send_telegram(make_s1_signal_message("CALL", name, spot, pivot_r1, current_ema9, current_ema21, volume_ratio, current_rsi, atm_ce, itm_ce, "ENTRY CONFIRMED"))
                    else:
                        pos1["pending_stage"] = None
                elif pending == "PENDING_PUT":
                    if s1_put and spot < float(st1.iloc[-1]) and spot < pivot_s1:
                        pos1.update({
                            "in_trade": True, "pending_stage": None, "trade_type": "PUT",
                            "entry_price": spot, "entry_time": dt.datetime.now(IST).isoformat(),
                            "extreme_price": low, "trailing_sl": round(spot + trail_buffer, 2),
                            "trail_buffer": trail_buffer, "atm_strike": atm_pe, "itm_strike": itm_pe,
                            "strategy": "S1"
                        })
                        send_telegram(make_s1_signal_message("PUT", name, spot, pivot_s1, current_ema9, current_ema21, volume_ratio, current_rsi, atm_pe, itm_pe, "ENTRY CONFIRMED"))
                    else:
                        pos1["pending_stage"] = None
                elif s1_call:
                    pos1["pending_stage"] = "PENDING_CALL"
                    send_telegram(make_s1_signal_message("CALL", name, spot, pivot_r1, current_ema9, current_ema21, volume_ratio, current_rsi, atm_ce, itm_ce, "SETUP — WAIT FOR NEXT BAR"))
                elif s1_put:
                    pos1["pending_stage"] = "PENDING_PUT"
                    send_telegram(make_s1_signal_message("PUT", name, spot, pivot_s1, current_ema9, current_ema21, volume_ratio, current_rsi, atm_pe, itm_pe, "SETUP — WAIT FOR NEXT BAR"))

            state["s1_positions"][ticker] = pos1

            # PIPELINE: STRATEGY 2 TRADES (EMA 9/21 CROSSOVER + VWAP)
            pos2 = state["s2_positions"].setdefault(ticker, get_default_item_state())
            if pos2.get("in_trade"):
                side = pos2.get("trade_type")
                buf = float(pos2.get("trail_buffer") or trail_buffer)
                if side == "CALL":
                    pos2["extreme_price"] = max(float(pos2["extreme_price"]), high)
                    pos2["trailing_sl"] = max(float(pos2["trailing_sl"]), round(pos2["extreme_price"] - buf, 2))
                    vwap_lost = spot < current_vwap
                    ema_cross_back = current_ema9 < current_ema21
                    exit_reason = (
                        "Trailing spot stop" if spot <= float(pos2["trailing_sl"])
                        else "VWAP breakdown" if vwap_lost
                        else "EMA 9 crossed below 21" if ema_cross_back else None
                    )
                    pnl = spot - float(pos2["entry_price"])
                else:
                    pos2["extreme_price"] = min(float(pos2["extreme_price"]), low)
                    candidate = round(pos2["extreme_price"] + buf, 2)
                    old_sl = float(pos2.get("trailing_sl") or candidate)
                    pos2["trailing_sl"] = min(old_sl, candidate)
                    vwap_reclaimed = spot > current_vwap
                    ema_cross_back = current_ema9 > current_ema21
                    exit_reason = (
                        "Trailing spot stop" if spot >= float(pos2["trailing_sl"])
                        else "VWAP breakout" if vwap_reclaimed
                        else "EMA 9 crossed above 21" if ema_cross_back else None
                    )
                    pnl = float(pos2["entry_price"]) - spot

                if exit_reason:
                    state["closed_trades"].append({
                        "strategy": "S2", "ticker": name, "symbol": ticker, "type": side,
                        "strike": pos2.get("itm_strike"), "entry": pos2["entry_price"],
                        "exit": spot, "pnl": round(pnl, 2), "reason": exit_reason,
                        "closed_at": dt.datetime.now(IST).isoformat(),
                    })
                    option = "CE" if side == "CALL" else "PE"
                    send_telegram(
                        f"{'🔴' if side == 'CALL' else '🟢'} *[S2: EMA+VWAP] {side} EXIT*\n"
                        f"`{name}` | Spot: ₹{spot:,.2f} ({pnl:+.2f} pts)\n"
                        f"Reason: {exit_reason} | Close `{pos2.get('itm_strike')} {option}`"
                    )
                    state["s2_positions"][ticker] = get_default_item_state()
            else:
                if s2_call:
                    pos2.update({
                        "in_trade": True, "pending_stage": None, "trade_type": "CALL",
                        "entry_price": spot, "entry_time": dt.datetime.now(IST).isoformat(),
                        "extreme_price": high, "trailing_sl": round(spot - trail_buffer, 2),
                        "trail_buffer": trail_buffer, "atm_strike": atm_ce, "itm_strike": itm_ce,
                        "strategy": "S2"
                    })
                    send_telegram(make_s2_signal_message("CALL", name, spot, current_vwap, current_ema9, current_ema21, current_atr, atm_ce, itm_ce, "ENTRY SIGNAL"))
                elif s2_put:
                    pos2.update({
                        "in_trade": True, "pending_stage": None, "trade_type": "PUT",
                        "entry_price": spot, "entry_time": dt.datetime.now(IST).isoformat(),
                        "extreme_price": low, "trailing_sl": round(spot + trail_buffer, 2),
                        "trail_buffer": trail_buffer, "atm_strike": atm_pe, "itm_strike": itm_pe,
                        "strategy": "S2"
                    })
                    send_telegram(make_s2_signal_message("PUT", name, spot, current_vwap, current_ema9, current_ema21, current_atr, atm_pe, itm_pe, "ENTRY SIGNAL"))

            state["s2_positions"][ticker] = pos2

        except Exception:
            logging.exception("Symbol processing failed for %s", ticker)

    # 30-Minute Market Pulse
    if is_pulse_cycle and rankings:
        bullish = sorted(rankings, key=lambda item: item["pct"], reverse=True)[:5]
        bearish = sorted(rankings, key=lambda item: item["pct"])[:5]
        lines = [
            f"⏱️ *MARKET PULSE ({current_time_str})*",
            f"Symbols analyzed: {processed}", "",
            "🐂 *TOP 5 BULLISH*",
        ]
        lines += [f"{i}. *{x['name']}* (`{x['pct']:+.2f}%`) | ₹{x['spot']:,.2f}\n   • {x['verdict']}" for i, x in enumerate(bullish, 1)]
        lines += ["", "🐻 *TOP 5 BEARISH*"]
        lines += [f"{i}. *{x['name']}* (`{x['pct']:+.2f}%`) | ₹{x['spot']:,.2f}\n   • {x['verdict']}" for i, x in enumerate(bearish, 1)]
        send_telegram("\n".join(lines))

    save_state(state)
    logging.info("Scan cycle completed. Symbols with usable data: %s/%s", processed, len(symbols))

def generate_daily_report():
    ist = pytz.timezone("Asia/Kolkata")
    today = dt.datetime.now(ist).date()
    today_label = today.strftime("%d-%b-%Y")
    
    print("Generating 5:00 PM summary report...")
    trades = []
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            for trade in data.get("closed_trades", []):
                try:
                    stamp = dt.datetime.fromisoformat(trade["closed_at"])
                    if stamp.tzinfo is None:
                        stamp = ist.localize(stamp)
                    if stamp.astimezone(ist).date() == today:
                        trades.append(trade)
                except Exception:
                    trades.append(trade)
        except Exception as exc:
            logging.error("Failed to read state file: %s", exc)

    if not trades:
        send_telegram(
            f"📊 *DAILY ALERT REPORT | {today_label}*\n"
            f"════════════════════════════\n"
            f"• Scanner status: Active & Connected ✅\n"
            f"• Trades closed today: 0\n"
            f"• Ready for the next market session."
        )
        return

    s1_trades = [t for t in trades if t.get("strategy") == "S1"]
    s2_trades = [t for t in trades if t.get("strategy") == "S2"]

    def calc_stats(sub_trades):
        if not sub_trades:
            return 0, 0, 0, 0.0, 0.0
        wins = sum(float(t.get("pnl", 0)) > 0 for t in sub_trades)
        losses = sum(float(t.get("pnl", 0)) < 0 for t in sub_trades)
        total = sum(float(t.get("pnl", 0)) for t in sub_trades)
        win_rate = (wins / len(sub_trades) * 100) if sub_trades else 0
        return len(sub_trades), wins, losses, win_rate, total

    s1_cnt, s1_w, s1_l, s1_wr, s1_pnl = calc_stats(s1_trades)
    s2_cnt, s2_w, s2_l, s2_wr, s2_pnl = calc_stats(s2_trades)
    total_pnl = s1_pnl + s2_pnl

    lines = [
        f"📊 *DAILY INTRADAY REPORT | {today_label}*",
        "════════════════════════════",
        f"📘 *[STRATEGY 1: BREAKOUT]*",
        f"• Trades: `{s1_cnt}` (✅ {s1_w} | ❌ {s1_l})",
        f"• Win Rate: `{s1_wr:.1f}%` | Net: *{s1_pnl:+.2f} pts*",
        "",
        f"📙 *[STRATEGY 2: EMA 9/21 + VWAP]*",
        f"• Trades: `{s2_cnt}` (✅ {s2_w} | ❌ {s2_l})",
        f"• Win Rate: `{s2_wr:.1f}%` | Net: *{s2_pnl:+.2f} pts*",
        "════════════════════════════",
        f"🎯 *COMBINED RESULT:* *{total_pnl:+.2f} pts*",
        "",
        "📋 *Recent Exits:*"
    ]
    for trade in trades[-8:]:
        st = trade.get("strategy", "S1")
        lines.append(
            f"• `[{st}] {trade.get('ticker')}` {trade.get('type')}: "
            f"*{float(trade.get('pnl', 0)):+.2f} pts* ({trade.get('reason', 'Exit')})"
        )
    send_telegram("\n".join(lines))
    print("Report sent successfully.")

def run_scanner():
    symbols = list(WATCHLIST)
    state = load_state(symbols)
    logging.info("Dual Strategy scanner online (S1: Breakout, S2: EMA 9/21 cross + VWAP).")
    last_pulse_slot = None
    while True:
        now = dt.datetime.now(IST)
        minute_of_day = now.hour * 60 + now.minute
        if now.weekday() >= 5:
            logging.info("Weekend detected; scanner stopping.")
            break
        if minute_of_day > SCAN_END_MINUTES:
            logging.info("15:15 IST cutoff reached; scanner stopping.")
            break
        if minute_of_day >= SCAN_START_MINUTES:
            pulse_slot = (now.hour, now.minute)
            is_pulse = now.minute in PULSE_MINUTES and pulse_slot != last_pulse_slot
            if is_pulse:
                last_pulse_slot = pulse_slot
            try:
                run_scan_cycle(state, is_pulse, now.strftime("%I:%M %p IST"))
            except Exception:
                logging.exception("Scan cycle failed.")
                save_state(state)
        else:
            logging.info("Waiting for 09:30 IST; current time %s", now.strftime("%H:%M"))
        time.sleep(SCAN_INTERVAL_SECONDS)
    save_state(state)

def main():
    parser = argparse.ArgumentParser(description="Dual Strategy Telegram alert scanner")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--scan", action="store_true", help="Run the intraday alert scanner")
    group.add_argument("--report", action="store_true", help="Send today's alert report")
    args = parser.parse_args()
    if args.report:
        generate_daily_report()
    else:
        run_scanner()

if __name__ == "__main__":
    main()
