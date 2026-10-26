import datetime
import json
import math
import os
import numpy as np
import pandas as pd
import pytz
import requests
import yfinance as yf

# =====================================================================
# 1. DUAL TELEGRAM CONFIGURATION (BROADCASTS TO BOTH)
# =====================================================================
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

# =====================================================================
# 2. WATCHLIST & STRIKE INTERVALS
# =====================================================================
STRIKE_STEPS = {
    "^NSEI": 50,  # Nifty 50
    "^NSEBANK": 100,  # Bank Nifty
    "^BSESN": 100,  # Sensex
    "NIFTY_FIN_SERVICE.NS": 50,  # FinNifty
    "RELIANCE.NS": 20,
    "HDFCBANK.NS": 20,
    "ICICIBANK.NS": 10,
    "SBIN.NS": 10,
    "TATAMOTORS.NS": 10,
    "INFY.NS": 20,
    "TCS.NS": 50,
    "LT.NS": 50,
    "AXISBANK.NS": 10,
    "BAJFINANCE.NS": 50,
    "MARUTI.NS": 100,
    "BHARTIARTL.NS": 10,
}

WATCHLIST = list(STRIKE_STEPS.keys())
TIMEFRAME = "5m"
TRAILING_SL_PCT = 0.05  # 5% trailing distance
STATE_FILE = "trade_state.json"


# =====================================================================
# 3. POSITION STATE MANAGEMENT (PERSISTENCE)
# =====================================================================
def load_state():
  if os.path.exists(STATE_FILE):
    try:
      with open(STATE_FILE, "r") as f:
        return json.load(f)
    except Exception:
      pass
  return {
      ticker: {
          "in_trade": False,
          "entry_price": 0.0,
          "highest_price": 0.0,
          "trailing_sl": 0.0,
          "atm_strike": 0,
          "itm_strike": 0,
      }
      for ticker in WATCHLIST
  }


def save_state(state):
  with open(STATE_FILE, "w") as f:
    json.dump(state, f, indent=2)


def send_telegram(text):
  """Sends alerts to all configured Telegram bots/accounts."""
  for recipient in TELEGRAM_RECIPIENTS:
    url = f"https://api.telegram.org/bot{recipient['token']}/sendMessage"
    payload = {
        "chat_id": recipient["chat_id"],
        "text": text,
        "parse_mode": "Markdown",
    }
    try:
      requests.post(url, json=payload, timeout=10)
    except Exception as e:
      print(f"Telegram error for chat {recipient['chat_id']}: {e}")


def is_market_hours():
  ist = pytz.timezone("Asia/Kolkata")
  now_ist = datetime.datetime.now(ist)

  if now_ist.weekday() > 4:  # Closed Saturday & Sunday
    return False

  market_start = now_ist.replace(hour=9, minute=30, second=0, microsecond=0)
  market_end = now_ist.replace(hour=15, minute=15, second=0, microsecond=0)
  return market_start <= now_ist <= market_end


def get_options_strikes(price, step):
  atm = int(round(price / step) * step)
  itm = atm - step
  return atm, itm


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
  atr = tr.ewm(alpha=1 / period, adjust=False).mean()

  hl2 = (high + low) / 2.0
  upper = hl2 + (multiplier * atr)
  lower = hl2 - (multiplier * atr)

  st = pd.Series(index=df.index, dtype=float)
  direction = pd.Series(index=df.index, dtype=int)

  for i in range(1, len(df)):
    curr_c = close.iloc[i]
    prev_st = st.iloc[i - 1] if not np.isnan(st.iloc[i - 1]) else upper.iloc[i]
    prev_dir = (
        direction.iloc[i - 1] if not np.isnan(direction.iloc[i - 1]) else 1
    )

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


def get_daily_pivots(ticker):
  try:
    df_d = yf.download(ticker, period="5d", interval="1d", progress=False)
    if len(df_d) < 2:
      return None, None, None
    if isinstance(df_d.columns, pd.MultiIndex):
      df_d.columns = df_d.columns.get_level_values(0)

    prev = df_d.iloc[-2]
    h, l, c = float(prev["High"]), float(prev["Low"]), float(prev["Close"])
    pivot = (h + l + c) / 3.0
    r1 = (2.0 * pivot) - l
    s1 = (2.0 * pivot) - h
    mid_pivot = (pivot + r1) / 2.0
    return pivot, mid_pivot, s1
  except Exception:
    return None, None, None


# =====================================================================
# 4. SCAN ENGINE WITH 5% TRAILING STOP LOSS
# =====================================================================
def run_scan():
  if not is_market_hours():
    print("Market closed or outside 9:30 AM - 3:15 PM IST window.")
    return

  state = load_state()

  for ticker in WATCHLIST:
    try:
      df = yf.download(ticker, period="3d", interval=TIMEFRAME, progress=False)
      if len(df) < 30:
        continue
      if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

      st1_val, st1_dir = calculate_supertrend(df, 10, 3.0)
      st2_val, st2_dir = calculate_supertrend(df, 7, 2.0)
      rsi_series = calculate_rsi(df["Close"], 14)
      pivot, mid_pivot, s1 = get_daily_pivots(ticker)

      if pivot is None or mid_pivot is None:
        continue

      curr_close = float(df["Close"].iloc[-1])
      curr_high = float(df["High"].iloc[-1])
      curr_open = float(df["Open"].iloc[-1])

      st1_bull = st1_dir.iloc[-1] == 1
      st2_bear = st2_dir.iloc[-1] == -1 and st2_dir.iloc[-2] == 1
      rsi_prev = float(rsi_series.iloc[-2])

      step = STRIKE_STEPS.get(ticker, 50)
      atm_ce, itm_ce = get_options_strikes(curr_close, step)

      name = (
          ticker.replace(".NS", "")
          .replace("^NSEI", "NIFTY 50")
          .replace("^NSEBANK", "BANK NIFTY")
          .replace("^BSESN", "SENSEX")
      )

      pos = state.get(
          ticker,
          {
              "in_trade": False,
              "entry_price": 0.0,
              "highest_price": 0.0,
              "trailing_sl": 0.0,
              "atm_strike": 0,
              "itm_strike": 0,
          },
      )

      # -------------------------------------------------------------
      # SCENARIO A: ACTIVE POSITION MANAGEMENT (CHECK TSL & EXITS)
      # -------------------------------------------------------------
      if pos["in_trade"]:
        if curr_high > pos["highest_price"]:
          pos["highest_price"] = curr_high
          new_tsl = curr_high * (1.0 - TRAILING_SL_PCT)
          if new_tsl > pos["trailing_sl"]:
            pos["trailing_sl"] = round(new_tsl, 2)

        tsl_hit = curr_close <= pos["trailing_sl"]
        pivot_exit = curr_close < s1
        exit_triggered = tsl_hit or st2_bear or pivot_exit

        if exit_triggered:
          reason = ""
          if tsl_hit:
            reason = f"5% Trailing Stop-Loss Hit (₹{pos['trailing_sl']:,.2f})"
          elif st2_bear:
            reason = "SuperTrend (7,2) Bearish Flip"
          elif pivot_exit:
            reason = "Broken Below Pivot Low (S1)"

          entry_px = pos["entry_price"]
          pnl_pct = ((curr_close - entry_px) / entry_px) * 100.0

          msg = (
              f"🔴 *EXIT / SQUARE-OFF ALERT*\n\n"
              f"• *Instrument:* `{name}`\n"
              f"• *Exit Price:* ₹{curr_close:,.2f}\n"
              f"• *Entry Price:* ₹{entry_px:,.2f}\n"
              f"• *Highest Peak:* ₹{pos['highest_price']:,.2f}\n"
              f"• *Final PnL:* {pnl_pct:+.2f}%\n"
              f"• *Reason:* {reason}\n"
              f"• *Action:* Square off `{pos.get('itm_strike', itm_ce)} CE` in"
              " Zerodha Kite"
          )
          send_telegram(msg)

          pos["in_trade"] = False
          pos["entry_price"] = 0.0
          pos["highest_price"] = 0.0
          pos["trailing_sl"] = 0.0

      # -------------------------------------------------------------
      # SCENARIO B: NEW CALL / BUY ENTRY
      # -------------------------------------------------------------
      else:
        is_green = curr_close > curr_open
        above_st = curr_close > float(st1_val.iloc[-1]) and st1_bull
        above_mid = curr_close > mid_pivot
        rsi_ok = rsi_prev > 60.0

        if above_st and above_mid and rsi_ok and is_green:
          initial_sl = round(curr_close * (1.0 - TRAILING_SL_PCT), 2)

          pos["in_trade"] = True
          pos["entry_price"] = curr_close
          pos["highest_price"] = curr_high
          pos["trailing_sl"] = initial_sl
          pos["atm_strike"] = atm_ce
          pos["itm_strike"] = itm_ce

          msg = (
              f"🟢 *CALL / BUY ENTRY ALERT (9:30-3:15)*\n\n"
              f"• *Instrument:* `{name}`\n"
              f"• *Spot Entry:* ₹{curr_close:,.2f}\n"
              f"• *Initial 5% SL:* ₹{initial_sl:,.2f}\n"
              f"• *Mid-Pivot Level:* ₹{mid_pivot:,.2f}\n"
              f"• *SuperTrend (10,3):* ₹{float(st1_val.iloc[-1]):,.2f}\n"
              f"• *Prior RSI:* {rsi_prev:.2f}\n\n"
              f"🎯 *Recommended Options Strikes:*\n"
              f"• *ATM Call (CE):* `{atm_ce} CE`\n"
              f"• *ITM Call (CE):* `{itm_ce} CE` *(Recommended)*\n\n"
              f"📌 *Trailing Rule:* Stop-loss trails 5% below every new peak"
              " high reached."
          )
          send_telegram(msg)

      state[ticker] = pos

    except Exception:
      continue

  save_state(state)


if __name__ == "__main__":
  run_scan()
