"""
HT ADVANCED BTST & SWING OPTIONS SCANNER — FREE PROTOTYPE
Manual trading only. Uses Yahoo Finance data via yfinance.
IMPORTANT:
- Free Yahoo Finance data can be delayed, incomplete, or unavailable.
- This prototype does NOT fetch a live NSE option chain.
- Verify CE/PE, strike, expiry, premium, bid/ask spread and liquidity in Dhan
  before placing any order. It never places orders.
"""

import math
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import yfinance as yf

IST = ZoneInfo("Asia/Kolkata")

# Common NSE F&O stock universe. This is a starter universe, not a guarantee
# that every symbol is currently in the NSE F&O segment. Review/update it.
FO_STOCKS = [
    "ABB", "ABCAPITAL", "ADANIENT", "ADANIPORTS", "ALKEM", "AMBUJACEM",
    "ANGELONE", "APLAPOLLO", "APOLLOHOSP", "ASHOKLEY", "ASIANPAINT",
    "ASTRAL", "ATGL", "AUBANK", "AUROPHARMA", "AXISBANK", "BAJAJ-AUTO",
    "BAJAJFINSV", "BAJFINANCE", "BALKRISIND", "BANDHANBNK", "BANKBARODA",
    "BEL", "BHARATFORG", "BHARTIARTL", "BHEL", "BIOCON", "BOSCHLTD",
    "BPCL", "BRITANNIA", "BSE", "CANBK", "CANFINHOME", "CHAMBLFERT",
    "CHOLAFIN", "CIPLA", "COALINDIA", "COFORGE", "COLPAL", "CONCOR",
    "CROMPTON", "CUMMINSIND", "DABUR", "DALBHARAT", "DEEPAKNTR",
    "DELHIVERY", "DIVISLAB", "DIXON", "DLF", "DRREDDY", "EICHERMOT",
    "ESCORTS", "EXIDEIND", "FEDERALBNK", "GAIL", "GLENMARK", "GMRAIRPORT",
    "GODREJCP", "GODREJPROP", "GRANULES", "GRASIM", "HAL", "HAVELLS",
    "HCLTECH", "HDFCAMC", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO",
    "HFCL", "HINDALCO", "HINDCOPPER", "HINDPETRO", "HINDUNILVR",
    "HUDCO", "ICICIBANK", "ICICIGI", "ICICIPRULI", "IDEA", "IDFCFIRSTB",
    "IEX", "INDHOTEL", "INDIACEM", "INDIAMART", "INDIGO", "INDUSINDBK",
    "INDUSTOWER", "INFY", "IOC", "IRB", "IRCTC", "IREDA", "IRFC",
    "ITC", "JINDALSTEL", "JIOFIN", "JKCEMENT", "JSWENERGY", "JSWSTEEL",
    "JUBLFOOD", "KALYANKJIL", "KEI", "KOTAKBANK", "KPITTECH",
    "LALPATHLAB", "LAURUSLABS", "LICHSGFIN", "LICI", " LTIM".strip(),
    "LTF", "LT", "LUPIN", "M&M", "MANKIND", "MARICO", "MARUTI",
    "MAXHEALTH", "MCX", "MFSL", "MOTHERSON", "MPHASIS", "MRF",
    "MUTHOOTFIN", "NATIONALUM", "NAUKRI", "NBCC", "NCC", "NESTLEIND",
    "NHPC", "NMDC", "NTPC", "NYKAA", "OBEROIRLTY", "OFSS", "ONGC",
    "PAGEIND", "PAYTM", "PEL", "PERSISTENT", "PETRONET", "PFC",
    "PHOENIXLTD", "PIDILITIND", "PIIND", "PNB", "POLICYBZR",
    "POLYCAB", "POONAWALLA", "POWERGRID", "PRESTIGE", "RBLBANK",
    "RECLTD", "RELIANCE", "SAIL", "SBICARD", "SBILIFE", "SBIN",
    "SHREECEM", "SHRIRAMFIN", "SIEMENS", "SRF", "SUNPHARMA",
    "SUPREMEIND", "SYNGENE", "TATACHEM", "TATACOMM", "TATACONSUM",
    "TATAELXSI", "TATAMOTORS", "TATAPOWER", "TATASTEEL", "TCS",
    "TECHM", "TIINDIA", "TITAGARH", "TITAN", "TORNTPHARM",
    "TORNTPOWER", "TRENT", "TVSMOTOR", "UBL", "ULTRACEMCO",
    "UNOMINDA", "UPL", "VEDL", "VOLTAS", "WIPRO", "YESBANK", "ZYDUSLIFE"
]
FO_STOCKS = sorted(set(s.strip() for s in FO_STOCKS if s.strip()))

st.set_page_config(page_title="HT BTST Options Scanner", page_icon="📈", layout="wide")
st.title("📈 HT Advanced BTST & Swing Options Scanner")
st.caption("FREE PROTOTYPE • Manual orders only • NSE stock symbols")

with st.sidebar:
    st.header("Scanner Settings")
    mode = st.radio("Trading Mode", ["BTST (overnight)", "Swing (1–3 days)"])
    run_scan = st.button("🔎 Scan Now", type="primary", use_container_width=True)
    st.caption("Yahoo Finance data is not an exchange-grade live feed.")
    st.caption("Do not place an option trade without checking Dhan's live option chain.")

def rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss.replace(0, float("nan"))
    value = 100 - (100 / (1 + rs))
    return float(value.iloc[-1]) if len(value) and pd.notna(value.iloc[-1]) else 50.0

def fetch_symbol(symbol: str):
    ticker = yf.Ticker(f"{symbol}.NS")
    intraday = ticker.history(period="5d", interval="5m", auto_adjust=False)
    daily = ticker.history(period="6mo", interval="1d", auto_adjust=False)
    if intraday.empty or daily.empty or len(intraday) < 30 or len(daily) < 30:
        return None

    intraday = intraday.dropna(subset=["Close", "Volume"])
    daily = daily.dropna(subset=["Close"])
    close = intraday["Close"]
    volume = intraday["Volume"]
    dclose = daily["Close"]

    ema9 = close.ewm(span=9, adjust=False).mean()
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50d = dclose.ewm(span=50, adjust=False).mean()
    rsi5 = rsi(close, 14)
    rsi_daily = rsi(dclose, 14)

    # Compare latest 5-minute volume with the average of the preceding 20 bars.
    vol_avg = volume.iloc[-21:-1].mean()
    rel_volume = float(volume.iloc[-1] / vol_avg) if vol_avg and vol_avg > 0 else 0.0

    last = float(close.iloc[-1])
    prev_close = float(daily["Close"].iloc[-2])
    day_change = ((last - prev_close) / prev_close) * 100 if prev_close else 0.0
    daily_trend = float(dclose.iloc[-1]) > float(ema50d.iloc[-1])
    intraday_bull = float(ema9.iloc[-1]) > float(ema20.iloc[-1]) and last > float(ema20.iloc[-1])
    intraday_bear = float(ema9.iloc[-1]) < float(ema20.iloc[-1]) and last < float(ema20.iloc[-1])

    # Simple score: trend + momentum + relative volume + price movement.
    bull = 0
    bear = 0
    bull += 25 if daily_trend else 0
    bear += 25 if not daily_trend else 0
    bull += 25 if intraday_bull else 0
    bear += 25 if intraday_bear else 0
    bull += 15 if 52 <= rsi5 <= 72 else 0
    bear += 15 if 28 <= rsi5 <= 48 else 0
    bull += 10 if day_change > 0 else 0
    bear += 10 if day_change < 0 else 0
    bull += 15 if rel_volume >= 1.3 and day_change > 0 else 0
    bear += 15 if rel_volume >= 1.3 and day_change < 0 else 0
    bull += 10 if rsi_daily > 50 else 0
    bear += 10 if rsi_daily < 50 else 0

    direction = "CE" if bull > bear else "PE" if bear > bull else "NO TRADE"
    score = max(bull, bear)
    # ATR proxy from daily true range.
    high, low, prev = daily["High"], daily["Low"], daily["Close"].shift(1)
    tr = pd.concat([(high-low), (high-prev).abs(), (low-prev).abs()], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1])
    if not math.isfinite(atr) or atr <= 0:
        atr = last * 0.015

    return {
        "symbol": symbol, "price": last, "change": day_change, "rsi": rsi5,
        "relvol": rel_volume, "bull": bull, "bear": bear, "score": score,
        "direction": direction, "atr": atr, "daily_trend": daily_trend,
        "intraday_bull": intraday_bull, "intraday_bear": intraday_bear
    }

def scan():
    rows = []
    progress = st.progress(0, text="Scanning F&O shares…")
    status = st.empty()
    total = len(FO_STOCKS)
    for i, symbol in enumerate(FO_STOCKS, start=1):
        status.caption(f"Checking {symbol} ({i}/{total})")
        try:
            result = fetch_symbol(symbol)
            if result:
                rows.append(result)
        except Exception:
            pass
        progress.progress(i / total, text=f"Scanned {i}/{total}")
    progress.empty()
    status.empty()
    return rows

now = datetime.now(IST)
st.write(f"**IST:** {now.strftime('%d-%m-%Y %I:%M:%S %p')}")
if mode.startswith("BTST"):
    st.info("BTST mode: use the final 5-minute signal only after checking the market session and data timestamp. Avoid fresh entries if the feed is stale.")
else:
    st.info("Swing mode: signals are directional candidates for a 1–3 day holding period, not guaranteed predictions.")

if run_scan:
    with st.spinner("Fetching free market data. This may take a few minutes…"):
        results = scan()
    if not results:
        st.error("ડેટા મળ્યો નથી. Yahoo Finance પર symbols/data availability તપાસો અને ફરી પ્રયાસ કરો.")
    else:
        df = pd.DataFrame(results)
        # Keep only candidates with a meaningful directional score and avoid weak ties.
        df["edge"] = (df["bull"] - df["bear"]).abs()
        qualified = df[(df["score"] >= 65) & (df["edge"] >= 20) & (df["direction"] != "NO TRADE")]
        if qualified.empty:
            st.warning("આ સ્કેનમાં યોગ્ય સેટઅપ મળ્યો નથી. નિર્ણય: NO TRADE.")
        else:
            best = qualified.sort_values(["score", "relvol", "edge"], ascending=False).iloc[0]
            direction = best["direction"]
            entry = float(best["price"])
            atr = float(best["atr"])
            if direction == "CE":
                sl = entry - 0.8 * atr
                target = entry + 1.2 * atr
                bias = "Bullish"
            else:
                sl = entry + 0.8 * atr
                target = entry - 1.2 * atr
                bias = "Bearish"

            st.success("એક જ Final Stock પસંદ થયો")
            a, b, c = st.columns(3)
            a.metric("FINAL STOCK", best["symbol"])
            b.metric("OPTION BIAS", f"BUY {direction}")
            c.metric("SIGNAL SCORE", f"{int(best['score'])}/100")

            st.subheader("Trade Plan — Underlying Stock Levels")
            x, y, z = st.columns(3)
            x.metric("Reference Entry", f"₹{entry:,.2f}")
            y.metric("Underlying Stop Loss", f"₹{sl:,.2f}")
            z.metric("Underlying Target", f"₹{target:,.2f}")

            st.write(f"**Trend:** {bias}  |  **Day change:** {best['change']:.2f}%  |  **5m RSI:** {best['rsi']:.1f}  |  **Relative volume:** {best['relvol']:.2f}x")
            st.warning(
                f"**Option selection:** Dhanમાં {best['symbol']}ની live option chain ખોલો. "
                f"{direction} તરફ યોગ્ય expiry અને liquid strike પસંદ કરો. "
                "આ prototype strike price, option premium અથવા option-level SL/target આપતું નથી."
            )
            tv_url = f"https://www.tradingview.com/chart/?symbol=NSE%3A{best['symbol']}"
            st.link_button("📊 Open selected stock in TradingView", tv_url)
            st.caption("Chart opens the selected NSE stock. It does not inject your private Pine indicators automatically.")

            with st.expander("Signal checks (technical only)"):
                st.write({
                    "Daily close above EMA50": bool(best["daily_trend"]),
                    "Intraday EMA9/EMA20 bullish": bool(best["intraday_bull"]),
                    "Intraday EMA9/EMA20 bearish": bool(best["intraday_bear"]),
                    "Bull score": int(best["bull"]),
                    "Bear score": int(best["bear"]),
                })
            st.caption("This is a research aid, not investment advice. Overnight gaps, theta decay and volatility can cause losses.")
else:
    st.markdown("### Ready to scan")
    st.write("Sidebarમાં **Scan Now** દબાવો. Scanner એક જ strongest qualified stock બતાવશે અથવા NO TRADE આપશે.")
    st.caption(f"Starter universe: {len(FO_STOCKS)} NSE stock symbols. F&O eligibility changes; verify the current NSE contract list.")

st.divider()
st.caption("HT Scanner • Free data prototype • Manual execution only • No broker credentials required")
