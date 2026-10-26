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
# 1. DUAL TELEGRAM RECIPIENTS
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
    "^NSEI": 50,  # NIFTY 50
    "^NSEBANK": 100,  # BANK NIFTY
    "^BSESN": 100,  # SENSEX
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
ATR_MULTIPLIER = 1.5  # Dynamic risk buffer based on 5-minute volatility
STATE_FILE = "trade_state.json"


# =====================================================================
# 3. POSITION STATE PERSISTENCE
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
          "trade_type": "",
          "entry_price": 0.0,
          "extreme_price": 0.0,
          "trailing_sl": 0.0,
          "trail_buffer": 0.0,
          "atm_strike": 0,
          "itm_strike": 0,
      }
      for ticker in WATCHLIST
  }


def save_state(state):
  with open(STATE_FILE, "w") as f:
    json.dump(state, f, indent=2)


def send_telegram(text):
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

  if now_ist.weekday() > 4:  # Closed Sat & Sun
    return False

  market_start = now_ist.replace(hour=9, minute=30, second=0, microsecond=0)
  market_end = now_ist.replace(hour=15, minute=15, second=0, microsecond=0)
  return market_start <= now_ist <= market_end


def get_options_strikes(price, step, direction="CALL"):
  atm = (
      int(round(price / step) * step)
      if step >= 1
      else round(price / step) * step
  )
  itm = (atm - step) if direction == "CALL" else (atm + step)

  atm_fmt = (
      int(atm)
      if isinstance(atm, (int, np.integer)) or atm.is_integer()
      else f"{atm:.1f}"
  )
  itm_fmt = (
      int(itm)
      if isinstance(itm, (int, np.integer)) or itm.is_integer()
      else f"{itm:.1f}"
  )
  return atm_fmt, itm_fmt


# =====================================================================
# 4. TECHNICAL INDICATORS (ATR, RSI, SUPERTREND, PIVOTS)
# =====================================================================
def calculate_atr(df, period=14):
  high, low, close = df["High"], df["Low"], df["Close"]
  tr1 = high - low
  tr2 = (high - close.shift(1)).abs()
  tr3 = (low - close.shift(1)).abs()
  tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
  return tr.ewm(alpha=1 / period, adjust=False).mean()


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
      return None, None, None, None, None
    if isinstance(df_d.columns, pd.MultiIndex):
      df_d.columns = df_d.columns.get_level_values(0)

    prev = df_d.iloc[-2]
    h, l, c = float(prev["High"]), float(prev["Low"]), float(prev["Close"])
    pivot = (h + l + c) / 3.0
    r1 = (2.0 * pivot) - l
    s1 = (2.0 * pivot) - h
    m3_upper = (pivot + r1) / 2.0
    m2_lower = (pivot + s1) / 2.0
    return pivot, m3_upper, m2_lower, r1, s1
  except Exception:
    return None, None, None, None, None


# =====================================================================
# 5. SCAN ENGINE
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

      atr_series = calculate_atr(df, period=14)
      current_atr = float(atr_series.iloc[-1])
      trail_buffer = round(current_atr * ATR_MULTIPLIER, 2)

      st1_val, st1_dir = calculate_supertrend(df, 10, 3.0)
      st2_val, st2_dir = calculate_supertrend(df, 7, 2.0)
      rsi_series = calculate_rsi(df["Close"], 14)
      pivot, m3_upper, m2_lower, r1, s1 = get_daily_pivots(ticker)

      if pivot is None or m3_upper is None or m2_lower is None:
        continue

      curr_close = float(df["Close"].iloc[-1])
      curr_high = float(df["High"].iloc[-1])
      curr_low = float(df["Low"].iloc[-1])
      curr_open = float(df["Open"].iloc[-1])

      st1_bull = st1_dir.iloc[-1] == 1
      st1_bear = st1_dir.iloc[-1] == -1
      st2_flipped_bear = st2_dir.iloc[-1] == -1 and st2_dir.iloc[-2] == 1
      st2_flipped_bull = st2_dir.iloc[-1] == 1 and st2_dir.iloc[-2] == -1
      rsi_prev = float(rsi_series.iloc[-2])

      step = STRIKE_STEPS.get(ticker, 50)
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
              "trade_type": "",
              "entry_price": 0.0,
              "extreme_price": 0.0,
              "trailing_sl": 0.0,
              "trail_buffer": 0.0,
              "atm_strike": 0,
              "itm_strike": 0,
          },
      )

      # -------------------------------------------------------------
      # 1. POSITION MANAGEMENT & TRAILING STOP-LOSS
      # -------------------------------------------------------------
      if pos["in_trade"]:
        trade_type = pos["trade_type"]
        buf = pos.get("trail_buffer", trail_buffer)

        # CALL EXIT / TRAILING LOGIC
        if trade_type == "CALL":
          if curr_high > pos["extreme_price"]:
            pos["extreme_price"] = curr_high
            new_tsl = round(curr_high - buf, 2)
            if new_tsl > pos["trailing_sl"]:
              pos["trailing_sl"] = new_tsl

          tsl_hit = curr_close <= pos["trailing_sl"]
          pivot_exit = curr_close < s1
          exit_triggered = tsl_hit or st2_flipped_bear or pivot_exit

          if exit_triggered:
            reason = ""
            if tsl_hit:
              reason = f"Trailing Stop Hit (₹{pos['trailing_sl']:,.2f})"
            elif st2_flipped_bear:
              reason = "SuperTrend (7,2) Bearish Flip"
            elif pivot_exit:
              reason = "Broken Below Pivot Low (S1)"

            pnl_pts = curr_close - pos["entry_price"]
            msg = (
                f"🔴 *CALL EXIT / SQUARE-OFF ALERT*\n\n"
                f"• *Instrument:* `{name}`\n"
                f"• *Exit Spot:* ₹{curr_close:,.2f}\n"
                f"• *Entry Spot:* ₹{pos['entry_price']:,.2f}\n"
                f"• *Highest Peak:* ₹{pos['extreme_price']:,.2f}\n"
                f"• *Spot Points PnL:* {pnl_pts:+.2f} pts\n"
                f"• *Reason:* {reason}\n"
                f"• *Action:* Square off `{pos['itm_strike']} CE` in Zerodha"
            )
            send_telegram(msg)
            pos["in_trade"] = False

        # PUT EXIT / TRAILING LOGIC
        elif trade_type == "PUT":
          if curr_low < pos["extreme_price"]:
            pos["extreme_price"] = curr_low
            new_tsl = round(curr_low + buf, 2)
            if new_tsl < pos["trailing_sl"] or pos["trailing_sl"] == 0:
              pos["trailing_sl"] = new_tsl

          tsl_hit = curr_close >= pos["trailing_sl"]
          pivot_exit = curr_close > r1
          exit_triggered = tsl_hit or st2_flipped_bull or pivot_exit

          if exit_triggered:
            reason = ""
            if tsl_hit:
              reason = f"Trailing Stop Hit (₹{pos['trailing_sl']:,.2f})"
            elif st2_flipped_bull:
              reason = "SuperTrend (7,2) Bullish Flip"
            elif pivot_exit:
              reason = "Broke Above Resistance (R1)"

            pnl_pts = pos["entry_price"] - curr_close
            msg = (
                f"🟢 *PUT EXIT / SQUARE-OFF ALERT*\n\n"
                f"• *Instrument:* `{name}`\n"
                f"• *Exit Spot:* ₹{curr_close:,.2f}\n"
                f"• *Entry Spot:* ₹{pos['entry_price']:,.2f}\n"
                f"• *Lowest Valley:* ₹{pos['extreme_price']:,.2f}\n"
                f"• *Spot Points Gain:* {pnl_pts:+.2f} pts\n"
                f"• *Reason:* {reason}\n"
                f"• *Action:* Square off `{pos['itm_strike']} PE` in Zerodha"
            )
            send_telegram(msg)
            pos["in_trade"] = False

      # -------------------------------------------------------------
      # 2. NEW ENTRY CHECKS (CALL OR PUT)
      # -------------------------------------------------------------
      else:
        # A. CALL / BUY ENTRY
        is_green = curr_close > curr_open
        call_st = curr_close > float(st1_val.iloc[-1]) and st1_bull
        call_pivot = curr_close > m3_upper
        call_rsi = rsi_prev > 60.0

        if call_st and call_pivot and call_rsi and is_green:
          atm_ce, itm_ce = get_options_strikes(
              curr_close, step, direction="CALL"
          )
          initial_sl = round(curr_close - trail_buffer, 2)

          pos["in_trade"] = True
          pos["trade_type"] = "CALL"
          pos["entry_price"] = curr_close
          pos["extreme_price"] = curr_high
          pos["trailing_sl"] = initial_sl
          pos["trail_buffer"] = trail_buffer
          pos["atm_strike"] = atm_ce
          pos["itm_strike"] = itm_ce

          msg = (
              f"🟢 *CALL / LONG ENTRY ALERT (CE)*\n\n"
              f"• *Instrument:* `{name}`\n"
              f"• *Spot Entry:* ₹{curr_close:,.2f}\n"
              f"• *Dynamic SL:* ₹{initial_sl:,.2f} "
              f"*(Risk: {trail_buffer} pts)*\n"
              f"• *Upper Mid-Pivot (M3):* ₹{m3_upper:,.2f}\n"
              f"• *SuperTrend (10,3):* ₹{float(st1_val.iloc[-1]):,.2f}\n"
              f"• *Prior RSI:* {rsi_prev:.2f}\n\n"
              f"🎯 *Recommended Call Strikes:*\n"
              f"• *ATM Call:* `{atm_ce} CE`\n"
              f"• *ITM Call:* `{itm_ce} CE` *(Recommended)*\n\n"
              f"📌 *Trailing Rule:* Trails exactly {trail_buffer} pts below"
              " highest peak reached."
          )
          send_telegram(msg)

        # B. PUT / SHORT ENTRY
        else:
          is_red = curr_close < curr_open
          put_st = curr_close < float(st1_val.iloc[-1]) and st1_bear
          put_pivot = curr_close < m2_lower
          put_rsi = rsi_prev < 40.0

          if put_st and put_pivot and put_rsi and is_red:
            atm_pe, itm_pe = get_options_strikes(
                curr_close, step, direction="PUT"
            )
            initial_sl = round(curr_close + trail_buffer, 2)

            pos["in_trade"] = True
            pos["trade_type"] = "PUT"
            pos["entry_price"] = curr_close
            pos["extreme_price"] = curr_low
            pos["trailing_sl"] = initial_sl
            pos["trail_buffer"] = trail_buffer
            pos["atm_strike"] = atm_pe
            pos["itm_strike"] = itm_pe

            msg = (
                f"🔴 *PUT / SHORT ENTRY ALERT (PE)*\n\n"
                f"• *Instrument:* `{name}`\n"
                f"• *Spot Entry:* ₹{curr_close:,.2f}\n"
                f"• *Dynamic SL:* ₹{initial_sl:,.2f} "
                f"*(Risk: {trail_buffer} pts)*\n"
                f"• *Lower Mid-Pivot (M2):* ₹{m2_lower:,.2f}\n"
                f"• *SuperTrend (10,3):* ₹{float(st1_val.iloc[-1]):,.2f}\n"
                f"• *Prior RSI:* {rsi_prev:.2f}\n\n"
                f"🎯 *Recommended Put Strikes:*\n"
                f"• *ATM Put:* `{atm_pe} PE`\n"
                f"• *ITM Put:* `{itm_pe} PE` *(Recommended)*\n\n"
                f"📌 *Trailing Rule:* Trails exactly {trail_buffer} pts above"
                " lowest valley reached."
            )
            send_telegram(msg)

      state[ticker] = pos

    except Exception:
      continue

  save_state(state)


if __name__ == "__main__":
  run_scan()
