import argparse
import datetime
import json
import math
import os
import time
import numpy as np
import pandas as pd
import pytz
import requests
import yfinance as yf

# Prevent multi-thread SQLite file locking
try:
    yf.set_tz_cache_location("/tmp/yf_tz_cache")
except Exception:
    pass

# =====================================================================
# 1. DUAL TELEGRAM RECIPIENTS
# =====================================================================
TELEGRAM_RECIPIENTS = [
    {
        "token": "8721771664:AAFcyCX2TP2KsUrIQoh6utZvHjbLQt8vD-k",
        "chat_id": "846124589"
    },
    {
        "token": "8764996383:AAE_vevTjJ76zfK3g3rYGgsZB3_EtkbvUms",
        "chat_id": "8865083462"
    }
]

# =====================================================================
# 2. WATCHLIST SPLIT INTO 5 PARALLEL GROUPS (~20 TICKERS EACH)
# =====================================================================
SECTOR_MAPS = {
    "indices_banking": {
        "^NSEI": 50, "^NSEBANK": 100, "^BSESN": 100, "NIFTY_FIN_SERVICE.NS": 50,
        "HDFCBANK.NS": 20, "ICICIBANK.NS": 10, "SBIN.NS": 10, "KOTAKBANK.NS": 20,
        "AXISBANK.NS": 10, "BAJFINANCE.NS": 50, "BAJAJFINSV.NS": 20, "INDUSINDBK.NS": 20,
        "FEDERALBNK.NS": 2.5, "AUBANK.NS": 10, "BANDHANBNK.NS": 2.5, "IDFCFIRSTB.NS": 1,
        "PNB.NS": 1, "BANKBARODA.NS": 2.5, "CANBK.NS": 1, "CHOLAFIN.NS": 20,
        "SHRIRAMFIN.NS": 25, "MUTHOOTFIN.NS": 20, "M&MFIN.NS": 5, "PFC.NS": 5,
        "RECLTD.NS": 5, "SBICARD.NS": 10, "SBILIFE.NS": 20, "HDFCLIFE.NS": 10
    },
    "it_energy": {
        "TCS.NS": 50, "INFY.NS": 20, "HCLTECH.NS": 20, "WIPRO.NS": 5,
        "TECHM.NS": 20, "PERSISTENT.NS": 50, "COFORGE.NS": 50, "MPHASIS.NS": 25, "NAUKRI.NS": 50,
        "RELIANCE.NS": 20, "ONGC.NS": 2.5, "BPCL.NS": 5, "IOC.NS": 1,
        "GAIL.NS": 2.5, "NTPC.NS": 5, "POWERGRID.NS": 2.5, "TATAPOWER.NS": 5,
        "ADANIENT.NS": 50, "ADANIPORTS.NS": 20, "COALINDIA.NS": 5
    },
    "auto_metals": {
        "MARUTI.NS": 100, "M&M.NS": 20, "BAJAJ-AUTO.NS": 100, "EICHERMOT.NS": 50,
        "HEROMOTOCO.NS": 50, "TVSMOTOR.NS": 25, "BHARATFORG.NS": 20, "ASHOKLEY.NS": 2.5,
        "MRF.NS": 500, "BALKRISIND.NS": 50, "APOLLOTYRE.NS": 5,
        "TATASTEEL.NS": 1, "JSWSTEEL.NS": 10, "HINDALCO.NS": 10, "JINDALSTEL.NS": 10,
        "VEDL.NS": 5, "NMDC.NS": 2.5, "SAIL.NS": 1, "NATIONALUM.NS": 2.5
    },
    "pharma_fmcg": {
        "SUNPHARMA.NS": 20, "DRREDDY.NS": 50, "CIPLA.NS": 20, "DIVISLAB.NS": 50,
        "APOLLOHOSP.NS": 50, "LUPIN.NS": 20, "AUROPHARMA.NS": 20, "BIOCON.NS": 5,
        "TORNTPHARM.NS": 50, "ZYDUSLIFE.NS": 10,
        "HINDUNILVR.NS": 20, "ITC.NS": 5, "NESTLEIND.NS": 20, "BRITANNIA.NS": 50,
        "TATACONSUM.NS": 10, "DABUR.NS": 5, "MARICO.NS": 5, "COLPAL.NS": 25, "GODREJCP.NS": 10
    },
    "telecom_infra_chem": {
        "BHARTIARTL.NS": 10, "TRENT.NS": 50, "TITAN.NS": 50, "ASIANPAINT.NS": 20,
        "BERGEPAINT.NS": 5, "INDIGO.NS": 50, "HAVELLS.NS": 20, "DIXON.NS": 100,
        "POLYCAB.NS": 50, "VOLTAS.NS": 20, "JUBLFOOD.NS": 5,
        "LT.NS": 50, "SIEMENS.NS": 50, "ABB.NS": 50, "BHEL.NS": 2.5,
        "HAL.NS": 50, "BEL.NS": 2.5, "CUMMINSIND.NS": 50, "DLF.NS": 10,
        "GODREJPROP.NS": 50, "OBEROIRLTY.NS": 20,
        "ULTRACEMCO.NS": 100, "GRASIM.NS": 20, "AMBUJACEM.NS": 5, "SHREECEM.NS": 250,
        "PIDILITIND.NS": 20, "SRF.NS": 25, "PIIND.NS": 50
    }
}

TIMEFRAME = "5m"
ATR_MULTIPLIER = 1.5
MAX_HOLD_CANDLES = 6  # 30-min time stop against theta decay

# =====================================================================
# 3. STATE & UTILITIES
# =====================================================================
def get_default_item_state():
    return {
        "in_trade": False,
        "pending_stage": None,
        "trade_type": "",
        "entry_price": 0.0,
        "extreme_price": 0.0,
        "trailing_sl": 0.0,
        "trail_buffer": 0.0,
        "atm_strike": 0,
        "itm_strike": 0,
        "candles_held": 0
    }

def load_state(group_name, symbols):
    filename = f"trade_state_{group_name}.json"
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f:
                saved = json.load(f)
                for t in symbols:
                    if t not in saved:
                        saved[t] = get_default_item_state()
                    else:
                        if "candles_held" not in saved[t]:
                            saved[t]["candles_held"] = 0
                return saved
        except Exception:
            pass
    return {s: get_default_item_state() for s in symbols}

def save_state(group_name, state):
    filename = f"trade_state_{group_name}.json"
    with open(filename, "w") as f:
        json.dump(state, f, indent=2)

def send_telegram(text):
    for recipient in TELEGRAM_RECIPIENTS:
        url = f"https://api.telegram.org/bot{recipient['token']}/sendMessage"
        payload = {"chat_id": recipient["chat_id"], "text": text, "parse_mode": "Markdown"}
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            print(f"Telegram error: {e}")

def get_market_timing_status():
    ist = pytz.timezone("Asia/Kolkata")
    now_ist = datetime.datetime.now(ist)
    if now_ist.weekday() > 4:
        return False, False, False, "Weekend"

    total_mins = now_ist.hour * 60 + now_ist.minute
    window_start = 9 * 60 + 30   # 09:30 AM IST
    window_close = 15 * 60 + 15  # 03:15 PM IST

    is_running = window_start <= total_mins <= window_close
    is_hard_squareoff_time = total_mins >= window_close
    # Allow entries between 09:30 AM and 03:00 PM IST
    is_valid_entry_time = (9 * 60 + 30 <= total_mins <= 15 * 60 + 0)

    return is_running, is_valid_entry_time, is_hard_squareoff_time, now_ist.strftime('%H:%M:%S IST')

def get_options_strikes(price, step, direction="CALL"):
    atm = int(round(price / step) * step) if step >= 1 else round(price / step) * step
    itm = (atm - step) if direction == "CALL" else (atm + step)
    atm_fmt = int(atm) if isinstance(atm, (int, np.integer)) or (isinstance(atm, float) and atm.is_integer()) else f"{atm:.1f}"
    itm_fmt = int(itm) if isinstance(itm, (int, np.integer)) or (isinstance(itm, float) and itm.is_integer()) else f"{itm:.1f}"
    return atm_fmt, itm_fmt

# =====================================================================
# 4. TECHNICAL INDICATORS
# =====================================================================
def calculate_vwap(df):
    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3.0
    vol = df["Volume"].replace(0, 1)
    cum_vol_price = (typical_price * vol).cumsum()
    cum_vol = vol.cumsum()
    return cum_vol_price / cum_vol

def calculate_atr(df, period=14):
    high, low, close = df["High"], df["Low"], df["Close"]
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def calculate_supertrend(df, period=10, multiplier=3.0):
    high, low, close = df["High"], df["Low"], df["Close"]
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, adjust=False).mean()

    hl2 = (high + low) / 2.0
    upper = hl2 + (multiplier * atr)
    lower = hl2 - (multiplier * atr)

    st = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(index=df.index, dtype=int)

    for i in range(1, len(df)):
        curr_c = close.iloc[i]
        prev_st = st.iloc[i-1] if not np.isnan(st.iloc[i-1]) else upper.iloc[i]
        prev_dir = direction.iloc[i-1] if not np.isnan(direction.iloc[i-1]) else 1

        if prev_dir == 1:
            if curr_c < lower.iloc[i]:
                direction.iloc[i] = -1
                st.iloc[i] = upper.iloc[i]
            else:
                direction.iloc[i] = 1
                st.iloc[i] = max(lower.iloc[i], prev_st)
        else:
            if curr_c > upper.iloc[i]:
                direction.iloc[i] = 1
                st.iloc[i] = lower.iloc[i]
            else:
                direction.iloc[i] = -1
                st.iloc[i] = min(upper.iloc[i], prev_st)

    return st, direction

def get_daily_context_bulk(tickers):
    try:
        data = yf.download(tickers, period="1mo", interval="1d", progress=False, group_by="ticker", threads=False)
        context = {}
        for t in tickers:
            try:
                df_d = data[t] if len(tickers) > 1 else data
                df_d = df_d.dropna()
                if len(df_d) < 20:
                    continue
                prev = df_d.iloc[-2]
                h, l, c = float(prev["High"]), float(prev["Low"]), float(prev["Close"])
                p = (h + l + c) / 3.0
                r1 = (2.0 * p) - l
                s1 = (2.0 * p) - h
                m3_upper = (p + r1) / 2.0
                m2_lower = (p + s1) / 2.0
                ema20 = float(df_d["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
                context[t] = (m3_upper, m2_lower, r1, s1, ema20)
            except Exception:
                continue
        return context
    except Exception:
        return {}

# =====================================================================
# 5. SCAN CYCLE
# =====================================================================
def run_scan(group_name, strike_dict):
    is_running, is_valid_entry, is_hard_squareoff, cur_time = get_market_timing_status()
    if not is_running and not is_hard_squareoff:
        print(f"[{group_name}] Outside active window 09:30 AM - 03:15 PM IST ({cur_time}).")
        return

    watchlist = list(strike_dict.keys())
    print(f"[{group_name}] Scanning {len(watchlist)} tickers at {cur_time}...")
    state = load_state(group_name, watchlist)
    context_map = get_daily_context_bulk(watchlist)

    try:
        intraday_data = yf.download(watchlist, period="3d", interval=TIMEFRAME, progress=False, group_by="ticker", threads=False)
    except Exception as e:
        print(f"Download error in {group_name}: {e}")
        return

    for ticker in watchlist:
        try:
            df = intraday_data[ticker] if len(watchlist) > 1 else intraday_data
            df = df.dropna()
            if len(df) < 30 or ticker not in context_map:
                continue

            m3_upper, m2_lower, r1, s1, daily_ema20 = context_map[ticker]
            vwap_series = calculate_vwap(df)
            curr_vwap = float(vwap_series.iloc[-1])
            atr_series = calculate_atr(df, period=14)
            current_atr = float(atr_series.iloc[-1])
            trail_buffer = round(current_atr * ATR_MULTIPLIER, 2)

            st1_val, st1_dir = calculate_supertrend(df, 10, 3.0)
            st2_val, st2_dir = calculate_supertrend(df, 7, 2.0)
            rsi_series = calculate_rsi(df["Close"], 14)

            curr_close = float(df["Close"].iloc[-1])
            curr_high = float(df["High"].iloc[-1])
            curr_low = float(df["Low"].iloc[-1])
            curr_open = float(df["Open"].iloc[-1])

            curr_vol = float(df["Volume"].iloc[-1])
            avg_vol_20 = float(df["Volume"].rolling(window=20).mean().iloc[-1])
            vol_confirmed = curr_vol >= avg_vol_20

            st1_bull = st1_dir.iloc[-1] == 1
            st1_bear = st1_dir.iloc[-1] == -1
            st2_flipped_bear = (st2_dir.iloc[-1] == -1 and st2_dir.iloc[-2] == 1)
            st2_flipped_bull = (st2_dir.iloc[-1] == 1 and st2_dir.iloc[-2] == -1)
            rsi_prev = float(rsi_series.iloc[-2])

            step = strike_dict[ticker]
            name = ticker.replace(".NS", "").replace("^NSEI", "NIFTY 50").replace("^NSEBANK", "BANK NIFTY").replace("^BSESN", "SENSEX")
            pos = state.get(ticker, get_default_item_state())

            # -------------------------------------------------------------
            # A. POSITION TRACKING & EXITS
            # -------------------------------------------------------------
            if pos["in_trade"]:
                pos["candles_held"] += 1
                trade_type = pos["trade_type"]
                buf = pos.get("trail_buffer", trail_buffer)

                time_stop_hit = pos["candles_held"] >= MAX_HOLD_CANDLES

                # Hard Square-off at 3:15 PM IST
                if is_hard_squareoff:
                    pnl = (curr_close - pos["entry_price"]) if trade_type == "CALL" else (pos["entry_price"] - curr_close)
                    opt = f"{pos['itm_strike']} {'CE' if trade_type == 'CALL' else 'PE'}"
                    send_telegram(
                        f"⏰ *3:15 PM HARD SQUARE-OFF ALERT*\n\n"
                        f"• Instrument: `{name}`\n"
                        f"• Spot Exit: ₹{curr_close:,.2f} ({pnl:+.2f} pts)\n"
                        f"• Reason: 3:15 PM End-of-Day Cutoff\n"
                        f"• Action: Close `{opt}` immediately"
                    )
                    pos = get_default_item_state()
                    state[ticker] = pos
                    continue

                if trade_type == "CALL":
                    if curr_high > pos["extreme_price"]:
                        pos["extreme_price"] = curr_high
                        new_tsl = round(curr_high - buf, 2)
                        if new_tsl > pos["trailing_sl"]:
                            pos["trailing_sl"] = new_tsl

                    tsl_hit = curr_close <= pos["trailing_sl"]
                    vwap_exit = curr_close < curr_vwap
                    pivot_exit = curr_close < s1
                    exit_triggered = tsl_hit or st2_flipped_bear or pivot_exit or vwap_exit or time_stop_hit

                    if exit_triggered:
                        reason = "Trailing SL Hit" if tsl_hit else ("VWAP Breakdown" if vwap_exit else ("30m Time Stop" if time_stop_hit else "ST/Pivot Flip"))
                        pnl = curr_close - pos["entry_price"]
                        send_telegram(
                            f"🔴 *CALL EXIT*: `{name}`\n"
                            f"• Exit Spot: ₹{curr_close:,.2f} ({pnl:+.2f} pts)\n"
                            f"• Reason: *{reason}*\n"
                            f"• Action: Square off `{pos['itm_strike']} CE`"
                        )
                        pos = get_default_item_state()

                elif trade_type == "PUT":
                    if curr_low < pos["extreme_price"]:
                        pos["extreme_price"] = curr_low
                        new_tsl = round(curr_low + buf, 2)
                        if new_tsl < pos["trailing_sl"] or pos["trailing_sl"] == 0:
                            pos["trailing_sl"] = new_tsl

                    tsl_hit = curr_close >= pos["trailing_sl"]
                    vwap_exit = curr_close > curr_vwap
                    pivot_exit = curr_close > r1
                    exit_triggered = tsl_hit or st2_flipped_bull or pivot_exit or vwap_exit or time_stop_hit

                    if exit_triggered:
                        reason = "Trailing SL Hit" if tsl_hit else ("VWAP Breakout" if vwap_exit else ("30m Time Stop" if time_stop_hit else "ST/Pivot Flip"))
                        pnl = pos["entry_price"] - curr_close
                        send_telegram(
                            f"🟢 *PUT EXIT*: `{name}`\n"
                            f"• Exit Spot: ₹{curr_close:,.2f} ({pnl:+.2f} pts)\n"
                            f"• Reason: *{reason}*\n"
                            f"• Action: Square off `{pos['itm_strike']} PE`"
                        )
                        pos = get_default_item_state()

            # -------------------------------------------------------------
            # B. 2-CANDLE ENTRY LOGIC (9:30 AM TO 3:00 PM IST)
            # -------------------------------------------------------------
            else:
                if not is_valid_entry:
                    continue

                is_green = curr_close > curr_open
                is_red = curr_close < curr_open

                call_condition = (
                    is_green and 
                    st1_bull and 
                    (curr_close > float(st1_val.iloc[-1])) and 
                    (curr_close > m3_upper) and 
                    (rsi_prev > 60.0) and 
                    (curr_close > curr_vwap) and 
                    (curr_close > daily_ema20)
                )

                put_condition = (
                    is_red and 
                    st1_bear and 
                    (curr_close < float(st1_val.iloc[-1])) and 
                    (curr_close < m2_lower) and 
                    (rsi_prev < 40.0) and 
                    (curr_close < curr_vwap) and 
                    (curr_close < daily_ema20)
                )

                # Candle 2 Check + Volume
                if pos.get("pending_stage") == "PENDING_CALL":
                    if call_condition and vol_confirmed:
                        atm, itm = get_options_strikes(curr_close, step, "CALL")
                        pos.update({
                            "in_trade": True, "pending_stage": None, "trade_type": "CALL",
                            "entry_price": curr_close, "extreme_price": curr_high,
                            "trailing_sl": round(curr_close - trail_buffer, 2), "trail_buffer": trail_buffer,
                            "atm_strike": atm, "itm_strike": itm, "candles_held": 0
                        })
                        send_telegram(
                            f"🟢 *CALL CONFIRMED ENTRY (CE)*\n\n"
                            f"✅ *2nd Candle + Volume Confirmed!*\n"
                            f"• `{name}` | Spot: ₹{curr_close:,.2f}\n"
                            f"• VWAP: ₹{curr_vwap:,.2f} | Dynamic SL: ₹{pos['trailing_sl']:,.2f}\n"
                            f"• Recommended: `{itm} CE` (ATM: `{atm} CE`)\n"
                            f"⏳ *Auto Time-Stop:* 30 Mins (Max 6 Candles)"
                        )
                    else:
                        pos["pending_stage"] = None

                elif pos.get("pending_stage") == "PENDING_PUT":
                    if put_condition and vol_confirmed:
                        atm, itm = get_options_strikes(curr_close, step, "PUT")
                        pos.update({
                            "in_trade": True, "pending_stage": None, "trade_type": "PUT",
                            "entry_price": curr_close, "extreme_price": curr_low,
                            "trailing_sl": round(curr_close + trail_buffer, 2), "trail_buffer": trail_buffer,
                            "atm_strike": atm, "itm_strike": itm, "candles_held": 0
                        })
                        send_telegram(
                            f"🔴 *PUT CONFIRMED ENTRY (PE)*\n\n"
                            f"✅ *2nd Candle + Volume Confirmed!*\n"
                            f"• `{name}` | Spot: ₹{curr_close:,.2f}\n"
                            f"• VWAP: ₹{curr_vwap:,.2f} | Dynamic SL: ₹{pos['trailing_sl']:,.2f}\n"
                            f"• Recommended: `{itm} PE` (ATM: `{atm} PE`)\n"
                            f"⏳ *Auto Time-Stop:* 30 Mins (Max 6 Candles)"
                        )
                    else:
                        pos["pending_stage"] = None

                # Candle 1 Setup Check
                else:
                    if call_condition:
                        pos["pending_stage"] = "PENDING_CALL"
                        send_telegram(
                            f"🟡 *CALL SETUP DETECTED (Candle 1)*\n\n"
                            f"• `{name}` | Spot: ₹{curr_close:,.2f}\n"
                            f"• Above VWAP & M3 Pivot. Waiting for Candle 2 Confirmation!"
                        )
                    elif put_condition:
                        pos["pending_stage"] = "PENDING_PUT"
                        send_telegram(
                            f"🟡 *PUT SETUP DETECTED (Candle 1)*\n\n"
                            f"• `{name}` | Spot: ₹{curr_close:,.2f}\n"
                            f"• Below VWAP & M2 Pivot. Waiting for Candle 2 Confirmation!"
                        )

            state[ticker] = pos
        except Exception:
            continue

    save_state(group_name, state)

# =====================================================================
# 6. INTRADAY CONTINUOUS LOOP (9:30 AM TO 3:15 PM IST)
# =====================================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", required=True, choices=list(SECTOR_MAPS.keys()))
    args = parser.parse_args()

    group_name = args.group
    strike_dict = SECTOR_MAPS[group_name]
    ist = pytz.timezone("Asia/Kolkata")
    print(f"🚀 Session active for [{group_name}]. Monitoring {len(strike_dict)} tickers (09:30 - 15:15 IST)...")

    while True:
        now_ist = datetime.datetime.now(ist)
        total_mins = now_ist.hour * 60 + now_ist.minute

        # Terminate script after 3:15 PM IST (15:15 = 915 mins) or on weekends
        if total_mins > 915 or now_ist.weekday() > 4:
            print(f"[{group_name}] Session reached 3:15 PM IST cutoff. Concluding execution.")
            break

        # Run scans once clock passes 9:30 AM IST (09:30 = 570 mins)
        if total_mins >= 570:
            try:
                run_scan(group_name, strike_dict)
            except Exception as e:
                print(f"[{group_name}] Scan cycle error: {e}")
        else:
            print(f"[{group_name}] Time: {now_ist.strftime('%H:%M:%S IST')} — Waiting for 9:30 AM IST session start...")

        time.sleep(300)

if __name__ == "__main__":
    main()
