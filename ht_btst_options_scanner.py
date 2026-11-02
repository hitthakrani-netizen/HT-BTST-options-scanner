"""
HT-BTST Options Scanner — DhanHQ Full Packet (Packet Code 8)
Manual signal scanner only. It NEVER places orders.

Streamlit Secrets:
DHAN_CLIENT_ID = "your_client_id"
DHAN_ACCESS_TOKEN = "your_access_token"

Important:
- Runs only on NSE trading days between 15:15 and 15:29 IST.
- Scans NSE stock options with monthly expiry (EXPIRY_FLAG == M).
- Selects ATM CE/PE contracts and returns at most ONE qualified contract.
- A signal means all programmed filters matched; it is NOT a profit guarantee.
"""

import asyncio
import json
import math
import struct
import time as time_module
from datetime import datetime, time, date
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st
import websockets

IST = ZoneInfo("Asia/Kolkata")
MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
FEED_URL = "wss://api-feed.dhan.co?version=2&token={token}&clientId={client_id}&authType=2"

# Dhan Live Feed request/response codes
REQ_SUBSCRIBE_FULL = 21
RESP_PREV_CLOSE = 6
RESP_FULL_PACKET = 8

# Tunable conservative filters. All must pass for a candidate to qualify.
UNDERLYING_MOVE_MIN_PCT = 0.10
OPTION_MOVE_MIN_PCT = 0.30
MIN_OPTION_DAY_VOLUME = 1000
MIN_OPTION_VOLUME_DELTA = 1
MIN_UNDERLYING_VOLUME_DELTA = 1
MIN_OI_CHANGE_PCT = 1.0
MIN_DEPTH_RATIO = 1.20
MAX_SPREAD_PCT = 3.0
MAX_TICK_AGE_SECONDS = 30
UNDERLYING_WARMUP_SECONDS = 8
OPTION_CAPTURE_SECONDS = 25
RECV_TIMEOUT_SECONDS = 0.5
FULL_PACKET_LENGTH = 162

st.set_page_config(page_title="HT-BTST Dhan Scanner", page_icon="📈", layout="centered")
st.title("📈 HT-BTST Options Scanner")
st.caption("DhanHQ Live Feed • Packet Code 8 • Monthly ATM • Manual trading only")

def get_credentials():
    try:
        client_id = str(st.secrets["DHAN_CLIENT_ID"]).strip()
        access_token = str(st.secrets["DHAN_ACCESS_TOKEN"]).strip()
    except Exception as exc:
        raise RuntimeError(
            "Streamlit Secrets માં DHAN_CLIENT_ID અને DHAN_ACCESS_TOKEN ઉમેરો."
        ) from exc
    if not client_id or not access_token:
        raise RuntimeError("Dhan Client ID અથવા Access Token ખાલી છે.")
    return client_id, access_token

def _clean_columns(df):
    df.columns = [str(c).strip().upper() for c in df.columns]
    return df

def _col(df, names, required=True):
    for name in names:
        if name in df.columns:
            return name
    if required:
        raise RuntimeError(
            "Instrument Master માં જરૂરી column મળ્યો નથી: " + " / ".join(names)
        )
    return None

@st.cache_data(ttl=3600, show_spinner=False)
def load_instrument_master():
    response = requests.get(MASTER_URL, timeout=30)
    response.raise_for_status()
    from io import BytesIO
    df = pd.read_csv(BytesIO(response.content), low_memory=False)
    return _clean_columns(df)

def prepare_universe(master):
    exch = _col(master, ["EXCH_ID", "SEM_EXM_EXCH_ID"])
    segment = _col(master, ["SEGMENT", "SEM_SEGMENT"])
    instrument = _col(master, ["INSTRUMENT", "SEM_INSTRUMENT_NAME"])
    secid = _col(master, ["SECURITY_ID", "SEM_SMST_SECURITY_ID", "SEM_SECURITY_ID"])
    symbol = _col(master, ["SYMBOL_NAME", "SM_SYMBOL_NAME", "UNDERLYING_SYMBOL"])
    underlying_id = _col(master, ["UNDERLYING_SECURITY_ID"], required=False)
    underlying_symbol = _col(master, ["UNDERLYING_SYMBOL"], required=False)
    expiry = _col(master, ["SM_EXPIRY_DATE", "EXPIRY_DATE", "SEM_EXPIRY_DATE"])
    strike = _col(master, ["STRIKE_PRICE", "SEM_STRIKE_PRICE"])
    option_type = _col(master, ["OPTION_TYPE", "SEM_OPTION_TYPE"])
    expiry_flag = _col(master, ["EXPIRY_FLAG", "SEM_EXPIRY_FLAG"])

    work = master.copy()
    work[exch] = work[exch].astype(str).str.upper().str.strip()
    work[segment] = work[segment].astype(str).str.upper().str.strip()
    work[instrument] = work[instrument].astype(str).str.upper().str.strip()
    work[secid] = work[secid].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()

    options = work[
        (work[exch] == "NSE") &
        (work[segment] == "D") &
        (work[instrument] == "OPTSTK")
    ].copy()
    if options.empty:
        # Some master versions label derivatives using instrument type.
        inst_type = _col(work, ["INSTRUMENT_TYPE", "SEM_EXCH_INSTRUMENT_TYPE"], required=False)
        if inst_type:
            options = work[
                (work[exch] == "NSE") &
                (work[segment] == "D") &
                (work[inst_type].astype(str).str.upper().str.strip() == "OPTSTK")
            ].copy()

    options["_EXPIRY"] = pd.to_datetime(options[expiry], errors="coerce").dt.date
    options["_STRIKE"] = pd.to_numeric(options[strike], errors="coerce")
    options["_OPT_TYPE"] = options[option_type].astype(str).str.upper().str.strip()
    options["_EXP_FLAG"] = options[expiry_flag].astype(str).str.upper().str.strip()
    options["_SECID"] = options[secid].astype(str).str.strip()
    options["_UNDER_ID"] = options[underlying_id].astype(str).str.replace(r"\.0$", "", regex=True).str.strip() if underlying_id else ""
    options["_SYMBOL"] = options[underlying_symbol].astype(str).str.upper().str.strip() if underlying_symbol else options[symbol].astype(str).str.upper().str.strip()

    today = datetime.now(IST).date()
    options = options[
        options["_EXPIRY"].notna() &
        (options["_EXPIRY"] >= today) &
        (options["_EXP_FLAG"] == "M") &
        options["_OPT_TYPE"].isin(["CE", "PE"]) &
        (options["_STRIKE"] > 0) &
        (options["_SECID"] != "")
    ].copy()

    # Find NSE cash-equity security IDs by symbol. The option master supplies
    # the underlying symbol/id; cash IDs are preferred for spot WebSocket feed.
    equities = work[
        (work[exch] == "NSE") &
        (work[segment] == "E") &
        (work[instrument] == "EQUITY")
    ].copy()
    if equities.empty:
        inst_type = _col(work, ["INSTRUMENT_TYPE", "SEM_EXCH_INSTRUMENT_TYPE"], required=False)
        if inst_type:
            equities = work[
                (work[exch] == "NSE") &
                (work[segment] == "E") &
                (work[inst_type].astype(str).str.upper().str.strip().isin(["EQUITY", "ES"]))
            ].copy()
    equities["_SECID"] = equities[secid].astype(str).str.strip()
    equities["_SYMBOL"] = equities[symbol].astype(str).str.upper().str.strip()
    equity_map = dict(zip(equities["_SYMBOL"], equities["_SECID"]))

    universe = []
    for sym, group in options.groupby("_SYMBOL"):
        if not sym or sym in ("NAN", "NONE"):
            continue
        uid = str(group["_UNDER_ID"].iloc[0]).strip()
        if not uid or uid.lower() == "nan":
            uid = equity_map.get(sym, "")
        if not uid:
            continue
        # Keep the nearest future MONTHLY expiry for this underlying.
        expiries = sorted(d for d in group["_EXPIRY"].dropna().unique() if d >= today)
        if not expiries:
            continue
        exp = expiries[0]
        contracts = group[group["_EXPIRY"] == exp]
        universe.append({
            "symbol": sym,
            "underlying_id": uid,
            "expiry": exp,
            "contracts": contracts,
        })
    if not universe:
        raise RuntimeError(
            "NSE F&O Monthly OPTSTK contracts મળ્યા નથી. Instrument Master ના columns/values તપાસો."
        )
    return universe

def subscribe_message(instruments):
    return json.dumps({
        "RequestCode": REQ_SUBSCRIBE_FULL,
        "InstrumentCount": len(instruments),
        "InstrumentList": [
            {"ExchangeSegment": seg, "SecurityId": str(secid)}
            for seg, secid in instruments
        ],
    })

def parse_packet(packet):
    """Decode Dhan 8-byte header + 154-byte FULL payload (little-endian)."""
    if not isinstance(packet, (bytes, bytearray)) or len(packet) < 8:
        return None
    response_code = packet[0]
    security_id = str(struct.unpack_from("<i", packet, 4)[0])
    if response_code == RESP_PREV_CLOSE and len(packet) >= 16:
        prev_close, prev_oi = struct.unpack_from("<fi", packet, 8)
        return {
            "code": RESP_PREV_CLOSE, "security_id": security_id,
            "prev_close": float(prev_close), "prev_oi": int(prev_oi),
        }
    if response_code != RESP_FULL_PACKET or len(packet) < FULL_PACKET_LENGTH:
        return None

    # Payload offsets are relative to the complete packet.
    ltp = struct.unpack_from("<f", packet, 8)[0]
    ltq = struct.unpack_from("<h", packet, 12)[0]
    ltt = struct.unpack_from("<i", packet, 14)[0]
    atp = struct.unpack_from("<f", packet, 18)[0]
    volume = struct.unpack_from("<i", packet, 22)[0]
    sell_qty = struct.unpack_from("<i", packet, 26)[0]
    buy_qty = struct.unpack_from("<i", packet, 30)[0]
    oi, high_oi, low_oi = struct.unpack_from("<iii", packet, 34)
    day_open, day_close, day_high, day_low = struct.unpack_from("<ffff", packet, 46)

    bid_total = 0
    ask_total = 0
    best_bid = 0.0
    best_ask = 0.0
    for level in range(5):
        offset = 62 + level * 20
        bid_qty, ask_qty, bid_orders, ask_orders, bid_price, ask_price = struct.unpack_from(
            "<iihhff", packet, offset
        )
        bid_total += max(0, bid_qty)
        ask_total += max(0, ask_qty)
        if level == 0:
            best_bid = float(bid_price)
            best_ask = float(ask_price)

    return {
        "code": RESP_FULL_PACKET,
        "security_id": security_id,
        "ltp": float(ltp),
        "ltq": int(ltq),
        "ltt": int(ltt),
        "atp": float(atp),
        "volume": int(volume),
        "sell_qty": int(sell_qty),
        "buy_qty": int(buy_qty),
        "oi": int(oi),
        "high_oi": int(high_oi),
        "low_oi": int(low_oi),
        "day_open": float(day_open),
        "day_close": float(day_close),
        "day_high": float(day_high),
        "day_low": float(day_low),
        "bid_depth": bid_total,
        "ask_depth": ask_total,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "received_at": time_module.time(),
    }

def _chunks(items, size=100):
    for i in range(0, len(items), size):
        yield items[i:i + size]

async def run_live_scan(client_id, token, universe, capture_seconds):
    url = FEED_URL.format(token=token, client_id=client_id)
    spot_ids = sorted({u["underlying_id"] for u in universe})
    option_lookup = {}
    spot_lookup = {}
    for u in universe:
        spot_lookup[u["underlying_id"]] = u["symbol"]

    snapshots = {}
    previous_oi = {}
    histories = {}

    async with websockets.connect(
        url, ping_interval=20, ping_timeout=20, close_timeout=5, max_size=2**20
    ) as ws:
        # First stage: subscribe to all NSE cash underlyings.
        spot_instruments = [("NSE_EQ", sid) for sid in spot_ids]
        for batch in _chunks(spot_instruments, 100):
            await ws.send(subscribe_message(batch))

        deadline = time_module.monotonic() + UNDERLYING_WARMUP_SECONDS
        while time_module.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=RECV_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                continue
            if isinstance(raw, bytes):
                parsed = parse_packet(raw)
                if not parsed:
                    continue
                sid = parsed["security_id"]
                if parsed["code"] == RESP_PREV_CLOSE:
                    previous_oi[sid] = parsed["prev_oi"]
                elif parsed["code"] == RESP_FULL_PACKET and sid in spot_lookup:
                    snapshots[sid] = parsed
                    histories.setdefault(sid, []).append(parsed)

        # Build ATM CE and PE using live spot price and nearest monthly expiry.
        selected_contracts = []
        selected_by_symbol = {}
        for u in universe:
            spot = snapshots.get(u["underlying_id"])
            if not spot or spot["ltp"] <= 0:
                continue
            contracts = u["contracts"].copy()
            strikes = sorted(contracts["_STRIKE"].dropna().unique())
            if not strikes:
                continue
            atm_strike = min(strikes, key=lambda x: abs(float(x) - spot["ltp"]))
            pair = contracts[contracts["_STRIKE"] == atm_strike]
            ce = pair[pair["_OPT_TYPE"] == "CE"]
            pe = pair[pair["_OPT_TYPE"] == "PE"]
            chosen = {}
            if not ce.empty:
                row = ce.iloc[0]
                chosen["CE"] = str(row["_SECID"])
                selected_contracts.append(("NSE_FNO", str(row["_SECID"])))
                option_lookup[str(row["_SECID"])] = (u["symbol"], "CE", float(atm_strike), u["expiry"])
            if not pe.empty:
                row = pe.iloc[0]
                chosen["PE"] = str(row["_SECID"])
                selected_contracts.append(("NSE_FNO", str(row["_SECID"])))
                option_lookup[str(row["_SECID"])] = (u["symbol"], "PE", float(atm_strike), u["expiry"])
            if chosen:
                selected_by_symbol[u["symbol"]] = {
                    "spot_id": u["underlying_id"],
                    "spot_start": spot["ltp"],
                    "spot_volume_start": spot["volume"],
                    "contracts": chosen,
                }

        if not selected_contracts:
            raise RuntimeError("Live underlying LTP પરથી ATM Monthly CE/PE contracts પસંદ થઈ શક્યા નથી.")

        # Second stage: subscribe to ATM monthly CE and PE option contracts.
        for batch in _chunks(sorted(set(selected_contracts)), 100):
            await ws.send(subscribe_message(batch))

        deadline = time_module.monotonic() + capture_seconds
        while time_module.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=RECV_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                continue
            if isinstance(raw, bytes):
                parsed = parse_packet(raw)
                if not parsed:
                    continue
                sid = parsed["security_id"]
                if parsed["code"] == RESP_PREV_CLOSE:
                    previous_oi[sid] = parsed["prev_oi"]
                elif parsed["code"] == RESP_FULL_PACKET:
                    snapshots[sid] = parsed
                    histories.setdefault(sid, []).append(parsed)

    return universe, snapshots, previous_oi, histories, selected_by_symbol, option_lookup

def _pct_change(start, end):
    if start is None or end is None or start <= 0:
        return 0.0
    return ((end - start) / start) * 100.0

def evaluate_candidates(universe, snapshots, previous_oi, histories, selected_by_symbol, option_lookup):
    candidates = []
    now_epoch = time_module.time()

    for symbol, meta in selected_by_symbol.items():
        spot_id = meta["spot_id"]
        spot_now = snapshots.get(spot_id)
        spot_hist = histories.get(spot_id, [])
        if not spot_now or len(spot_hist) < 2:
            continue

        spot_move = _pct_change(meta["spot_start"], spot_now["ltp"])
        spot_vol_delta = max(0, spot_now["volume"] - meta["spot_volume_start"])
        if abs(spot_move) < UNDERLYING_MOVE_MIN_PCT or spot_vol_delta < MIN_UNDERLYING_VOLUME_DELTA:
            continue

        direction = "CE" if spot_move > 0 else "PE"
        option_id = meta["contracts"].get(direction)
        if not option_id:
            continue
        opt = snapshots.get(option_id)
        opt_hist = histories.get(option_id, [])
        if not opt or len(opt_hist) < 2:
            continue

        start_opt = opt_hist[0]
        option_move = _pct_change(start_opt["ltp"], opt["ltp"])
        option_vol_delta = max(0, opt["volume"] - start_opt["volume"])
        prev_oi = previous_oi.get(option_id)
        oi_change = _pct_change(float(prev_oi), float(opt["oi"])) if prev_oi and prev_oi > 0 else None
        depth_ratio = opt["bid_depth"] / max(1, opt["ask_depth"])
        spread_pct = (
            ((opt["best_ask"] - opt["best_bid"]) / opt["best_ask"]) * 100
            if opt["best_ask"] > 0 and opt["best_bid"] > 0 and opt["best_ask"] >= opt["best_bid"]
            else 999.0
        )
        tick_age = now_epoch - opt["ltt"] if opt["ltt"] > 0 else 999999

        # Strict conjunction: every condition must pass.
        checks = {
            "spot_directional_move": abs(spot_move) >= UNDERLYING_MOVE_MIN_PCT,
            "spot_volume_increased": spot_vol_delta >= MIN_UNDERLYING_VOLUME_DELTA,
            "option_premium_rising": option_move >= OPTION_MOVE_MIN_PCT,
            "option_volume_increased": option_vol_delta >= MIN_OPTION_VOLUME_DELTA,
            "option_day_volume": opt["volume"] >= MIN_OPTION_DAY_VOLUME,
            "oi_up_vs_previous_close": oi_change is not None and oi_change >= MIN_OI_CHANGE_PCT,
            "bid_depth_dominant": depth_ratio >= MIN_DEPTH_RATIO,
            "spread_acceptable": spread_pct <= MAX_SPREAD_PCT,
            "fresh_last_trade": tick_age <= MAX_TICK_AGE_SECONDS,
            "valid_prices": opt["ltp"] > 0 and opt["best_bid"] > 0 and opt["best_ask"] > 0,
        }
        if not all(checks.values()):
            continue

        # Ranking only chooses ONE among fully qualified candidates.
        score = (
            min(abs(spot_move) / UNDERLYING_MOVE_MIN_PCT, 5.0) * 15
            + min(option_move / OPTION_MOVE_MIN_PCT, 5.0) * 20
            + min(max(oi_change, 0) / MIN_OI_CHANGE_PCT, 5.0) * 20
            + min(depth_ratio / MIN_DEPTH_RATIO, 3.0) * 15
            + min(option_vol_delta / 1000.0, 5.0) * 15
            + min(opt["volume"] / 10000.0, 5.0) * 15
        )
        info = option_lookup[option_id]
        candidates.append({
            "symbol": symbol,
            "signal": "CALL" if direction == "CE" else "PUT",
            "option_type": direction,
            "strike": info[2],
            "expiry": info[3],
            "option_ltp": opt["ltp"],
            "spot_ltp": spot_now["ltp"],
            "spot_move_pct": spot_move,
            "option_move_pct": option_move,
            "option_volume": opt["volume"],
            "option_volume_delta": option_vol_delta,
            "oi": opt["oi"],
            "oi_change_pct": oi_change,
            "depth_ratio": depth_ratio,
            "spread_pct": spread_pct,
            "score": score,
            "checks": checks,
        })

    if not candidates:
        return None
    return sorted(candidates, key=lambda x: x["score"], reverse=True)[0]

def run_scanner():
    now = datetime.now(IST)
    if now.weekday() >= 5:
        st.warning("આજે શનિવાર/રવિવાર છે. NSE trading day પર ફરી Scan કરો.")
        return
    if not (time(15, 15) <= now.time().replace(tzinfo=None) <= time(15, 29)):
        st.warning("BTST Scan ફક્ત Trading Day ના 3:15 PM થી 3:29 PM IST વચ્ચે જ ચાલશે.")
        return

    client_id, token = get_credentials()
    with st.spinner("Dhan Instrument Master લોડ થાય છે..."):
        master = load_instrument_master()
        universe = prepare_universe(master)

    st.info(f"Monthly F&O stocks found: {len(universe)}. Live Dhan Full Packet feed શરૂ થાય છે.")
    progress = st.progress(0, text="Underlying live feed subscribe થાય છે...")
    result_data = asyncio.run(
        run_live_scan(client_id, token, universe, OPTION_CAPTURE_SECONDS)
    )
    progress.progress(100, text="Confirmation checks પૂર્ણ.")
    progress.empty()

    best = evaluate_candidates(*result_data)
    if not best:
        st.warning("NO TRADE — કોઈપણ Stock ની બધી LTP + Volume + OI + Market Depth conditions એકસાથે પૂરી થઈ નથી.")
        return

    st.success("એક જ fully-qualified signal મળ્યો")
    st.subheader(best["symbol"])
    col1, col2, col3 = st.columns(3)
    col1.metric("SIGNAL", best["signal"])
    col2.metric("ATM STRIKE", f'{best["strike"]:g} {best["option_type"]}')
    col3.metric("MONTHLY EXPIRY", best["expiry"].strftime("%d-%b-%Y"))
    st.metric("Option LTP", f'₹{best["option_ltp"]:,.2f}')
    st.caption("એક જ Stock બતાવવામાં આવે છે. કોઈ order આપમેળે મૂકાતો નથી.")
    with st.expander("Confirmation audit (all must be True)"):
        st.write({
            "Underlying LTP move %": round(best["spot_move_pct"], 3),
            "Option LTP move %": round(best["option_move_pct"], 3),
            "Option day volume": int(best["option_volume"]),
            "Option volume increase during scan": int(best["option_volume_delta"]),
            "OI": int(best["oi"]),
            "OI change vs previous close %": round(best["oi_change_pct"], 3),
            "5-level bid/ask quantity ratio": round(best["depth_ratio"], 3),
            "Best bid/ask spread %": round(best["spread_pct"], 3),
            "All filters": best["checks"],
            "Ranking score (not probability)": round(best["score"], 1),
        })
    st.caption("Technical filter match is not a 100% profit guarantee. Options can lose value rapidly; verify the contract and risk before manual entry.")

with st.sidebar:
    st.header("Scanner Settings")
    st.write("**Strike:** ATM")
    st.write("**Expiry:** Monthly")
    st.write("**Time:** 3:15–3:29 PM IST")
    capture = st.slider("Live option capture (seconds)", 15, 60, OPTION_CAPTURE_SECONDS, 5)
    st.caption("No auto orders • One final stock only • No signal = NO TRADE")
    run_button = st.button("🔎 Scan for one confirmed stock", type="primary", use_container_width=True)

if run_button:
    try:
        # Honour the sidebar capture duration without changing the fixed strategy.
        OPTION_CAPTURE_SECONDS = int(capture)
        run_scanner()
    except Exception as exc:
        st.error(f"Scanner error: {exc}")
        st.caption("Dhan API token, API access, Streamlit Secrets, instrument-master columns અને internet connection તપાસો.")
else:
    st.info("Scan button દબાવો. BTST માટે 3:15 PM થી 3:29 PM IST દરમિયાન જ Scan થશે.")
    st.caption("આ સ્કેનર ફક્ત Manual Trading માટે છે; auto order placement બંધ છે.")
