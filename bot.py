import datetime
import time
import pandas as pd
import pandas_ta as ta
import requests
import yfinance as yf

# =====================================================================
# 1. TELEGRAM CONFIGURATION
# =====================================================================
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # From @BotFather
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID_HERE"  # From @userinfobot

# =====================================================================
# 2. AUTO-POPULATED WATCHLIST (INDICES + ENTIRE NIFTY 50)
# =====================================================================
# Major benchmark indices
BENCHMARKS = ["^NSEI", "^NSEBANK", "^BSESN"]

# Official Nifty 50 constituent symbols (auto-appended with .NS)
NIFTY_50_STOCKS = [
    "ADANIENT",
    "ADANIPORTS",
    "APOLLOHOSP",
    "ASIANPAINT",
    "AXISBANK",
    "BAJAJ-AUTO",
    "BAJFINANCE",
    "BAJAJFINSV",
    "BPCL",
    "BHARTIARTL",
    "BRITANNIA",
    "CIPLA",
    "COALINDIA",
    "DRREDDY",
    "EICHERMOT",
    "GRASIM",
    "HCLTECH",
    "HDFCBANK",
    "HDFCLIFE",
    "HEROMOTOCO",
    "HINDALCO",
    "HINDUNILVR",
    "ICICIBANK",
    "ITC",
    "INDUSINDBK",
    "INFY",
    "JSWSTEEL",
    "KOTAKBANK",
    "LT",
    "M&M",
    "MARUTI",
    "NTPC",
    "NESTLEIND",
    "ONGC",
    "POWERGRID",
    "RELIANCE",
    "SBILIFE",
    "SHRIRAMFIN",
    "SBIN",
    "SUNPHARMA",
    "TCS",
    "TATACONSUM",
    "TATAMOTORS",
    "TATASTEEL",
    "TECHM",
    "TITAN",
    "ULTRACEMCO",
    "WIPRO",
    "SIEMENS",
    "TRENT",
]


def load_full_watchlist():
  """Combines major indices with the full Nifty 50 constituents."""
  basket = list(BENCHMARKS)
  for sym in NIFTY_50_STOCKS:
    formatted_sym = f"{sym}.NS"
    if formatted_sym not in basket:
      basket.append(formatted_sym)
  return basket


WATCHLIST = load_full_watchlist()
TIMEFRAME = "5m"
SCAN_INTERVAL_SECONDS = 60  # Evaluates bars every 60s

# State memory to track active positions and entry prices
positions = {ticker: {"in_trade": False, "entry_price": 0.0} for ticker in WATCHLIST}


def send_telegram(text: str):
  """Sends formatted alerts directly to Telegram."""
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


def calculate_daily_pivots(ticker: str):
  """Calculates prior day's classic Pivot Point (P) and Pivot Low (S1)."""
  try:
    df_daily = yf.download(ticker, period="5d", interval="1d", progress=False)
    if len(df_daily) < 2:
      return None, None
    if isinstance(df_daily.columns, pd.MultiIndex):
      df_daily.columns = df_daily.columns.get_level_values(0)

    prev_day = df_daily.iloc[-2]
    pivot = float((prev_day["High"] + prev_day["Low"] + prev_day["Close"]) / 3.0)
    s1_low = float((2.0 * pivot) - prev_day["High"])
    return pivot, s1_low
  except Exception:
    return None, None


def scan_engine():
  for ticker in WATCHLIST:
    try:
      # Fetch recent 5m intraday data
      df = yf.download(ticker, period="3d", interval=TIMEFRAME, progress=False)
      if len(df) < 30:
        continue

      if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

      # 1. SuperTrend (10, 3) for Entry
      st1 = ta.supertrend(
          df["High"], df["Low"], df["Close"], length=10, multiplier=3.0
      )
      st1_col = "SUPERT_10_3.0"
      st1_dir_col = "SUPERTd_10_3.0"

      # 2. SuperTrend (7, 2) for Exit
      st2 = ta.supertrend(
          df["High"], df["Low"], df["Close"], length=7, multiplier=2.0
      )
      st2_dir_col = "SUPERTd_7_2.0"

      # 3. RSI 14
      rsi = ta.rsi(df["Close"], length=14)

      # 4. Daily Pivots
      pivot, s1_low = calculate_daily_pivots(ticker)
      if pivot is None:
        continue

      # Latest and previous bars
      curr = df.iloc[-1]
      prev = df.iloc[-2]

      curr_close = float(curr["Close"])
      curr_open = float(curr["Open"])
      st1_val = float(st1[st1_col].iloc[-1])
      st1_bullish = st1[st1_dir_col].iloc[-1] == 1
      st2_bearish_flip = (
          st2[st2_dir_col].iloc[-1] == -1 and st2[st2_dir_col].iloc[-2] == 1
      )
      rsi_prev = float(rsi.iloc[-2])

      pos = positions[ticker]
      display_name = (
          ticker.replace(".NS", "")
          .replace("^NSEI", "NIFTY 50")
          .replace("^NSEBANK", "BANK NIFTY")
          .replace("^BSESN", "SENSEX")
      )

      # -----------------------------------------------------------------
      # CALL / LONG ENTRY TRIGGER
      # -----------------------------------------------------------------
      is_green_candle = curr_close > curr_open
      above_st10_3 = curr_close > st1_val and st1_bullish
      above_pivot = curr_close > pivot
      rsi_confirmed = rsi_prev > 60.0

      if (
          not pos["in_trade"]
          and above_st10_3
          and above_pivot
          and rsi_confirmed
          and is_green_candle
      ):
        pos["in_trade"] = True
        pos["entry_price"] = curr_close

        msg = (
            f"🟢 *CALL / LONG ENTRY ALERT*\n\n"
            f"• *Symbol:* `{display_name}`\n"
            f"• *Price:* ₹{curr_close:,.2f}\n"
            f"• *SuperTrend (10,3):* ₹{st1_val:,.2f}\n"
            f"• *Daily Pivot:* ₹{pivot:,.2f}\n"
            f"• *Prior RSI:* {rsi_prev:.2f}\n"
            f"• *Action:* Buy Call / Position in Zerodha"
        )
        send_telegram(msg)

      # -----------------------------------------------------------------
      # EXIT TRIGGER (5% SL OR ST 7,2 FLIP OR S1 PIVOT BREAK)
      # -----------------------------------------------------------------
      elif pos["in_trade"]:
        entry_price = pos["entry_price"]
        sl_hit = curr_close <= (entry_price * 0.95)
        pivot_exit = curr_close < s1_low

        exit_triggered = False
        reason = ""

        if sl_hit:
          exit_triggered = True
          reason = "5% Fixed Stop Loss Hit"
        elif st2_bearish_flip:
          exit_triggered = True
          reason = "SuperTrend (7,2) Bearish Reversal"
        elif pivot_exit:
          exit_triggered = True
          reason = "Crossed Below Pivot Low (S1)"

        if exit_triggered:
          pos["in_trade"] = False
          pnl_pct = ((curr_close - entry_price) / entry_price) * 100.0

          msg = (
              f"🔴 *EXIT / SQUARE-OFF ALERT*\n\n"
              f"• *Symbol:* `{display_name}`\n"
              f"• *Exit Price:* ₹{curr_close:,.2f}\n"
              f"• *Entry Price:* ₹{entry_price:,.2f}\n"
              f"• *PnL:* {pnl_pct:+.2f}%\n"
              f"• *Reason:* {reason}\n"
              f"• *Action:* Square off in Zerodha"
          )
          send_telegram(msg)

      # Small sleep between requests to avoid rate limits across the full 50+ list
      time.sleep(0.1)

    except Exception:
      continue


# =====================================================================
# 3. BACKGROUND EXECUTION
# =====================================================================
if __name__ == "__main__":
    scan_engine()
