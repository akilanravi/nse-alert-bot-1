import argparse
import html
import json
import os
import re
import time
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf

IST = ZoneInfo("Asia/Kolkata")
STATE_FILE = "trade_state.json"

# ==============================================================================
# SETTINGS (change here)
# ==============================================================================
INITIAL_SL_PCT = 0.10        # initial stop loss on the UNDERLYING price (not option premium)
TRAIL_PCT = 0.10             # trailing stop, % below the peak price since entry
RSI_MIN = 60.0               # entry needs RSI(14) above this
CANDLE_MIN = 5               # candle size in minutes
MAX_DATA_AGE_MIN = 20        # ignore a symbol whose last completed candle is older than this
SCAN_START = dtime(9, 20)    # first completed 5m candle (09:15-09:20)
SCAN_END = dtime(15, 45)     # stop scanning after this
REPORT_AFTER = dtime(15, 35)
RANKING_LATE_MIN = 20        # still send a ranking if the run is up to this late
CHUNK = 50                   # symbols per yfinance download call

RANKING_SLOTS = [
    dtime(h, m) for h in range(9, 16) for m in (0, 30)
    if dtime(9, 30) <= dtime(h, m) <= dtime(15, 0)
]

# ==============================================================================
# SYMBOLS  (Yahoo Finance tickers). A ticker with no data is reported once a day.
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
    "SONACOMS.NS", "SUZLON.NS", "NHPC.NS", "SJVN.NS", "IRFC.NS", "RVNL.NS", "HUDCO.NS",
]

DISPLAY_NAMES = {
    "^NSEI": "NIFTY50",
    "^NSEBANK": "BANKNIFTY",
    "NIFTY_FIN_SERVICE.NS": "FINNIFTY",
    "NIFTY_MID_SELECT.NS": "MIDCPNIFTY",
}


def display_name(symbol: str) -> str:
    return DISPLAY_NAMES.get(symbol) or symbol.replace(".NS", "")


# ==============================================================================
# TELEGRAM
# ==============================================================================
def telegram_targets():
    targets = []
    for n in ("1", "2"):
        token = os.getenv(f"TELEGRAM_BOT_TOKEN_{n}", "").strip()
        chat = os.getenv(f"TELEGRAM_CHAT_ID_{n}", "").strip()
        if token and chat:
            targets.append((n, token, chat))
    return targets


def strip_tags(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def send_telegram(message: str, dry_run: bool = False) -> bool:
    """Send to every configured chat. Retries on rate-limit. Never prints the token."""
    if dry_run:
        print("[DRY-RUN ALERT]\n" + strip_tags(message) + "\n")
        return True
    targets = telegram_targets()
    if not targets:
        print("[WARN] No Telegram secrets configured - message not sent:")
        print(strip_tags(message))
        return False

    all_ok = True
    for n, token, chat in targets:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        sent = False
        for _ in range(3):
            try:
                r = requests.post(url, json=payload, timeout=15)
            except Exception as e:  # do not print e: it can contain the URL (= the token)
                print(f"[ERROR] Telegram recipient {n}: {type(e).__name__}")
                time.sleep(2)
                continue
            if r.status_code == 200:
                sent = True
                break
            if r.status_code == 429:
                try:
                    wait = int(r.json().get("parameters", {}).get("retry_after", 3))
                except Exception:
                    wait = 3
                time.sleep(min(wait + 1, 30))
                continue
            print(f"[ERROR] Telegram recipient {n}: HTTP {r.status_code} {r.text[:200]}")
            break
        if not sent:
            all_ok = False
            print(f"[ERROR] Telegram recipient {n}: message NOT delivered")
    return all_ok


# ==============================================================================
# DATA
# ==============================================================================
def _clean_frame(df: pd.DataFrame, now: datetime) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).lower() for c in df.columns]
    need = ["open", "high", "low", "close"]
    if any(c not in df.columns for c in need):
        return pd.DataFrame()
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df = df.dropna(subset=need)
    if df.empty:
        return df
    df["volume"] = df["volume"].fillna(0.0)
    idx = df.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    df.index = idx.tz_convert(IST)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    # drop the candle that is still forming
    if df.index[-1] + timedelta(minutes=CANDLE_MIN) > now:
        df = df.iloc[:-1]
    return df


def fetch_all(symbols, now: datetime):
    """Returns ({symbol: DataFrame}, [symbols with no data])."""
    data, missing = {}, []
    for i in range(0, len(symbols), CHUNK):
        chunk = symbols[i:i + CHUNK]
        raw = None
        try:
            raw = yf.download(
                chunk, period="5d", interval="5m", group_by="ticker",
                auto_adjust=False, progress=False, threads=True,
            )
        except Exception as e:
            print(f"[ERROR] download failed for chunk {i // CHUNK + 1}: {type(e).__name__}")
        for s in chunk:
            df = None
            try:
                if raw is not None and not raw.empty:
                    if isinstance(raw.columns, pd.MultiIndex):
                        if s in raw.columns.get_level_values(0):
                            df = raw[s]
                    elif len(chunk) == 1:
                        df = raw
                if df is not None:
                    df = _clean_frame(df, now)
            except Exception as e:
                print(f"[ERROR] {s}: {type(e).__name__}")
                df = None
            if df is None or len(df) < 40:
                missing.append(s)
            else:
                data[s] = df
    return data, missing


# ==============================================================================
# INDICATORS
# ==============================================================================
def supertrend(df: pd.DataFrame, period: int, multiplier: float) -> pd.Series:
    """1 = bullish, -1 = bearish."""
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    hl2 = (high + low) / 2
    upper = (hl2 + multiplier * atr).to_numpy()
    lower = (hl2 - multiplier * atr).to_numpy()
    c = close.to_numpy()
    n = len(c)
    fu, fl = upper.copy(), lower.copy()
    trend = np.ones(n, dtype=int)
    for i in range(1, n):
        fu[i] = upper[i] if (upper[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lower[i] if (lower[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        if trend[i - 1] == 1:
            trend[i] = -1 if c[i] < fl[i] else 1
        else:
            trend[i] = 1 if c[i] > fu[i] else -1
    return pd.Series(trend, index=df.index)


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    return 100 - (100 / (1 + gain / (loss + 1e-9)))


def bollinger_upper(series: pd.Series, length: int = 20, num_std: float = 2.0) -> pd.Series:
    return series.rolling(length).mean() + series.rolling(length).std() * num_std


def daily_pivot_r1(df: pd.DataFrame, today):
    """Classic DAILY pivot R1 from the previous session's high / low / close."""
    prior = df[df.index.date < today]
    if prior.empty:
        return None
    last_day = prior.index.date[-1]
    day = prior[prior.index.date == last_day]
    h, l, c = float(day["high"].max()), float(day["low"].min()), float(day["close"].iloc[-1])
    pivot = (h + l + c) / 3
    return 2 * pivot - l


def composite_strength(today_df: pd.DataFrame, prev_close: float, avg_daily_vol: float) -> dict:
    """-100..+100 score from TODAY's candles only (weights unchanged from your formula)."""
    ltp = float(today_df["close"].iloc[-1])
    day_high = float(today_df["high"].max())
    day_low = float(today_df["low"].min())
    day_open = float(today_df["open"].iloc[0])
    day_vol = float(today_df["volume"].sum())

    chg_pct = (ltp - prev_close) / prev_close * 100 if prev_close else 0.0
    v_mom = float(np.clip(chg_pct / 3.0, -1, 1)) if abs(chg_pct) > 0.5 else 0.0

    typical = (today_df["high"] + today_df["low"] + today_df["close"]) / 3
    if day_vol > 0:
        vwap = float((typical * today_df["volume"]).sum() / day_vol)
    else:  # indices have no volume on Yahoo
        vwap = float(typical.mean())
    v_vwap = float(np.clip(((ltp - vwap) / vwap * 100) / 1.5, -1, 1)) if vwap else 0.0

    # volume vs what is normal by this time of day (average of earlier sessions, pro-rated)
    sessions_fraction = min(1.0, len(today_df) / 75.0)
    expected = avg_daily_vol * sessions_fraction
    ratio = day_vol / expected if expected > 0 else 0.0
    v_vol = float(np.clip((ratio - 1.0) / 3.0, 0, 1) * np.sign(chg_pct)) if ratio > 1.5 else 0.0

    rng = day_high - day_low
    pos = (ltp - day_low) / (rng + 1e-9)
    v_range = (pos - 0.5) * 2.0

    if chg_pct > 0.1 and ltp >= day_open:
        v_trend = 1.0
    elif chg_pct < -0.1 and ltp < day_open:
        v_trend = -1.0
    else:
        v_trend = 0.0

    v_oi = 1.0 if chg_pct > 0.5 else (-1.0 if chg_pct < -0.5 else 0.0)  # proxy

    weights = [1.00, 0.95, 0.85, 0.60, 0.50, 0.35]
    values = [v_mom, v_vwap, v_vol, v_range, v_trend, v_oi]
    score = sum(w * v for w, v in zip(weights, values)) / sum(weights) * 100
    return {
        "score": round(score, 1),
        "ltp": round(ltp, 2),
        "chg_pct": round(chg_pct, 2),
        "vwap": round(vwap, 2),
    }


# ==============================================================================
# STATE
# ==============================================================================
def default_state() -> dict:
    return {
        "open_positions": {},
        "closed_trades": [],
        "last_exit_candle": {},
        "rankings": {"date": "", "slots": []},
        "report_sent": "",
        "missing_reported": "",
    }


def load_state() -> dict:
    state = default_state()
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                state.update(loaded)
        except Exception as e:
            print(f"[WARN] could not read {STATE_FILE}: {type(e).__name__} - starting fresh")
    if not isinstance(state.get("closed_trades"), list):
        state["closed_trades"] = []
    for key, default in default_state().items():
        if not isinstance(state.get(key), type(default)):
            state[key] = default
    state.pop("latest_scores", None)
    return state


def snapshot(state: dict) -> str:
    return json.dumps(state, sort_keys=True)


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ==============================================================================
# ALERT MESSAGES
# ==============================================================================
def h(text) -> str:
    return html.escape(str(text))


def entry_message(name, price, sl, rsi_v, bb_v, r1_v, candle_ts, now) -> str:
    return (
        f"🟢 <b>BULL ENTRY SIGNAL: {h(name)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"• Entry Price: ₹{price:.2f}\n"
        f"• Initial Stop Loss ({INITIAL_SL_PCT:.0%}): ₹{sl:.2f}\n"
        f"• Trailing SL: {TRAIL_PCT:.0%} below peak\n"
        f"• RSI (14): {rsi_v:.2f} (&gt; {RSI_MIN:.0f})\n"
        f"• Upper Bollinger: ₹{bb_v:.2f}\n"
        f"• Daily Pivot R1: ₹{r1_v:.2f}\n"
        f"• Supertrend (10, 2): Bullish\n"
        f"• Candle: {candle_ts.strftime('%H:%M')} (5M, closed)\n"
        f"• Time: {now.strftime('%H:%M:%S IST')}"
    )


def exit_message(name, reason, exit_price, pos, pnl, eff_sl, candle_ts, now) -> str:
    return (
        f"🔴 <b>EXIT SIGNAL: {h(name)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"• Reason: <b>{h(reason)}</b>\n"
        f"• Exit Price: ₹{exit_price:.2f}\n"
        f"• Entry Price: ₹{pos['entry_price']:.2f}\n"
        f"• PnL: <b>{pnl:+.2f}%</b>\n"
        f"• Active SL Level: ₹{eff_sl:.2f}\n"
        f"• Candle: {candle_ts.strftime('%H:%M')} (5M, closed)\n"
        f"• Time: {now.strftime('%H:%M:%S IST')}"
    )


# ==============================================================================
# PER-SYMBOL LOGIC
# ==============================================================================
def analyse(name: str, df: pd.DataFrame, now: datetime, state: dict, dry_run: bool):
    """Checks exit/entry on the last COMPLETED candle. Returns the strength score (or None)."""
    last_ts = df.index[-1]
    today = now.date()
    if last_ts.date() != today:
        return None
    age_min = (now - (last_ts + timedelta(minutes=CANDLE_MIN))).total_seconds() / 60
    if age_min > MAX_DATA_AGE_MIN:
        return None

    close = df["close"]
    st10 = supertrend(df, 10, 2.0)
    st7 = supertrend(df, 7, 2.0)
    rsi14 = rsi(close, 14)
    bb_up = bollinger_upper(close, 20, 2.0)
    r1 = daily_pivot_r1(df, today)

    cur_close = float(close.iloc[-1])
    cur_high = float(df["high"].iloc[-1])
    candle_key = last_ts.isoformat()

    # ---- strength score (today's candles only) ----
    today_df = df[df.index.date == today]
    prior = df[df.index.date < today]
    prev_close = float(prior["close"].iloc[-1]) if not prior.empty else float(today_df["open"].iloc[0])
    avg_vol = float(prior.groupby(prior.index.date)["volume"].sum().mean()) if not prior.empty else 0.0
    score = composite_strength(today_df, prev_close, avg_vol)

    positions = state["open_positions"]

    # ---- exits ----
    if name in positions:
        pos = positions[name]
        entry_ts = pd.Timestamp(pos["entry_ts"]) if pos.get("entry_ts") else None
        window = df[df.index > entry_ts] if entry_ts is not None else df.tail(1)
        peak_now = float(window["high"].max()) if not window.empty else cur_high
        pos["peak_price"] = max(float(pos["peak_price"]), peak_now)

        trailing = pos["peak_price"] * (1 - TRAIL_PCT)
        initial = float(pos["initial_sl"])
        eff_sl = max(initial, trailing)

        reason = None
        if cur_close <= eff_sl:
            reason = (
                f"Trailing stop hit ({TRAIL_PCT:.0%} below peak ₹{pos['peak_price']:.2f})"
                if trailing >= initial else f"Initial {INITIAL_SL_PCT:.0%} stop loss hit"
            )
        elif int(st7.iloc[-1]) == -1:
            reason = "Supertrend (7, 2) bearish reversal"

        if reason:
            pnl = (cur_close - pos["entry_price"]) / pos["entry_price"] * 100
            send_telegram(exit_message(name, reason, cur_close, pos, pnl, eff_sl, last_ts, now), dry_run)
            state["closed_trades"].append({
                "symbol": name,
                "entry_price": pos["entry_price"],
                "exit_price": cur_close,
                "pnl_pct": round(pnl, 3),
                "exit_reason": reason,
                "time": now.strftime("%Y-%m-%d %H:%M:%S"),
                "date": now.strftime("%Y-%m-%d"),
            })
            del positions[name]
            state["last_exit_candle"][name] = candle_key
        return score

    # ---- entries (long only) ----
    if state["last_exit_candle"].get(name) == candle_key:
        return score
    vals = [st10.iloc[-1], rsi14.iloc[-1], bb_up.iloc[-1], r1]
    if any(v is None or pd.isna(v) for v in vals):
        return score

    if (
        int(st10.iloc[-1]) == 1
        and rsi14.iloc[-1] > RSI_MIN
        and cur_close > bb_up.iloc[-1]
        and cur_close > r1
    ):
        sl = cur_close * (1 - INITIAL_SL_PCT)
        positions[name] = {
            "entry_price": cur_close,
            "initial_sl": sl,
            "peak_price": cur_high,
            "entry_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "entry_ts": candle_key,
        }
        send_telegram(
            entry_message(name, cur_close, sl, float(rsi14.iloc[-1]), float(bb_up.iloc[-1]),
                          float(r1), last_ts, now),
            dry_run,
        )
    return score


# ==============================================================================
# RANKINGS & REPORT
# ==============================================================================
def maybe_send_rankings(now: datetime, scores: dict, state: dict, dry_run: bool):
    if len(scores) < 10:
        return
    slot_label = None
    if dry_run:
        slot_label = "dry-run"
    else:
        due = [s for s in RANKING_SLOTS if s <= now.time()]
        if not due:
            return
        slot = due[-1]
        slot_dt = now.replace(hour=slot.hour, minute=slot.minute, second=0, microsecond=0)
        if (now - slot_dt).total_seconds() / 60 > RANKING_LATE_MIN:
            return
        slot_label = slot.strftime("%H:%M")
        today_s = now.strftime("%Y-%m-%d")
        if state["rankings"].get("date") != today_s:
            state["rankings"] = {"date": today_s, "slots": []}
        if slot_label in state["rankings"]["slots"]:
            return

    ranked = sorted(scores.items(), key=lambda kv: kv[1]["score"], reverse=True)
    top5, bottom5 = ranked[:5], ranked[-5:]
    lines = [
        "📊 <b>LIVE 30M MOMENTUM RANKINGS</b>",
        f"⏰ <b>Time:</b> {now.strftime('%H:%M IST')}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🟢 <b>TOP 5 STRONGEST BULLS</b>",
    ]
    for i, (sym, d) in enumerate(top5, 1):
        lines.append(f"{i}. <code>{h(sym)}</code>: <b>{d['score']:+.1f} pts</b> | CMP: ₹{d['ltp']} ({d['chg_pct']:+.2f}%) | VWAP: ₹{d['vwap']}")
    lines.append("\n🔴 <b>BOTTOM 5 STRONGEST BEARS</b>")
    for i, (sym, d) in enumerate(reversed(bottom5), 1):
        lines.append(f"{i}. <code>{h(sym)}</code>: <b>{d['score']:+.1f} pts</b> | CMP: ₹{d['ltp']} ({d['chg_pct']:+.2f}%) | VWAP: ₹{d['vwap']}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━")

    ok = send_telegram("\n".join(lines), dry_run)
    if ok and not dry_run:
        state["rankings"]["slots"].append(slot_label)


def send_report(state: dict, now: datetime, dry_run: bool = False) -> bool:
    today_s = now.strftime("%Y-%m-%d")
    closed = state["closed_trades"]
    todays = [t for t in closed if str(t.get("date") or t.get("time", ""))[:10] == today_s]
    wins = [t for t in todays if t["pnl_pct"] > 0]
    n = len(todays)
    win_rate = len(wins) / n * 100 if n else 0.0
    avg = float(np.mean([t["pnl_pct"] for t in todays])) if n else 0.0
    open_pos = state["open_positions"]

    all_n = len(closed)
    all_wins = len([t for t in closed if t["pnl_pct"] > 0])

    lines = [
        "📊 <b>EOD 5M SCANNER REPORT</b>",
        f"📅 Date: {now.strftime('%d-%b-%Y')}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"• Trades closed today: <b>{n}</b>",
        f"• Win rate today: <b>{win_rate:.1f}%</b> ({len(wins)}/{n})",
        f"• Average return today: <b>{avg:+.2f}%</b>",
        f"• Open positions: <b>{len(open_pos)}</b>",
        f"• All-time: {all_n} trades, {(all_wins / all_n * 100 if all_n else 0):.1f}% win rate",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    if todays:
        lines.append("\n<b>Closed trades today:</b>")
        for t in todays[-15:]:
            lines.append(f"• <code>{h(t['symbol'])}</code>: {t['pnl_pct']:+.2f}% ({h(t['exit_reason'])})")
    if open_pos:
        lines.append("\n<b>Open positions carrying over:</b>")
        for sym, p in open_pos.items():
            lines.append(f"• <code>{h(sym)}</code>: Entry ₹{p['entry_price']:.2f} | Peak ₹{p['peak_price']:.2f}")
    return send_telegram("\n".join(lines), dry_run)


# ==============================================================================
# RUN
# ==============================================================================
def run_once(dry_run: bool = False, now: datetime = None):
    now = now or datetime.now(IST)
    if not dry_run:
        if now.weekday() >= 5:
            print("Weekend - nothing to do.")
            return
        if now.time() < SCAN_START:
            print(f"{now:%H:%M} IST is before {SCAN_START:%H:%M} - nothing to do.")
            return

    state = load_state()
    before = snapshot(state)
    symbols = list(dict.fromkeys(RAW_SYMBOLS))
    data, missing = fetch_all(symbols, now)
    print(f"Downloaded {len(data)} symbols, {len(missing)} without data.")

    # dry-run: behave as if it is just after the newest candle closed
    if dry_run and data:
        newest = max(df.index[-1] for df in data.values())
        now = newest + timedelta(minutes=CANDLE_MIN + 1)

    today = now.date()
    fresh = sum(1 for df in data.values() if df.index[-1].date() == today)
    if fresh < 10:
        print("No candles for today (holiday, or Yahoo returned nothing) - nothing to do.")
        if missing and len(missing) > len(symbols) // 2 and not dry_run:
            print("[WARN] most symbols returned no data - Yahoo may be blocking this runner.")
        if snapshot(state) != before or not os.path.exists(STATE_FILE):
            if not dry_run:
                save_state(state)
        return

    today_s = now.strftime("%Y-%m-%d")
    if missing and state["missing_reported"] != today_s:
        names = ", ".join(display_name(s) for s in missing[:40])
        extra = f" (+{len(missing) - 40} more)" if len(missing) > 40 else ""
        ok = send_telegram(
            f"⚠️ <b>No Yahoo data for {len(missing)} symbol(s)</b>\n{h(names)}{h(extra)}\n"
            f"Wrong/old ticker or a temporary Yahoo problem.", dry_run)
        if ok and not dry_run:
            state["missing_reported"] = today_s

    scores = {}
    if dry_run or now.time() <= SCAN_END:
        for sym, df in data.items():
            name = display_name(sym)
            try:
                score = analyse(name, df, now, state, dry_run)
            except Exception as e:
                print(f"[ERROR] {name}: {type(e).__name__}: {e}")
                continue
            if score:
                scores[name] = score
        maybe_send_rankings(now, scores, state, dry_run)

    if dry_run or (now.time() >= REPORT_AFTER and state["report_sent"] != today_s):
        if send_report(state, now, dry_run) and not dry_run:
            state["report_sent"] = today_s

    if not dry_run and (snapshot(state) != before or not os.path.exists(STATE_FILE)):
        save_state(state)
        print("State saved.")
    print(f"Done. Open positions: {len(state['open_positions'])}")


def main():
    ap = argparse.ArgumentParser(description="NSE 5m alert scanner")
    ap.add_argument("--once", action="store_true", help="one scan run (used by the workflow)")
    ap.add_argument("--dry-run", action="store_true", help="test mode: print alerts, send nothing, save nothing")
    ap.add_argument("--report", action="store_true", help="send the end-of-day report now")
    ap.add_argument("--test-telegram", action="store_true", help="send a test message")
    args = ap.parse_args()

    if args.test_telegram:
        ok = send_telegram("✅ <b>Scanner test</b>\nTelegram connection works.")
        print("Test message delivered." if ok else "Test message FAILED - check secrets / chat ids.")
        return
    if args.report:
        send_report(load_state(), datetime.now(IST))
        return
    if args.once or args.dry_run:
        run_once(dry_run=args.dry_run)
        return
    ap.print_help()


if __name__ == "__main__":
    main()
