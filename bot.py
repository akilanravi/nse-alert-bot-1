    direction = pd.Series(0, index=df.index, dtype=int)
    for i in range(1, len(df)):
        if pd.isna(atr.iloc[i]):
            continue
        if pd.isna(upper.iloc[i-1]): upper.iloc[i-1] = basic_upper.iloc[i-1]
        if pd.isna(lower.iloc[i-1]): lower.iloc[i-1] = basic_lower.iloc[i-1]
        upper.iloc[i] = basic_upper.iloc[i] if (basic_upper.iloc[i] < upper.iloc[i-1] or close.iloc[i-1] > upper.iloc[i-1]) else upper.iloc[i-1]
        lower.iloc[i] = basic_lower.iloc[i] if (basic_lower.iloc[i] > lower.iloc[i-1] or close.iloc[i-1] < lower.iloc[i-1]) else lower.iloc[i-1]
        prev_dir = direction.iloc[i-1] or 1
        if prev_dir == 1:
            direction.iloc[i] = -1 if close.iloc[i] < lower.iloc[i] else 1
        else:
            direction.iloc[i] = 1 if close.iloc[i] > upper.iloc[i] else -1
        st.iloc[i] = lower.iloc[i] if direction.iloc[i] == 1 else upper.iloc[i]
    return st, direction


def daily_pivots(ticker: str):
    d = yf.download(ticker, period="10d", interval="1d", progress=False, auto_adjust=False, threads=False)
    d = normalize_columns(d).dropna(subset=["High", "Low", "Close"])
    if len(d) < 2:
        return None
    # Previous completed daily candle (latest daily row may be today's partial candle).
    prev = d.iloc[-2]
    h, l, c = float(prev.High), float(prev.Low), float(prev.Close)
    p = (h+l+c)/3
    r1 = 2*p-l
    # Classic central-range midpoint often called M3: (P + R1)/2.
    m3 = (p+r1)/2
    s1 = 2*p-h
    return p, m3, s1


def option_strikes(price: float, step: int, bullish: bool):
    atm = int(math.floor(price/step + 0.5) * step)
    # One strike ITM: call ITM below ATM; put ITM above ATM.
    itm = atm-step if bullish else atm+step
    return atm, itm


def load_state():
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"last_alert": {}}


def scan():
    now = datetime.now(IST)
    if not market_open_now(now):
        print(f"Outside scan window: {now:%Y-%m-%d %H:%M:%S %Z}; no market scan.")
        return
    state = load_state()
    state.setdefault("last_alert", {})
    sent = 0
    for ticker, (name, step) in WATCHLIST.items():
        try:
            df = yf.download(ticker, period="5d", interval="5m", progress=False, auto_adjust=False, threads=False)
            df = normalize_columns(df).dropna(subset=["Open", "High", "Low", "Close"])
            if len(df) < 50:
                print(f"SKIP {name}: insufficient 5-minute data ({len(df)} rows)")
                continue
            # Exclude the newest candle because it may still be forming.
            df = df.iloc[:-1].copy()
            if len(df) < 40: continue
            pvt = daily_pivots(ticker)
            if pvt is None:
                print(f"SKIP {name}: daily pivot unavailable")
                continue
            pivot, m3, s1 = pvt
            st1, dir1 = supertrend(df, 10, 3.0)
            st2, dir2 = supertrend(df, 7, 2.0)
            rs = rsi(df.Close.astype(float), 14)
            i = -1
            close, op = float(df.Close.iloc[i]), float(df.Open.iloc[i])
            rsi_now = float(rs.iloc[i]) if pd.notna(rs.iloc[i]) else float("nan")
            if not np.isfinite(rsi_now) or pd.isna(st1.iloc[i]) or pd.isna(st2.iloc[i]):
                print(f"SKIP {name}: indicators not ready")
                continue
            bull = close > float(st1.iloc[i]) and dir1.iloc[i] == 1 and close > m3 and rsi_now >= 60 and close > op
            bear = close < float(st1.iloc[i]) and dir1.iloc[i] == -1 and close < m3 and rsi_now <= 40 and close < op
            # Exit / reversal alerts are signal-only; not broker position tracking.
            exit_bull = dir2.iloc[i] == -1 and dir2.iloc[i-1] == 1
            exit_bear = dir2.iloc[i] == 1 and dir2.iloc[i-1] == -1
            candle_id = str(df.index[i])
            side = "CALL" if bull else "PUT" if bear else ""
            if not side and not (exit_bull or exit_bear):
                continue
            event = side or ("EXIT CALL BIAS" if exit_bull else "EXIT PUT BIAS")
            dedupe_key = f"{ticker}|{event}"
            if state["last_alert"].get(dedupe_key) == candle_id:
                continue
            if side:
                atm, itm = option_strikes(close, step, side == "CALL")
                emoji = "🟢" if side == "CALL" else "🔴"
                msg = (f"{emoji} {side} SETUP — UNDERLYING ALERT\n"
                       f"Symbol: {name}\nUnderlying close: {close:.2f}\n"
                       f"RSI(14): {rsi_now:.1f}\nSuperTrend(10,3): {float(st1.iloc[i]):.2f}\n"
                       f"Daily Pivot: {pivot:.2f}\nMid-pivot M3: {m3:.2f}\nS1: {s1:.2f}\n"
                       f"Candidate ATM strike: {atm}\nCandidate 1-strike ITM: {itm}\n"
                       f"5m candle: {candle_id}\nData: Yahoo Finance; may be delayed/incomplete.\n"
                       "Confirm option liquidity, bid-ask spread, expiry and live price in broker before any trade.")
            else:
                msg = (f"⚠️ {event}\nSymbol: {name}\nUnderlying close: {close:.2f}\n"
                       f"SuperTrend(7,2) reversal detected. This is an underlying bias alert, not a confirmed broker-position exit.\n"
                       f"5m candle: {candle_id}")
            send_telegram(msg)
            state["last_alert"][dedupe_key] = candle_id
            sent += 1
            print(f"ALERT {name}: {event} at {close}")
        except Exception as exc:
            print(f"ERROR {ticker}: {type(exc).__name__}: {exc}", file=sys.stderr)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"Scan complete at {now:%H:%M:%S} IST; alerts sent: {sent}")


if __name__ == "__main__":
    if not TOKEN or not CHAT_ID:
        print("ERROR: Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID as GitHub Actions secrets.", file=sys.stderr)
        sys.exit(2)
    if os.getenv("TEST_TELEGRAM", "0") == "1":
        send_telegram("✅ F&O scanner Telegram connection test successful. This is a test only.")
    else:
        scan()
