import numpy as np
import pandas as pd
import requests
import yfinance as yf

# =====================================================================
# 1. TELEGRAM CONFIGURATION
# =====================================================================
TELEGRAM_BOT_TOKEN = "8721771664:AAFcyCX2TP2KsUrIQoh6utZvHjbLQt8vD-k"
TELEGRAM_CHAT_ID = "846124589"

# =====================================================================
# 2. WATCHLIST (INDICES + TOP HIGH-BETA NIFTY DRIVERS)
# =====================================================================
WATCHLIST = [
    "^NSEI",
    "^NSEBANK",
    "^BSESN",
    "RELIANCE.NS",
    "HDFCBANK.NS",
    "ICICIBANK.NS",
    "TATAMOTORS.NS",
    "SBIN.NS",
    "INFY.NS",
    "TCS.NS",
    "LT.NS",
    "AXISBANK.NS",
    "BAJFINANCE.NS",
]


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
  try:
    df_d = yf.download(ticker, period="5d", interval="1d", progress=False)
    if len(df_d) < 2:
      return None, None
    if isinstance(df_d.columns, pd.MultiIndex):
      df_d.columns = df_d.columns.get_level_values(0)

    prev = df_d.iloc[-2]
    h, l, c = float(prev["High"]), float(prev["Low"]), float(prev["Close"])
    pivot = (h + l + c) / 3.0
    s1 = (2.0 * pivot) - h
    return pivot, s1
  except Exception:
    return None, None


def run_scan():
  print("Scanning 5-minute charts...")
  for ticker in WATCHLIST:
    try:
      df = yf.download(ticker, period="3d", interval="5m", progress=False)
      if len(df) < 30:
        continue
      if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

      st1_val, st1_dir = calculate_supertrend(df, 10, 3.0)
      st2_val, st2_dir = calculate_supertrend(df, 7, 2.0)
      rsi_series = calculate_rsi(df["Close"], 14)
      pivot, s1 = get_daily_pivots(ticker)

      if pivot is None:
        continue

      curr_close = float(df["Close"].iloc[-1])
      curr_open = float(df["Open"].iloc[-1])
      st1_bull = st1_dir.iloc[-1] == 1
      st2_bear = st2_dir.iloc[-1] == -1 and st2_dir.iloc[-2] == 1
      rsi_prev = float(rsi_series.iloc[-2])

      name = (
          ticker.replace(".NS", "")
          .replace("^NSEI", "NIFTY 50")
          .replace("^NSEBANK", "BANK NIFTY")
          .replace("^BSESN", "SENSEX")
      )

      # --- Entry Condition ---
      if (
          curr_close > float(st1_val.iloc[-1])
          and st1_bull
          and curr_close > pivot
          and rsi_prev > 60.0
          and curr_close > curr_open
      ):
        msg = (
            f"🟢 *CALL / BUY ENTRY ALERT*\n\n"
            f"• *Symbol:* `{name}`\n"
            f"• *Price:* ₹{curr_close:,.2f}\n"
            f"• *SuperTrend (10,3):* ₹{float(st1_val.iloc[-1]):,.2f}\n"
            f"• *Daily Pivot:* ₹{pivot:,.2f}\n"
            f"• *Prior RSI:* {rsi_prev:.2f}\n"
            f"• *Action:* Buy Call Option / Cash in Zerodha"
        )
        send_telegram(msg)

      # --- Exit Condition ---
      elif st2_bear or curr_close < s1:
        reason = (
            "ST (7,2) Bearish Reversal"
            if st2_bear
            else "Broken Below Pivot Low (S1)"
        )
        msg = (
            f"🔴 *EXIT / SQUARE-OFF ALERT*\n\n"
            f"• *Symbol:* `{name}`\n"
            f"• *Exit Price:* ₹{curr_close:,.2f}\n"
            f"• *Reason:* {reason}\n"
            f"• *Action:* Square off position in Zerodha"
        )
        send_telegram(msg)

    except Exception:
      continue


if __name__ == "__main__":
  run_scan()
