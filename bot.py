import datetime
import math
import numpy as np
import pandas as pd
import pytz
import requests
import yfinance as yf

# =====================================================================
# 1. TELEGRAM CONFIGURATION
# =====================================================================
TELEGRAM_BOT_TOKEN = "8721771664:AAFcyCX2TP2KsUrIQoh6utZvHjbLQt8vD-k"
TELEGRAM_CHAT_ID = "846124589"

# =====================================================================
# 2. WATCHLIST & STRIKE INTERVALS (INDICES & TOP F&O STOCKS)
# =====================================================================
# Maps tickers to their options strike step size for ATM / ITM calculation
STRIKE_STEPS = {
    "^NSEI": 50,  # Nifty 50
    "^NSEBANK": 100,  # Bank Nifty
    "^BSESN": 100,  # Sensex
    "NIFTY_FIN_SERVICE.NS": 50,  # FinNifty
    "RELIANCE.NS": 20,  # Reliance
    "HDFCBANK.NS": 20,  # HDFC Bank
    "ICICIBANK.NS": 10,  # ICICI Bank
    "SBIN.NS": 10,  # SBI
    "TATAMOTORS.NS": 10,  # Tata Motors
    "INFY.NS": 20,  # Infosys
    "TCS.NS": 50,  # TCS
    "LT.NS": 50,  # L&T
    "AXISBANK.NS": 10,  # Axis Bank
    "BAJFINANCE.NS": 50,  # Bajaj Finance
    "MARUTI.NS": 100,  # Maruti
    "BHARTIARTL.NS": 10,  # Airtel
}

WATCHLIST = list(STRIKE_STEPS.keys())
TIMEFRAME = "5m"


def send_telegram(text):
  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
  payload = {
      "chat_id": TELEGRAM_CHAT_ID,
      "text": text,
      "parse_mode": "Markdown",
  }
  try:
    requests.post(url, json=payload, timeout=10)
  except Exception as e:
    print(f"Telegram error: {e}")


def is_market_hours():
  """Checks if current time in IST is between 09:30 AM and 03:15 PM, Mon-Fri."""
  ist = pytz.timezone("Asia/Kolkata")
  now_ist = datetime.datetime.now(ist)

  # Monday = 0, Friday = 4, Saturday = 5, Sunday = 6
  if now_ist.weekday() > 4:
    return False

  market_start = now_ist.replace(
      hour=9, minute=30, second=0, microsecond=0
  )
  market_end = now_ist.replace(
      hour=15, minute=15, second=0, microsecond=0
  )

  return market_start <= now_ist <= market_end


def get_options_strikes(price, step):
  """Calculates exact ATM (At The Money) and ITM (In The Money) Call strikes."""
  atm_strike = int(round(price / step) * step)
  itm_strike = atm_strike - step  # 1 Strike In-The-Money Call
  return atm_strike, itm_strike


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
    prev_st = (
        st.iloc[i - 1] if not np.isnan(st.iloc[i - 1]) else upper.iloc[i]
    )
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
  """Calculates Central Pivot (P), Resistance 1 (R1), and Mid-Pivot (M3)."""
  try:
    df_d = yf.download(ticker, period="5d", interval="1d", progress=False)
    if len(df_d) < 2:
      return None, None, None, None
    if isinstance(df_d.columns, pd.MultiIndex):
      df_d.columns = df_d.columns.get_level_values(0)

    prev = df_d.iloc[-2]
    h, l, c = float(prev["High"]), float(prev["Low"]), float(prev["Close"])

    pivot = (h + l + c) / 3.0
    r1 = (2.0 * pivot) - l
    s1 = (2.0 * pivot) - h
    mid_pivot = (pivot + r1) / 2.0  # M3 Mid-Pivot between P and R1

    return pivot, mid_pivot, s1, r1
  except Exception:
    return None, None, None, None


def run_scan():
  # Strict Trading Time Check (09:30 AM to 03:15 PM IST)
  if not is_market_hours():
    print("Market is currently closed or outside 9:30 AM - 3:15 PM IST window.")
    return

  print("Running 5M scan across Index & Stock Options watchlist...")

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
      pivot, mid_pivot, s1, r1 = get_daily_pivots(ticker)

      if pivot is None or mid_pivot is None:
        continue

      curr_close = float(df["Close"].iloc[-1])
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

      # --- ENTRY CONDITION: ST (10,3) Bullish + Price > Mid-Pivot + RSI > 60 + Green Candle ---
      if (
          curr_close > float(st1_val.iloc[-1])
          and st1_bull
          and curr_close > mid_pivot
          and rsi_prev > 60.0
          and curr_close > curr_open
      ):

        msg = (
            f"🟢 *CALL / BUY ENTRY ALERT (9:30-3:15)*\n\n"
            f"• *Instrument:* `{name}`\n"
            f"• *Spot Price:* ₹{curr_close:,.2f}\n"
            f"• *Mid-Pivot Level:* ₹{mid_pivot:,.2f}\n"
            f"• *SuperTrend (10,3):* ₹{float(st1_val.iloc[-1]):,.2f}\n"
            f"• *Prior RSI:* {rsi_prev:.2f}\n\n"
            f"🎯 *Recommended Options Strikes:*\n"
            f"• *ATM Call (CE):* `{atm_ce} CE`\n"
            f"• *ITM Call (CE):* `{itm_ce} CE` *(Recommended for higher delta &"
            " less theta decay)*\n\n"
            f"• *Execution:* Place order on Zerodha Kite"
        )
        send_telegram(msg)

      # --- EXIT CONDITION: ST (7,2) Reversal OR Breakdown Below Pivot Low (S1) ---
      elif st2_bear or curr_close < s1:
        reason = (
            "ST (7,2) Bearish Reversal"
            if st2_bear
            else "Broken Below Pivot Low (S1)"
        )
        msg = (
            f"🔴 *EXIT / SQUARE-OFF ALERT*\n\n"
            f"• *Instrument:* `{name}`\n"
            f"• *Current Spot:* ₹{curr_close:,.2f}\n"
            f"• *Trigger Reason:* {reason}\n"
            f"• *Suggested Action:* Square off `{atm_ce} CE` / `{itm_ce} CE` in"
            " Zerodha"
        )
        send_telegram(msg)

    except Exception:
      continue


if __name__ == "__main__":
  run_scan()
