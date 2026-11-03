import os
import sys
import json
import time
import argparse
from datetime import datetime, time as dtime
import pytz
import requests
import pandas as pd
import numpy as np
import yfinance as yf

# ==============================================================================
# 1. TIMEZONE & TELEGRAM CONFIGURATION
# ==============================================================================
IST = pytz.timezone('Asia/Kolkata')

TELEGRAM_BOT_CONFIGS = [
    {
        "token": os.getenv("TELEGRAM_BOT_TOKEN_1", "8764996383:AAE_vevTjJ76zfK3g3rYGgsZB3_EtkbvUms"),
        "chat_id": os.getenv("TELEGRAM_CHAT_ID_1", "8865083462")
    },
    {
        "token": os.getenv("TELEGRAM_BOT_TOKEN_2", "8721771664:AAFcyCX2TP2KsUrIQoh6utZvHjbLQt8vD-k"),
        "chat_id": os.getenv("TELEGRAM_CHAT_ID_2", "846124589")
    }
]

def send_telegram_alert(message: str):
    """Broadcasts messages to both configured Telegram channels."""
    for cfg in TELEGRAM_BOT_CONFIGS:
        token = cfg.get("token")
        chat_id = cfg.get("chat_id")
        if not token or not chat_id:
            continue
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
        try:
            requests.post(url, json=payload, timeout=8)
        except Exception as e:
            print(f"[ERROR] Failed to send Telegram message to {chat_id}: {e}")

# ==============================================================================
# 2. 210 F&O SYMBOLS SPLIT INTO GROUPS OF 10
# ==============================================================================
RAW_SYMBOLS = [
    "^NSEI", "^NSEBANK", "NIFTY_FIN_SERVICE.NS", "NIFTY_MID_SELECT.NS",
    "AARTIIND.NS", "ABB.NS", "ABBOTINDIA.NS", "ABCAPITAL.NS", "ABFRL.NS", "ACC.NS",
    "ADANIENT.NS", "ADANIPORTS.NS", "ALKEM.NS", "AMBUJACEM.NS", "APOLLOHOSP.NS",
    "APOLLOTYRE.NS", "ASHOKLEY.NS", "ASIANPAINT.NS", "ASTRAL.NS", "ATUL.NS",
    "AUBANK.NS", "AUROPHARMA.NS", "AXISBANK.NS", "BAJAJ-AUTO.NS", "BAJAJFINSV.NS",
    "BAJFINANCE.NS", "BALKRISIND.NS", "BALRAMCHIN.NS", "BANDHANBNK.NS", "BANKBARODA.NS",
    "BATAINDIA.NS", "BEL.NS", "BERGEPAINT.NS", "BHARATFORG.NS", "BHARTIARTL.NS",
    "BHEL.NS", "BIOCON.NS", "BOSCHLTD.NS", "BPCL.NS", "BRITANNIA.NS", "BSOFT.NS",
    "CANBK.NS", "CANFINHOME.NS", "CHAMBLFERT.NS", "CHOLAFIN.NS", "CIPLA.NS",
    "COALINDIA.NS", "COFORGE.NS", "COLPAL.NS", "CONCOR.NS", "COROMANDEL.NS",
    "CROMPTON.NS", "CUB.NS", "CUMMINSIND.NS", "DABUR.NS", "DALBHARAT.NS",
    "DEEPAKNTR.NS", "DELHIVERY.NS", "DIVISLAB.NS", "DIXON.NS", "DLF.NS", "DRREDDY.NS",
    "EICHERMOT.NS", "ESCORTS.NS", "EXIDEIND.NS", "FEDERALBNK.NS", "GAIL.NS",
    "GLENMARK.NS", "GMRINFRA.NS", "GNFC.NS", "GODREJCP.NS", "GODREJPROP.NS",
    "GRANULES.NS", "GRASIM.NS", "GUJGASLTD.NS", "HAL.NS", "HAVELLS.NS", "HCLTECH.NS",
    "HDFCAMC.NS", "HDFCBANK.NS", "HDFCLIFE.NS", "HEROMOTOCO.NS", "HINDALCO.NS",
    "HINDCOPPER.NS", "HINDPETRO.NS", "HINDUNILVR.NS", "ICICIBANK.NS", "ICICIGI.NS",
    "ICICIPRULI.NS", "IDEA.NS", "IDFCFIRSTB.NS", "IEX.NS", "IGL.NS", "INDHOTEL.NS",
    "INDIACEM.NS", "INDIAMART.NS", "INDIGO.NS", "INDUSINDBK.NS", "INDUSTOWER.NS",
    "INFY.NS", "IOC.NS", "IPCALAB.NS", "IRCTC.NS", "ITC.NS", "JINDALSTEL.NS",
    "JKCEMENT.NS", "JSWSTEEL.NS", "JUBLFOOD.NS", "KALYANKJIL.NS", "KOTAKBANK.NS",
    "LALPATHLAB.NS", "LAURUSLABS.NS", "LICHSGFIN.NS", "LICI.NS", "LT.NS", "LTF.NS",
    "LTIM.NS", "LTTS.NS", "LUPIN.NS", "M&M.NS", "M&MFIN.NS", "MANAPPURAM.NS",
    "MARICO.NS", "MARUTI.NS", "MCX.NS", "METROPOLIS.NS", "MFSL.NS", "MGL.NS",
    "MOTHERSON.NS", "MPHASIS.NS", "MRF.NS", "MUTHOOTFIN.NS", "NATIONALUM.NS",
    "NAUKRI.NS", "NAVINFLUOR.NS", "NESTLEIND.NS", "NMDC.NS", "NTPC.NS", "OBEROIRLTY.NS",
    "OFSS.NS", "ONGC.NS", "PAGEIND.NS", "PEL.NS", "PERSISTENT.NS", "PETRONET.NS",
    "PFC.NS", "PIDILITIND.NS", "PIIND.NS", "PNB.NS", "POLYCAB.NS", "POONAWALLA.NS",
    "POWERGRID.NS", "PVRINOX.NS", "RAMCOCEM.NS", "RBLBANK.NS", "RECLTD.NS",
    "RELIANCE.NS", "SAIL.NS", "SBICARD.NS", "SBILIFE.NS", "SBIN.NS", "SHREECEM.NS",
    "SHRIRAMFIN.NS", "SIEMENS.NS", "SRF.NS", "SUNPHARMA.NS", "SUNTV.NS", "SYNGENE.NS",
    "TATACHEM.NS", "TATACOMM.NS", "TATACONSUM.NS", "TATAMOTORS.NS", "TATAPOWER.NS",
    "TATASTEEL.NS", "TCS.NS", "TECHM.NS", "TITAN.NS", "TORNTPHARM.NS", "TORNTPOWER.NS",
    "TRENT.NS", "TVSMOTOR.NS", "UBL.NS", "ULTRACEMCO.NS", "UNIONBANK.NS", "UPL.NS",
    "VBL.NS", "VEDL.NS", "VOLTAS.NS", "WIPRO.NS", "ZYDUSLIFE.NS", "BSE.NS", "CDSL.NS",
    "ANGELONE.NS", "KEI.NS", "PRESTIGE.NS", "POLICYBZR.NS", "MAXHEALTH.NS",
    "SONACOMS.NS", "SUZLON.NS", "NHPC.NS", "SJVN.NS", "IRFC.NS", "RVNL.NS", "HUDCO.NS"
]

CHUNK_SIZE = 10
SYMBOL_GROUPS = {
    f"group_{i+1}": RAW_SYMBOLS[i * CHUNK_SIZE:(i + 1) * CHUNK_SIZE]
    for i in range((len(RAW_SYMBOLS) + CHUNK_SIZE - 1) // CHUNK_SIZE)
}

# ==============================================================================
# 3. INDICATOR FORMULAS
# ==============================================================================
def calculate_supertrend(df: pd.DataFrame, period: int, multiplier: float) -> pd.Series:
    high, low, close = df['high'], df['low'], df['close']
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, adjust=False).mean()

    hl2 = (high + low) / 2
    upper = hl2 + (multiplier * atr)
    lower = hl2 - (multiplier * atr)

    final_upper = pd.Series(0.0, index=df.index)
    final_lower = pd.Series(0.0, index=df.index)
    trend = pd.Series(1, index=df.index)

    for i in range(1, len(df)):
        final_upper.iloc[i] = upper.iloc[i] if upper.iloc[i] < final_upper.iloc[i-1] or close.iloc[i-1] > final_upper.iloc[i-1] else final_upper.iloc[i-1]
        final_lower.iloc[i] = lower.iloc[i] if lower.iloc[i] > final_lower.iloc[i-1] or close.iloc[i-1] < final_lower.iloc[i-1] else final_lower.iloc[i-1]

        if trend.iloc[i-1] == 1:
            trend.iloc[i] = -1 if close.iloc[i] < final_lower.iloc[i] else 1
        else:
            trend.iloc[i] = 1 if close.iloc[i] > final_upper.iloc[i] else -1

    return trend  # 1 = Bullish, -1 = Bearish

def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))

def calculate_bollinger_upper(series: pd.Series, length: int = 20, num_std: float = 2.0) -> pd.Series:
    return series.rolling(length).mean() + (series.rolling(length).std() * num_std)

def calculate_pivot_r1(df: pd.DataFrame) -> pd.Series:
    pivot = (df['high'].shift(1) + df['low'].shift(1) + df['close'].shift(1)) / 3
    return (2 * pivot) - df['low'].shift(1)

# ==============================================================================
# 4. PERSISTENT STATE MANAGEMENT
# ==============================================================================
def get_state_file(group_name: str) -> str:
    return f"trade_state_{group_name}.json"

def load_group_state(group_name: str) -> dict:
    fname = get_state_file(group_name)
    if os.path.exists(fname):
        try:
            with open(fname, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {"open_positions": {}, "closed_trades": []}

def save_group_state(group_name: str, state: dict):
    fname = get_state_file(group_name)
    with open(fname, 'w') as f:
        json.dump(state, f, indent=2)

# ==============================================================================
# 5. CONTINUOUS 5-MINUTE SCANNER (09:30 - 15:30 IST)
# ==============================================================================
def run_sector_scanner(group_name: str):
    symbols = SYMBOL_GROUPS.get(group_name, [])
    if not symbols:
        print(f"Group '{group_name}' contains no symbols.")
        return

    print(f"Starting continuous scanner for {group_name} ({len(symbols)} symbols)...")
    send_telegram_alert(
        f"🟢 *5M Scanner Active: {group_name}*\n"
        f"• Stocks Tracked: {len(symbols)}\n"
        f"• Session: 09:30 to 15:30 IST\n"
        f"• Timeframe: 5 Minutes"
    )

    state = load_group_state(group_name)
    start_time = dtime(9, 30)
    end_time = dtime(15, 30)

    while True:
        now_ist = datetime.now(IST)
        curr_time = now_ist.time()

        # Pre-market wait
        if curr_time < start_time:
            time.sleep(15)
            continue

        # Market close check
        if curr_time >= end_time:
            print(f"[{now_ist.strftime('%H:%M:%S')}] 15:30 IST reached. Market session concluded.")
            break

        for symbol in symbols:
            try:
                # 5-minute candle data
                ticker = yf.Ticker(symbol)
                df = ticker.history(period="5d", interval="5m")
                if df.empty or len(df) < 30:
                    continue

                df.columns = [c.lower() for c in df.columns]

                # Indicators on 5M timeframe
                st_10_2 = calculate_supertrend(df, period=10, multiplier=2.0)
                st_7_2 = calculate_supertrend(df, period=7, multiplier=2.0)
                rsi = calculate_rsi(df['close'], period=14)
                bb_upper = calculate_bollinger_upper(df['close'], length=20, num_std=2.0)
                r1 = calculate_pivot_r1(df)

                curr_close = float(df['close'].iloc[-1])
                curr_high = float(df['high'].iloc[-1])
                curr_st_7_2 = int(st_7_2.iloc[-1])
                clean_sym = symbol.replace(".NS", "")

                # ------------------------------------------------------
                # CHECK EXITS & BEARISH REVERSAL MESSAGE
                # ------------------------------------------------------
                if clean_sym in state["open_positions"]:
                    pos = state["open_positions"][clean_sym]
                    pos["peak_price"] = max(pos["peak_price"], curr_high)
                    trailing_sl = pos["peak_price"] * 0.90
                    initial_sl = pos["initial_sl"]
                    effective_sl = max(initial_sl, trailing_sl)

                    exit_triggered = False
                    exit_reason = ""

                    if curr_close <= effective_sl:
                        exit_triggered = True
                        exit_reason = f"Trailing Stop Loss Hit (10% from Peak ₹{pos['peak_price']:.2f})" if effective_sl == trailing_sl else "Initial 10% Stop Loss Hit"
                    elif curr_st_7_2 == -1:
                        exit_triggered = True
                        exit_reason = "Supertrend (7, 2) Bearish Reversal"

                    if exit_triggered:
                        pnl = ((curr_close - pos['entry_price']) / pos['entry_price']) * 100
                        bear_msg = (
                            f"🔴 *BEAR REVERSAL / EXIT SIGNAL: {clean_sym}*\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"• Reason: *{exit_reason}*\n"
                            f"• Exit Price: ₹{curr_close:.2f}\n"
                            f"• Entry Price: ₹{pos['entry_price']:.2f}\n"
                            f"• PnL: *{pnl:+.2f}%*\n"
                            f"• Active SL Level: ₹{effective_sl:.2f}\n"
                            f"• Timeframe: 5M\n"
                            f"• Time: {now_ist.strftime('%H:%M:%S IST')}"
                        )
                        send_telegram_alert(bear_msg)

                        state["closed_trades"].append({
                            "symbol": clean_sym,
                            "entry_price": pos["entry_price"],
                            "exit_price": curr_close,
                            "pnl_pct": pnl,
                            "exit_reason": exit_reason,
                            "time": now_ist.strftime('%Y-%m-%d %H:%M:%S')
                        })
                        del state["open_positions"][clean_sym]
                        save_group_state(group_name, state)
                    continue

                # ------------------------------------------------------
                # CHECK STRATEGY 1 ENTRY & BULL MESSAGE
                # ------------------------------------------------------
                cond_st10 = (st_10_2.iloc[-1] == 1)
                cond_rsi = (rsi.iloc[-1] > 60)
                cond_bb = (curr_close > bb_upper.iloc[-1])
                cond_r1 = (curr_close > r1.iloc[-1])

                if cond_st10 and cond_rsi and cond_bb and cond_r1:
                    initial_sl = curr_close * 0.90
                    state["open_positions"][clean_sym] = {
                        "entry_price": curr_close,
                        "initial_sl": initial_sl,
                        "peak_price": curr_high,
                        "entry_time": now_ist.strftime('%Y-%m-%d %H:%M:%S')
                    }
                    save_group_state(group_name, state)

                    bull_msg = (
                        f"🟢 *BULL ENTRY SIGNAL: {clean_sym}*\n"
                        f"━━━━━━━━━━━━━━━━━━━\n"
                        f"• Entry Price: ₹{curr_close:.2f}\n"
                        f"• Initial Stop Loss (10%): ₹{initial_sl:.2f}\n"
                        f"• Trailing SL: 10% Ratchet\n"
                        f"• RSI (14): {rsi.iloc[-1]:.2f} (> 60)\n"
                        f"• Upper Bollinger: ₹{bb_upper.iloc[-1]:.2f}\n"
                        f"• Pivot R1: ₹{r1.iloc[-1]:.2f}\n"
                        f"• Supertrend (10, 2): Bullish\n"
                        f"• Timeframe: 5M\n"
                        f"• Time: {now_ist.strftime('%H:%M:%S IST')}"
                    )
                    send_telegram_alert(bull_msg)

            except Exception as e:
                print(f"Error checking {symbol}: {e}")

        # Sync polling interval with 5-minute bar updates
        time.sleep(60)

# ==============================================================================
# 6. END-OF-DAY PERFORMANCE REPORT
# ==============================================================================
def generate_eod_report():
    """Compiles all trade state records into an EOD summary dispatch."""
    now_ist = datetime.now(IST)
    all_closed = []
    all_open = []

    for f in os.listdir("."):
        if f.startswith("trade_state_") and f.endswith(".json"):
            try:
                with open(f, 'r') as fp:
                    data = json.load(fp)
                    all_closed.extend(data.get("closed_trades", []))
                    for sym, pos in data.get("open_positions", {}).items():
                        all_open.append({"symbol": sym, **pos})
            except Exception:
                pass

    total_trades = len(all_closed)
    wins = [t for t in all_closed if t["pnl_pct"] > 0]
    win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0.0
    avg_pnl = np.mean([t["pnl_pct"] for t in all_closed]) if total_trades > 0 else 0.0

    report_lines = [
        f"📊 *EOD 5M SCANNER REPORT*",
        f"📅 Date: {now_ist.strftime('%d-%b-%Y')}",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"• Total Trades: *{total_trades}*",
        f"• Win Rate: *{win_rate:.1f}%* ({len(wins)}/{total_trades})",
        f"• Average Return: *{avg_pnl:+.2f}%*",
        f"• Open Active Positions: *{len(all_open)}*",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ]

    if all_closed:
        report_lines.append("\n*Closed Trades Today:*")
        for t in all_closed[-10:]:
            report_lines.append(f"• `{t['symbol']}`: {t['pnl_pct']:+.2f}% ({t['exit_reason']})")

    if all_open:
        report_lines.append("\n*Open Positions Carrying Over:*")
        for pos in all_open:
            report_lines.append(f"• `{pos['symbol']}`: Entry ₹{pos['entry_price']:.2f} | Peak ₹{pos['peak_price']:.2f}")

    send_telegram_alert("\n".join(report_lines))
    print("EOD report sent successfully.")

# ==============================================================================
# 7. EXECUTION ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", type=str, help="Group name (e.g. group_1)")
    parser.add_argument("--report", action="store_true", help="Generate EOD summary report")
    args = parser.parse_args()

    if args.report:
        generate_eod_report()
    elif args.group:
        run_sector_scanner(args.group)
    else:
        print("Please specify --group <group_name> or --report")
