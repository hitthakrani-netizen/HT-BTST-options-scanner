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
st.caption("FREE PROTOTYPE • Strict confirmation filters • Manual orders only • NSE stock symbols")

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
    """Return a conservative signal only when today's intraday data is fresh.

    Yahoo Finance is a free, non-exchange-grade source. This deliberately
    rejects stale/incomplete data and weak or conflicting setups.
    """
    ticker = yf.Ticker(f"{symbol}.NS")
    intraday = ticker.history(period="5d", interval="5m", auto_adjust=False)
    daily = ticker.history(period="6mo", interval="1d", auto_adjust=False)
    if intraday.empty or daily.empty or len(daily) < 60:
        return None

    intraday = intraday.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
    daily = daily.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
    if intraday.empty:
        return None

    # Normalize timestamps to IST and keep only today's completed 5-minute bars.
    idx = intraday.index
    if idx.tz is None:
        intraday.index = idx.tz_localize("Asia/Kolkata")
    else:
        intraday.index = idx.tz_convert("Asia/Kolkata")
    now_ist = datetime.now(IST)
    today_bars = intraday[intraday.index.date == now_ist.date()].copy()
    if today_bars.empty:
        return None
    # Yahoo labels a 5m candle by its start time. Do not use a candle until it closes.
    completed = today_bars[today_bars.index + pd.Timedelta(minutes=5) <= pd.Timestamp(now_ist)]
    if len(completed) < 25:
        return None
    bar_time = completed.index[-1]
    age_minutes = (pd.Timestamp(now_ist) - bar_time).total_seconds() / 60
    if age_minutes > 12:
        return None

    close = completed["Close"].astype(float)
    volume = completed["Volume"].astype(float)
    high = completed["High"].astype(float)
    low = completed["Low"].astype(float)
    ema9 = close.ewm(span=9, adjust=False).mean()
    ema20 = close.ewm(span=20, adjust=False).mean()
    rsi5 = rsi(close, 14)

    # Session VWAP; reject zero-volume or unavailable values.
    typical = (high + low + close) / 3
    cum_vol = volume.cumsum()
    vwap_series = (typical * volume).cumsum() / cum_vol.replace(0, float("nan"))
    vwap = float(vwap_series.iloc[-1]) if pd.notna(vwap_series.iloc[-1]) else float("nan")
    if not math.isfinite(vwap):
        return None

    dclose = daily["Close"].astype(float)
    ema50d = dclose.ewm(span=50, adjust=False).mean()
    rsi_daily = rsi(dclose, 14)
    last = float(close.iloc[-1])
    prev_close = float(daily["Close"].iloc[-2])
    day_change = ((last - prev_close) / prev_close) * 100 if prev_close else 0.0
    daily_bull = float(dclose.iloc[-1]) > float(ema50d.iloc[-1]) and rsi_daily >= 52
    daily_bear = float(dclose.iloc[-1]) < float(ema50d.iloc[-1]) and rsi_daily <= 48
    intraday_bull = float(ema9.iloc[-1]) > float(ema20.iloc[-1]) and last > float(ema20.iloc[-1]) and last > vwap
    intraday_bear = float(ema9.iloc[-1]) < float(ema20.iloc[-1]) and last < float(ema20.iloc[-1]) and last < vwap

    # Require a close beyond the preceding 3 completed bars, not just an EMA cross.
    prior_high = float(high.iloc[-4:-1].max())
    prior_low = float(low.iloc[-4:-1].min())
    breakout_bull = last > prior_high
    breakout_bear = last < prior_low

    vol_avg = float(volume.iloc[-21:-1].mean()) if len(volume) >= 21 else 0.0
    rel_volume = float(volume.iloc[-1] / vol_avg) if vol_avg > 0 else 0.0
    bull = 0
    bear = 0
    bull += 25 if daily_bull else 0
    bear += 25 if daily_bear else 0
    bull += 25 if intraday_bull else 0
    bear += 25 if intraday_bear else 0
    bull += 20 if breakout_bull else 0
    bear += 20 if breakout_bear else 0
    bull += 15 if 52 <= rsi5 <= 70 else 0
    bear += 15 if 30 <= rsi5 <= 48 else 0
    bull += 15 if rel_volume >= 1.5 else 0
    bear += 15 if rel_volume >= 1.5 else 0

    # Conservative confirmation: all major filters must agree.
    if daily_bull and intraday_bull and breakout_bull and 52 <= rsi5 <= 70 and rel_volume >= 1.5:
        direction = "CE"
    elif daily_bear and intraday_bear and breakout_bear and 30 <= rsi5 <= 48 and rel_volume >= 1.5:
        direction = "PE"
    else:
        direction = "NO TRADE"
    score = max(bull, bear)

    dhigh, dlow, dprev = daily["High"].astype(float), daily["Low"].astype(float), daily["Close"].astype(float).shift(1)
    tr = pd.concat([(dhigh-dlow), (dhigh-dprev).abs(), (dlow-dprev).abs()], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1])
    if not math.isfinite(atr) or atr <= 0:
        return None

    return {
        "symbol": symbol, "price": last, "change": day_change, "rsi": rsi5,
        "relvol": rel_volume, "bull": bull, "bear": bear, "score": score,
        "direction": direction, "atr": atr, "daily_trend": daily_bull or daily_bear,
        "intraday_bull": intraday_bull, "intraday_bear": intraday_bear,
        "vwap": vwap, "bar_time": bar_time.strftime("%H:%M"), "age_minutes": age_minutes,
        "breakout_bull": breakout_bull, "breakout_bear": breakout_bear,
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

if run_scan and now.weekday() >= 5:
    st.warning("આજે NSE બજાર બંધ છે. આજના ડેટા પરથી નવો ટ્રેડિંગ સિગ્નલ નહીં આપીએ. આગામી Trading Day પર ફરી Scan કરો.")
elif run_scan and mode.startswith("BTST") and not (time(15, 15) <= now.time().replace(tzinfo=None) <= time(15, 29)):
    st.warning("BTST માટે Scan ફક્ત Trading Day ના 3:15 PM થી 3:29 PM વચ્ચે કરો. સવારે મળતો Signal BTST Final Signal નથી.")
elif run_scan and mode.startswith("Swing") and not (time(9, 30) <= now.time().replace(tzinfo=None) <= time(15, 15)):
    st.warning("Swing Scan માટે Trading Day ના 9:30 AM થી 3:15 PM વચ્ચે Scan કરો.")
elif run_scan:
    with st.spinner("Fetching free market data. This may take a few minutes…"):
        results = scan()
    if not results:
        st.error("ડેટા મળ્યો નથી. Yahoo Finance પર symbols/data availability તપાસો અને ફરી પ્રયાસ કરો.")
    else:
        df = pd.DataFrame(results)
        # Keep only candidates with a meaningful directional score and avoid weak ties.
        df["edge"] = (df["bull"] - df["bear"]).abs()
        qualified = df[(df["score"] >= 100) & (df["edge"] >= 40) & (df["direction"] != "NO TRADE")]
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

            st.write(f"**Trend:** {bias}  |  **Day change:** {best['change']:.2f}%  |  **5m RSI:** {best['rsi']:.1f}  |  **Relative volume:** {best['relvol']:.2f}x  |  **VWAP:** ₹{best['vwap']:.2f}  |  **Last completed candle:** {best['bar_time']}")
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
                    "Above prior 3-bar high": bool(best["breakout_bull"]),
                    "Below prior 3-bar low": bool(best["breakout_bear"]),
                    "Completed candle age (minutes)": round(float(best["age_minutes"]), 1),
                    "Bull score": int(best["bull"]),
                    "Bear score": int(best["bear"]),
                })
            st.caption("This is a research aid, not investment advice. Overnight gaps, theta decay and volatility can cause losses.")
else:
    st.markdown("### Ready to scan")
    st.write("Sidebarમાં **Scan Now** દબાવો. Scanner એક જ strongest qualified stock બતાવશે અથવા NO TRADE આપશે.")
    st.caption(f"Starter universe: {len(FO_STOCKS)} NSE stock symbols. Strict filters may often return NO TRADE. F&O eligibility changes; verify the current NSE contract list.")

st.divider()
st.caption("HT Scanner • Free data prototype • Manual execution only • No broker credentials required")
