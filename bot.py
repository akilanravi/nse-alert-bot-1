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
STATE_FILE = Path(os.getenv("STATE_FILE", "trade_state_master.json"))
IST = pytz.timezone("Asia/Kolkata")
SCAN_START_MINUTES = 9 * 60 + 30
SCAN_END_MINUTES = 15 * 60 + 15
PULSE_MINUTES = (15, 45)
YF_BATCH_SIZE = 35

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)

def send_telegram(message):
    for token, chat_id in TELEGRAM_RECIPIENTS:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            res = requests.post(
                url,
                json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True},
                timeout=10,
            )
            if not res.ok:
                requests.post(
                    url,
                    json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
                    timeout=10,
                )
        except requests.RequestException as exc:
            logging.error("Telegram network failure for chat %s: %s", chat_id, exc)

def get_default_item_state():
    return {
        "in_trade": False, "trade_type": "", "entry_price": 0.0,
        "entry_time": None, "atm_strike": 0, "itm_strike": 0,
        "strategy": "CONFLUENCE"
    }

def load_state(symbols):
    state = {
        "positions": {s: get_default_item_state() for s in symbols},
        "closed_trades": []
    }
    if not STATE_FILE.exists():
        return state
    try:
        saved = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        state["closed_trades"] = saved.get("closed_trades", [])
        saved_pos = saved.get("positions", saved.get("s1_positions", {}))
        for symbol in symbols:
            if symbol in saved_pos and isinstance(saved_pos[symbol], dict):
                m = get_default_item_state()
                m.update(saved_pos[symbol])
                state["positions"][symbol] = m
    except Exception as exc:
        logging.exception("Could not parse state file: %s", exc)
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

def calculate_supertrend(frame, period=10, multiplier=2.0):
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

def calculate_adx(frame, period=14):
    """
    Standard Wilder's ADX calculation with RMA smoothing matching TradingView.
    Requires at least 2*period bars for valid readings.
    """
    if len(frame) < period * 2:
        return pd.Series(0.0, index=frame.index)

    high, low, close = frame["High"], frame["Low"], frame["Close"]
    prev_close = close.shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)

    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    # Wilder's Smoothing (alpha = 1/period)
    tr_smooth = pd.Series(tr).ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * (pd.Series(plus_dm, index=frame.index).ewm(alpha=1/period, adjust=False).mean() / tr_smooth.replace(0, np.nan))
    minus_di = 100 * (pd.Series(minus_dm, index=frame.index).ewm(alpha=1/period, adjust=False).mean() / tr_smooth.replace(0, np.nan))

    di_sum = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * ((plus_di - minus_di).abs() / di_sum)
    dx = dx.fillna(0.0)

    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    return adx

def get_daily_context(tickers):
    logging.info("Caching daily pivots (R1/S1)...")
    context = {}
    for start in range(0, len(tickers), YF_BATCH_SIZE):
        batch = tickers[start:start + YF_BATCH_SIZE]
        try:
            raw = yf.download(
                batch, period="1mo", interval="1d", progress=False,
                group_by="ticker", threads=True, auto_adjust=False,
            )
        except Exception as exc:
            logging.warning("Daily download failed for batch: %s", exc)
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
    """
    Downloads 5 days of 5m bars to give Wilder's ADX and Supertrend 
    sufficient historical depth for accurate readings.
    """
    frames = {}
    for start in range(0, len(tickers), YF_BATCH_SIZE):
        batch = tickers[start:start + YF_BATCH_SIZE]
        try:
            raw = yf.download(
                batch, period="5d", interval=TIMEFRAME, progress=False,
                group_by="ticker", threads=True, auto_adjust=False,
            )
        except Exception as exc:
            logging.warning("Intraday download failed: %s", exc)
            continue
        for ticker in batch:
            frame = normalize_ohlcv(extract_ticker_frame(raw, ticker))
            if not frame.empty:
                frames[ticker] = frame
    return frames

def make_signal_message(side, name, spot, pivot, ema9, ema21, rsi, adx_val, strike_atm, strike_itm, stage):
    option = "CE" if side == "CALL" else "PE"
    return (
        f"{'🟢' if side == 'CALL' else '🔴'} *[STRATEGY: CONFLUENCE] {side} {stage}*\n"
        f"• `{name}` | Spot: ₹{spot:,.2f}\n"
        f"• Strike: Rec ITM `{strike_itm} {option}` (ATM: `{strike_atm} {option}`)\n"
        f"• EMA 9/21: `{ema9:.2f} / {ema21:.2f}` | RSI: `{rsi:.1f}` | ADX: `{adx_val:.1f}`\n"
        f"• Daily {'R1' if side == 'CALL' else 'S1'}: ₹{pivot:,.2f}"
    )

def run_scan_cycle(state, context_map, is_pulse_cycle, current_time_str):
    symbols = list(WATCHLIST)
    intraday_map = download_intraday(symbols)
    rankings = []
    processed = 0

    for ticker in symbols:
        try:
            frame = intraday_map.get(ticker, pd.DataFrame())
            # Minimum 45 bars needed for ADX and EMA warmup
            if len(frame) < 45 or ticker not in context_map:
                continue
            frame = frame.copy()
            ctx = context_map[ticker]
            pivot_r1, pivot_s1 = ctx["pivot_r1"], ctx["pivot_s1"]

            close = frame["Close"]
            ema9 = close.ewm(span=9, adjust=False).mean()
            ema21 = close.ewm(span=21, adjust=False).mean()
            rsi = calculate_rsi(close)
            bb_upper, bb_lower = calculate_bollinger_bands(close, period=20, mult=2.0)
            
            # Entry Supertrend (10, 2)
            st_entry, st_entry_dir = calculate_supertrend(frame, period=10, multiplier=2.0)
            # Exit Supertrend (7, 2)
            st_exit, st_exit_dir = calculate_supertrend(frame, period=7, multiplier=2.0)
            
            # ADX Calculation
            adx = calculate_adx(frame, period=14)

            last = frame.iloc[-1]
            spot = float(last["Close"])

            current_rsi = float(rsi.iloc[-1])
            current_adx = float(adx.iloc[-1])
            current_ema9, current_ema21 = float(ema9.iloc[-1]), float(ema21.iloc[-1])
            prev_ema9, prev_ema21 = float(ema9.iloc[-2]), float(ema21.iloc[-2])
            current_st_entry = float(st_entry.iloc[-1])
            current_bb_upper, current_bb_lower = float(bb_upper.iloc[-1]), float(bb_lower.iloc[-1])

            if not all(math.isfinite(x) for x in (
                current_rsi, current_adx, current_ema9,
                current_ema21, prev_ema9, prev_ema21, current_st_entry,
                current_bb_upper, current_bb_lower
            )):
                continue

            name = ticker.replace(".NS", "").replace("^NSEI", "NIFTY 50").replace("^NSEBANK", "BANK NIFTY").replace("^BSESN", "SENSEX")
            prev_close = float(ctx["prev_close"])
            pct_change = ((spot - prev_close) / prev_close * 100.0) if prev_close else 0.0

            st_entry_bull = float(st_entry_dir.iloc[-1]) == 1
            st_entry_bear = float(st_entry_dir.iloc[-1]) == -1

            st_exit_bull = float(st_exit_dir.iloc[-1]) == 1
            st_exit_bear = float(st_exit_dir.iloc[-1]) == -1

            ema_cross_above = (prev_ema9 <= prev_ema21) and (current_ema9 > current_ema21)
            ema_cross_below = (prev_ema9 >= prev_ema21) and (current_ema9 < current_ema21)

            # STRICT ADX CRITERIA: Explicitly require current_adx > 20.0
            adx_valid = bool(current_adx > 20.0 and not np.isnan(current_adx))

            signal_call = (
                st_entry_bull
                and (spot > current_st_entry)
                and (current_rsi > 60.0)
                and (spot > current_bb_upper)
                and (spot > current_ema9)
                and (spot > current_ema21)
                and ema_cross_above
                and (spot > pivot_r1)
                and adx_valid
            )

            signal_put = (
                st_entry_bear
                and (spot < current_st_entry)
                and (current_rsi < 40.0)
                and (spot < current_bb_lower)
                and (spot < current_ema9)
                and (spot < current_ema21)
                and ema_cross_below
                and (spot < pivot_s1)
                and adx_valid
            )

            atm_ce, itm_ce = get_options_strikes(spot, WATCHLIST[ticker], "CALL")
            atm_pe, itm_pe = get_options_strikes(spot, WATCHLIST[ticker], "PUT")

            verdicts = []
            if signal_call: verdicts.append(f"🟢 CALL ({itm_ce} CE)")
            if signal_put: verdicts.append(f"🔴 PUT ({itm_pe} PE)")
            if not verdicts:
                verdicts.append("WAIT — In neutral range" if pivot_s1 <= spot <= pivot_r1 else "WAIT — Setup pending")

            rankings.append({"name": name, "spot": spot, "pct": pct_change, "verdict": " | ".join(verdicts)})
            processed += 1

            # POSITION TRACKING & EXIT LOGIC
            pos = state["positions"].setdefault(ticker, get_default_item_state())
            if pos.get("in_trade"):
                side = pos.get("trade_type")
                # Strictly exit on Supertrend (7, 2) reversal only
                exit_reason = None
                if side == "CALL" and st_exit_bear:
                    exit_reason = "Supertrend (7,2) flipped Bearish"
                    pnl = spot - float(pos["entry_price"])
                elif side == "PUT" and st_exit_bull:
                    exit_reason = "Supertrend (7,2) flipped Bullish"
                    pnl = float(pos["entry_price"]) - spot

                if exit_reason:
                    state["closed_trades"].append({
                        "strategy": "CONFLUENCE", "ticker": name, "symbol": ticker, "type": side,
                        "strike": pos.get("itm_strike"), "entry": pos["entry_price"],
                        "exit": spot, "pnl": round(pnl, 2), "reason": exit_reason,
                        "closed_at": dt.datetime.now(IST).isoformat(),
                    })
                    option = "CE" if side == "CALL" else "PE"
                    send_telegram(
                        f"{'🔴' if side == 'CALL' else '🟢'} *[EXIT: ST (7,2)] {side} CLOSED*\n"
                        f"• `{name}` | Spot: ₹{spot:,.2f} ({pnl:+.2f} pts)\n"
                        f"• Trigger: *{exit_reason}*\n"
                        f"• Close Strike: `{pos.get('itm_strike')} {option}`"
                    )
                    state["positions"][ticker] = get_default_item_state()
            else:
                if signal_call:
                    pos.update({
                        "in_trade": True, "trade_type": "CALL",
                        "entry_price": spot, "entry_time": dt.datetime.now(IST).isoformat(),
                        "atm_strike": atm_ce, "itm_strike": itm_ce,
                        "strategy": "CONFLUENCE"
                    })
                    send_telegram(make_signal_message("CALL", name, spot, pivot_r1, current_ema9, current_ema21, current_rsi, current_adx, atm_ce, itm_ce, "ENTRY CONFIRMED"))
                elif signal_put:
                    pos.update({
                        "in_trade": True, "trade_type": "PUT",
                        "entry_price": spot, "entry_time": dt.datetime.now(IST).isoformat(),
                        "atm_strike": atm_pe, "itm_strike": itm_pe,
                        "strategy": "CONFLUENCE"
                    })
                    send_telegram(make_signal_message("PUT", name, spot, pivot_s1, current_ema9, current_ema21, current_rsi, current_adx, atm_pe, itm_pe, "ENTRY CONFIRMED"))

            state["positions"][ticker] = pos

        except Exception:
            logging.exception("Symbol error: %s", ticker)

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

def run_scanner():
    symbols = list(WATCHLIST)
    state = load_state(symbols)
    context_map = get_daily_context(symbols)
    logging.info("Confluence Strategy online (Yahoo Engine). Exit: Supertrend (7,2) reversal only.")
    last_pulse_slot = None

    while True:
        now = dt.datetime.now(IST)
        minute_of_day = now.hour * 60 + now.minute
        if now.weekday() >= 5:
            logging.info("Weekend detected; stopping.")
            break
        if minute_of_day > SCAN_END_MINUTES:
            logging.info("15:15 IST reached; stopping.")
            break

        if minute_of_day >= SCAN_START_MINUTES:
            pulse_slot = (now.hour, now.minute)
            is_pulse = now.minute in PULSE_MINUTES and pulse_slot != last_pulse_slot
            if is_pulse:
                last_pulse_slot = pulse_slot
            try:
                run_scan_cycle(state, context_map, is_pulse, now.strftime("%I:%M %p IST"))
            except Exception:
                logging.exception("Cycle failed.")
                save_state(state)
        else:
            logging.info("Waiting for 09:30 IST; current time %s", now.strftime("%H:%M"))

        # Wait until 10s past next 5m candle boundary
        curr_sec = dt.datetime.now(IST).minute * 60 + dt.datetime.now(IST).second
        next_boundary = ((curr_sec // 300) + 1) * 300 + 10
        sleep_duration = max(next_boundary - curr_sec, 15)
        time.sleep(sleep_duration)

    save_state(state)

def generate_daily_report():
    ist = pytz.timezone("Asia/Kolkata")
    today = dt.datetime.now(ist).date()
    today_label = today.strftime("%d-%b-%Y")
    
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
            logging.error("Failed to read state: %s", exc)

    if not trades:
        send_telegram(
            f"📊 *DAILY ALERT REPORT | {today_label}*\n"
            f"════════════════════════════\n"
            f"• Scanner status: Active & Connected ✅\n"
            f"• Trades closed today: 0\n"
            f"• Ready for the next market session."
        )
        return

    wins = sum(float(t.get("pnl", 0)) > 0 for t in trades)
    losses = sum(float(t.get("pnl", 0)) < 0 for t in trades)
    total_pnl = sum(float(t.get("pnl", 0)) for t in trades)
    win_rate = (wins / len(trades) * 100) if trades else 0

    lines = [
        f"📊 *DAILY INTRADAY REPORT | {today_label}*",
        "════════════════════════════",
        f"📘 *[STRATEGY: CONFLUENCE]*",
        f"• Trades: `{len(trades)}` (✅ {wins} | ❌ {losses})",
        f"• Win Rate: `{win_rate:.1f}%`",
        f"• Net P&L: *{total_pnl:+.2f} pts*",
        "════════════════════════════",
        "📋 *Recent Exits:*"
    ]
    for trade in trades[-8:]:
        lines.append(
            f"• `{trade.get('ticker')}` {trade.get('type')}: "
            f"*{float(trade.get('pnl', 0)):+.2f} pts* ({trade.get('reason', 'Exit')})"
        )
    send_telegram("\n".join(lines))

def main():
    parser = argparse.ArgumentParser(description="Confluence Telegram Alert Scanner")
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
