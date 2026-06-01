import os
import time
import requests
import json
import datetime
import pandas as pd
import numpy as np
import streamlit as st

# ─────────────────────────────────────────────
# CONSTANTS & CONFIGURATION
# ─────────────────────────────────────────────

CALENDAR_PATH = "/cpfs/intrastats/calendar"

# Price cache: { instrument_id -> last known price }
# Populated at startup from pre_settlement_price, updated each tick.
_price_cache: dict[str, float] = {}

# ── Market-open time windows ──────────────────
# commodity: morning 09:00, evening 21:00
# futures  : morning 09:30  (no evening session)
COMMODITY_MORNING_OPEN  = datetime.time(9,  0)
FUTURES_MORNING_OPEN    = datetime.time(9, 30)
MORNING_CLOSE           = datetime.time(15, 15)   # both close ~15:00-15:15
EVENING_OPEN            = datetime.time(21, 0)
EVENING_CLOSE_NEXT_DAY  = datetime.time(2, 30)    # crosses midnight

# ── Product registry ──────────────────────────
# Each entry:
#   path, broker, product_name, futures_type, init_capital (0 = use pre_balance)
PRODUCT_CONFIGS = [
    {
        "path":         "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_data_baguatian",
        "broker":       "Dongzheng",
        "product_name": "Baguatian (AnXin 1Hao)",
        "futures_type": "commodity",
        "init_capital": 147680000,
    },
    {
        "path":         "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_data_shjq_zx",
        "broker":       "Zhongxin",
        "product_name": "Shanhai Jinqu",
        "futures_type": "commodity",
        "init_capital": 0,
    },
    {
        "path":         "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_data_shph1h_zx",
        "broker":       "Zhongxin",
        "product_name": "Shanhai Pingheng 1Hao",
        "futures_type": "commodity",
        "init_capital": 0,
    },
    {
        "path":         "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_date",
        "broker":       "Zhongxin",
        "product_name": "Zhizeng 1Hao",
        "futures_type": "commodity",
        "init_capital": 25000000,
    },
    {
        "path":         "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_jz1h",
        "broker":       "Dongzheng",
        "product_name": "jz1h",
        "futures_type": "futures",
        "init_capital": 110000000,
    },
    {
        "path":         "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_ly1h",
        "broker":       "Dongzheng",
        "product_name": "ly1h",
        "futures_type": "futures",
        "init_capital": 25000000,
    },
    {
        "path":         "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_zz1h",
        "broker":       "Zhongxin",
        "product_name": "zz1h",
        "futures_type": "futures",
        "init_capital": 26240000,
    },
]

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def get_date_from_calendar():
    date = datetime.datetime.now().date()
    date_int = int(date.strftime("%Y%m%d"))
    date_list = np.loadtxt(CALENDAR_PATH, dtype=np.int64, ndmin=1)
    pos = np.searchsorted(date_list, date_int, side="right")
    next_trade_day = int(date_list[pos])
    return date_int, next_trade_day


def is_market_open(futures_type: str) -> bool:
    """
    Returns True when the market for this futures_type is expected to be open.

    Commodity:  09:00-15:15  and  21:00-02:30(+1)
    Futures:    09:30-15:15  only
    """
    now = datetime.datetime.now()
    t   = now.time()

    # Morning session
    if futures_type == "commodity":
        in_morning = COMMODITY_MORNING_OPEN <= t <= MORNING_CLOSE
    else:
        in_morning = FUTURES_MORNING_OPEN <= t <= MORNING_CLOSE

    if in_morning:
        return True

    # Evening session – commodity only, spans midnight
    if futures_type == "commodity":
        # Before midnight: 21:00 → 23:59
        in_evening_before_midnight = t >= EVENING_OPEN
        # After midnight:  00:00 → 02:30
        in_evening_after_midnight  = t <= EVENING_CLOSE_NEXT_DAY
        if in_evening_before_midnight or in_evening_after_midnight:
            return True

    return False


def safe_read_csv(filepath: str) -> tuple[pd.DataFrame | None, str | None]:
    """
    Returns (dataframe, error_message).
    - File missing       → (None, "File not found: ...")
    - File fully empty   → (None, "File is empty: ...")
    - Only header row    → (empty DataFrame with columns, None)   ← treated as normal
    - Normal             → (DataFrame, None)
    """
    if not os.path.exists(filepath):
        return None, f"File not found: {filepath}"
    if os.path.getsize(filepath) == 0:
        return None, f"File is completely empty (0 bytes): {filepath}"
    try:
        df = pd.read_csv(filepath)
        # File with header only → 0 data rows, but that is OK
        return df, None
    except Exception as e:
        return None, f"CSV parse error [{filepath}]: {e}"


def get_margin_file_path(path: str, futures_type: str, current_date: int) -> str:
    if futures_type == "commodity":
        return "/cpfs/rawdata/cncf_all_nedd_before_open/margin_uplimit.csv"
    mapping = {
        "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_jz1h":
            f"/cpfs/rawdata/cnif_all_need_before_open/margin_uplimit_jz1h_{current_date}.csv",
        "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_ly1h":
            f"/cpfs/rawdata/cnif_all_need_before_open/margin_uplimit_ly1h_{current_date}.csv",
        "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_zz1h":
            f"/cpfs/rawdata/cnif_all_need_before_open/margin_uplimit_zz1h_{current_date}.csv",
    }
    return mapping.get(path, "")


def get_static_info_path(futures_type: str) -> str:
    if futures_type == "commodity":
        return "/cpfs/rawdata/cncf_all_nedd_before_open/ins_static_info.csv"
    return "/cpfs/rawdata/cnif_all_need_before_open/ins_static_info.csv"


def get_market_data_path(futures_type: str, current_date: int) -> str:
    kind = "commodity" if futures_type == "commodity" else "futures"
    return f"/mnt/nfs_bohr_data1/china/trading_realdata/partial_market_data_realtime/{kind}/{current_date}.csv"


def get_trade_file_path(path: str, current_date: int) -> str:
    return os.path.join(path, f"trade_data_{current_date}.csv")


def send_alert(message: str):
    webhook_url = (
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
        "?key=1f5ccb85-9f37-46a5-b5a7-d5e0a7cc9b3c"
    )
    msg = {"msgtype": "text", "text": {"content": message}}
    try:
        requests.post(webhook_url, data=json.dumps(msg), timeout=5)
    except Exception:
        pass


# ─────────────────────────────────────────────
# PRICE CACHE MANAGEMENT
# ─────────────────────────────────────────────

def init_price_cache(futures_type: str, current_date: int):
    """
    Called once at startup (or when cache is empty).
    Seeds _price_cache with pre_settlement_price from the position file
    for every product config of the given futures_type.
    """
    for cfg in PRODUCT_CONFIGS:
        if cfg["futures_type"] != futures_type:
            continue
        pd_path = os.path.join(cfg["path"], f"position_data_{current_date}.csv")
        df, err = safe_read_csv(pd_path)
        if err or df is None or df.empty:
            continue
        if "instrument_id" in df.columns and "pre_settlement_price" in df.columns:
            for _, row in df.iterrows():
                inst = row["instrument_id"]
                price = row.get("pre_settlement_price", 0)
                if inst not in _price_cache and pd.notna(price) and price > 0:
                    _price_cache[inst] = float(price)


def update_price_cache(future_df: pd.DataFrame):
    """
    Replaces cached prices with the latest mid-price from the market data snapshot.
    Called every refresh cycle after the market file is loaded.
    """
    if future_df is None or future_df.empty:
        return
    required = {"instrument", "ask_price1", "bid_price1"}
    if not required.issubset(future_df.columns):
        return
    for _, row in future_df.iterrows():
        inst = row["instrument"]
        ask  = row.get("ask_price1", 0)
        bid  = row.get("bid_price1", 0)
        if pd.notna(ask) and pd.notna(bid) and (ask + bid) > 0:
            _price_cache[inst] = float((ask + bid) / 2)


def get_price(instrument: str) -> float | None:
    """Return cached price or None if unknown."""
    return _price_cache.get(instrument)


# ─────────────────────────────────────────────
# STYLERS
# ─────────────────────────────────────────────

def style_product_low_limit(val):
    try:
        if float(val) < 0.8:
            return "background-color: #ff4b4b; color: white"
    except (ValueError, TypeError):
        pass
    return ""


def style_instrument_margin_uplimit(val):
    try:
        if float(val) > 0.25:
            return "background-color: #ff4b4b; color: white"
    except (ValueError, TypeError):
        pass
    return ""


def style_nonzero_yellow(val):
    try:
        if abs(float(val)) > 1e-6:
            return "background-color: #ffd700; color: black"
    except (ValueError, TypeError):
        pass
    return ""


# ─────────────────────────────────────────────
# CORE: calculate_product
# ─────────────────────────────────────────────

SUMMARY_COLS = [
    "futures_type", "product_name", "broker",
    "init_capital",
    "balance", "pre_balance", "market_value",
    "cost", "abs_return", "pnl",
    "instrument_margin_uplimit", "product_low_limit",
    "deposit_withdraw", "time", "warnings",
]

DEFAULT_SUMMARY = {
    "futures_type": "",
    "product_name": "",
    "broker": "",
    "init_capital": 0,
    "balance": 0,
    "pre_balance": 0,
    "market_value": 0,
    "cost": 0,
    "abs_return": 0,
    "pnl": "0.000%",
    "instrument_margin_uplimit": 0.0,
    "product_low_limit": 0.0,
    "deposit_withdraw": 0,
    "time": "",
    "warnings": "",
}


def calculate_product(
    path: str,
    broker: str,
    product_name: str,
    futures_type: str,
    init_capital: float,
    current_date: int,
    # Shared dataframes (pre-loaded outside to avoid redundant I/O)
    shared_sd_df: pd.DataFrame | None,
    shared_future_df: pd.DataFrame | None,
    shared_margin_df: pd.DataFrame | None,
) -> tuple[dict, pd.DataFrame | None]:
    """
    Returns:
        summary_row : dict  (one row for the overview table)
        detail_df   : pd.DataFrame | None  (per-instrument breakdown)
    """
    warnings_list: list[str] = []
    data = dict(DEFAULT_SUMMARY)
    data["futures_type"]  = "cncf" if futures_type == "commodity" else "cnif"
    data["product_name"]  = product_name
    data["broker"]        = broker
    data["init_capital"]  = init_capital
    data["time"]          = datetime.datetime.now().strftime("%H:%M:%S")

    # ── 1. account_info ──────────────────────────────────────
    ai_path = os.path.join(path, f"account_info_{current_date}.csv")
    ai_df, ai_err = safe_read_csv(ai_path)
    if ai_err:
        warnings_list.append(ai_err)
        data["warnings"] = " | ".join(warnings_list)
        return data, None
    if ai_df.empty:
        # header-only file → default zeros
        warnings_list.append(f"Header-only file (using defaults): {ai_path}")
        balance     = 0.0
        pre_balance = 0.0
        deposit     = 0.0
        withdraw    = 0.0
        fee         = 0.0
    else:
        balance     = float(ai_df["balance"].iloc[0])
        pre_balance = float(ai_df["pre_balance"].iloc[0])
        deposit     = float(ai_df["deposit"].iloc[0])
        withdraw    = float(ai_df["withdraw"].iloc[0])
        fee         = float(ai_df["fee"].iloc[0])

    data["balance"]          = balance
    data["pre_balance"]      = pre_balance
    data["deposit_withdraw"] = deposit - withdraw
    data["cost"]             = fee

    # ── 2. position_data ─────────────────────────────────────
    pd_path = os.path.join(path, f"position_data_{current_date}.csv")
    pd_df, pd_err = safe_read_csv(pd_path)
    if pd_err:
        warnings_list.append(pd_err)
        data["warnings"] = " | ".join(warnings_list)
        return data, None
    if pd_df.empty:
        warnings_list.append(f"Header-only file (using defaults): {pd_path}")
        pd_df = pd.DataFrame(columns=[
            "instrument_id", "pos_type", "position",
            "position_profit", "close_profit", "pre_settlement_price",
        ])

    data["abs_return"] = float(
        (pd_df.get("position_profit", pd.Series([0])).fillna(0)
         + pd_df.get("close_profit",  pd.Series([0])).fillna(0)).sum()
    )

    # ── 3. PnL ───────────────────────────────────────────────
    pnl_denominator = init_capital if init_capital > 0 else pre_balance
    if pnl_denominator > 0:
        pnl = round((data["abs_return"] - fee) / pnl_denominator * 100, 3)
    else:
        pnl = 0.0
    data["pnl"] = f"{pnl:.3f}%"

    # ── 4. Static info (shared) ───────────────────────────────
    sd_df = shared_sd_df  # may be None

    # ── 5. Market data (shared, possibly sparse due to night session) ─
    future_df = shared_future_df  # may be None or sparse

    # ── 6. Margin file (shared) ───────────────────────────────
    margin_df = shared_margin_df  # may be None

    # ── 7. Per-instrument calculations ───────────────────────
    market_value          = 0.0
    instrument_margin_max = 0.0
    detail_rows: list[dict] = []

    instruments = pd_df["instrument_id"].dropna().unique().tolist() if not pd_df.empty else []

    # Load trade file for last-trade-time lookup
    trade_path = get_trade_file_path(path, current_date)
    trade_df, trade_err = safe_read_csv(trade_path)
    if trade_err:
        warnings_list.append(trade_err)
        trade_df = None

    for inst in instruments:
        inst_warnings: list[str] = []

        # Position (net: LONG positive, SHORT negative)
        long_rows  = pd_df.query(f"instrument_id == '{inst}' and pos_type == 'LONG'")
        short_rows = pd_df.query(f"instrument_id == '{inst}' and pos_type == 'SHORT'")
        long_pos  = float(long_rows["position"].iloc[0])  if not long_rows.empty  else 0.0
        short_pos = float(short_rows["position"].iloc[0]) if not short_rows.empty else 0.0
        net_pos   = long_pos - short_pos   # display as signed int

        # close_profit & position_profit per instrument
        cp = float(pd_df[pd_df["instrument_id"] == inst]["close_profit"].fillna(0).sum())
        pp = float(pd_df[pd_df["instrument_id"] == inst]["position_profit"].fillna(0).sum())
        total_pnl = cp + pp

        # Multiplier
        multiplier = 1.0
        exchange   = ""
        if sd_df is not None and not sd_df.empty:
            sd_row = sd_df[sd_df["instrument"] == inst]
            if not sd_row.empty:
                multiplier = float(sd_row["multiplier"].iloc[0])
                exchange   = str(sd_row["exchange"].iloc[0]) if "exchange" in sd_row.columns else ""
            else:
                inst_warnings.append(f"no static info for {inst}")
        else:
            inst_warnings.append(f"static info file unavailable for {inst}")

        # Margin ratio
        margin_ratio = 0.0
        if margin_df is not None and not margin_df.empty:
            m_row = margin_df[margin_df["instrument"] == inst]
            if not m_row.empty:
                margin_ratio = float(m_row["margin_ratio"].iloc[0])

        # Price (from cache – updated from market file each cycle)
        price = get_price(inst)
        if price is None:
            inst_warnings.append(f"no price available for {inst} (using 0)")
            price = 0.0

        # Market value contribution
        total_pos = long_pos + short_pos
        market_value += total_pos * price * multiplier

        # Per-instrument margin (use absolute position for sizing)
        inst_margin = price * total_pos * multiplier * margin_ratio
        print(f"inst_margin {inst_margin} price {price} total_pos {total_pos} multiplier {multiplier} margin_ratio {margin_ratio}")
        instrument_margin_max = max(inst_margin, instrument_margin_max)

        # Last trade time
        last_trade_time = ""
        if trade_df is not None and not trade_df.empty:
            t_rows = trade_df[trade_df.get("instrument_id", trade_df.get("instrument", pd.Series())) == inst]
            if not t_rows.empty:
                time_col = "trade_time" if "trade_time" in t_rows.columns else (
                           "update_time" if "update_time" in t_rows.columns else None)
                if time_col:
                    last_trade_time = str(t_rows[time_col].iloc[-1])

        detail_rows.append({
            "instrument":        inst,
            "position":          int(net_pos),
            "close_profit":      round(cp, 2),
            "position_profit":   round(pp, 2),
            "total_pnl":         round(total_pnl, 2),
            "instrument_margin": round(inst_margin, 2),
            "exchange":          exchange,
            "last_trade_time":   last_trade_time,
            "_warnings":         "; ".join(inst_warnings),
        })

    data["market_value"] = market_value
    data["product_low_limit"] = (
        market_value / balance if balance > 0 else 0.0
    )
    data["instrument_margin_uplimit"] = (
        instrument_margin_max / balance if balance > 0 else 0.0
    )
    data["warnings"] = " | ".join(warnings_list)

    detail_df = pd.DataFrame(detail_rows) if detail_rows else None
    return data, detail_df


# ─────────────────────────────────────────────
# SHARED FILE LOADER  (load once per cycle)
# ─────────────────────────────────────────────

def load_shared_files(
    futures_type: str,
    path: str,
    current_date: int,
) -> tuple[pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None, list[str]]:
    """
    Returns (sd_df, future_df, margin_df, file_errors).
    Errors are strings suitable for display in the dashboard.
    """
    errors: list[str] = []

    # static info
    sd_path  = get_static_info_path(futures_type)
    sd_df, e = safe_read_csv(sd_path)
    if e:
        errors.append(e)

    # market data
    mkt_path   = get_market_data_path(futures_type, current_date)
    future_df, e = safe_read_csv(mkt_path)
    if e:
        errors.append(e)
    else:
        # Update price cache regardless of session hours
        update_price_cache(future_df)

    # margin
    margin_path   = get_margin_file_path(path, futures_type, current_date)
    margin_df, e  = safe_read_csv(margin_path) if margin_path else (None, "No margin path configured")
    if e:
        errors.append(e)

    return sd_df, future_df, margin_df, errors


# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────

def dashboard():
    st.set_page_config(page_title="Futures Monitor Dashboard", layout="wide")

    # ── Seed price cache at startup ───────────────────────────
    try:
        current_date, _ = get_date_from_calendar()
        init_price_cache("commodity", current_date)
        init_price_cache("futures",   current_date)
    except Exception as e:
        st.warning(f"Price cache init failed: {e}")

    placeholder = st.empty()

    while True:
        try:
            current_date, _ = get_date_from_calendar()
            now = datetime.datetime.now()

            # ── Summary table accumulator ──────────────────────
            summary_rows: list[dict]      = []
            detail_map:   dict[str, pd.DataFrame] = {}  # product_name → detail_df
            global_file_errors: list[str] = []

            # Pre-load shared files per futures_type to avoid reading the same
            # market/static files once per product.
            shared_cache: dict[str, tuple] = {}  # futures_type → (sd, future, margin, errors)

            for cfg in PRODUCT_CONFIGS:
                ft   = cfg["futures_type"]
                path = cfg["path"]
                name = cfg["product_name"]

                # ── Opening-hours guard ────────────────────────
                if not is_market_open(ft):
                    # Still show the row but mark it as pre-market
                    row = dict(DEFAULT_SUMMARY)
                    row.update({
                        "futures_type": "cncf" if ft == "commodity" else "cnif",
                        "product_name": name,
                        "broker":       cfg["broker"],
                        "init_capital": cfg["init_capital"],
                        "time":         now.strftime("%H:%M:%S"),
                        "warnings":     "Market not open yet",
                    })
                    summary_rows.append(row)
                    continue

                # ── Load shared files (once per futures_type) ──
                # For commodity, margin_df varies per product path → load per product.
                # For futures,   margin_df also varies per path    → load per product.
                # sd_df and future_df are shared per futures_type.
                if ft not in shared_cache:
                    sd_df, future_df, _dummy_margin, errs = load_shared_files(
                        ft, path, current_date
                    )
                    shared_cache[ft] = (sd_df, future_df, errs)
                    global_file_errors.extend(errs)

                sd_df, future_df, _shared_errs = shared_cache[ft]

                # Load margin per product (path-specific for futures)
                margin_path  = get_margin_file_path(path, ft, current_date)
                margin_df, m_err = safe_read_csv(margin_path) if margin_path else (None, None)
                if m_err:
                    global_file_errors.append(m_err)

                # ── Calculate ─────────────────────────────────
                try:
                    row, detail_df = calculate_product(
                        path          = path,
                        broker        = cfg["broker"],
                        product_name  = name,
                        futures_type  = ft,
                        init_capital  = cfg["init_capital"],
                        current_date  = current_date,
                        shared_sd_df      = sd_df,
                        shared_future_df  = future_df,
                        shared_margin_df  = margin_df,
                    )
                except Exception as calc_err:
                    row = dict(DEFAULT_SUMMARY)
                    row.update({
                        "futures_type": "cncf" if ft == "commodity" else "cnif",
                        "product_name": name,
                        "broker":       cfg["broker"],
                        "init_capital": cfg["init_capital"],
                        "time":         now.strftime("%H:%M:%S"),
                        "warnings":     f"Calculation error: {calc_err}",
                    })
                    detail_df = None

                summary_rows.append(row)
                if detail_df is not None:
                    detail_map[name] = (cfg, detail_df)

                # ── Alert checks ───────────────────────────────
                try:
                    pll = float(row["product_low_limit"])
                    imu = float(row["instrument_margin_uplimit"])
                    if pll < 0.8:
                        send_alert(
                            f"[ALERT] product_low_limit < 0.8 | "
                            f"broker={row['broker']} product={name} time={row['time']}"
                        )
                    if imu > 0.25:
                        send_alert(
                            f"[ALERT] instrument_margin_uplimit > 0.25 | "
                            f"broker={row['broker']} product={name} time={row['time']}"
                        )
                except (ValueError, TypeError):
                    pass

            # ── Build summary DataFrame ────────────────────────
            df = pd.DataFrame(summary_rows, columns=SUMMARY_COLS)

            # Format money columns
            money_cols = ["balance", "pre_balance", "market_value",
                          "deposit_withdraw", "cost", "abs_return", "init_capital"]
            for col in money_cols:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).round(0).astype(int)
                df[col] = df[col].apply(lambda x: f"{x:,}")

            df["instrument_margin_uplimit"] = pd.to_numeric(
                df["instrument_margin_uplimit"], errors="coerce"
            ).fillna(0).apply(lambda x: f"{x:.4f}")
            df["product_low_limit"] = pd.to_numeric(
                df["product_low_limit"], errors="coerce"
            ).fillna(0).apply(lambda x: f"{x:.4f}")

            styled_df = (
                df.style
                  .map(style_product_low_limit,        subset=["product_low_limit"])
                  .map(style_instrument_margin_uplimit, subset=["instrument_margin_uplimit"])
            )

            # ── Render ────────────────────────────────────────
            with placeholder.container():
                st.markdown(
                    """
                    <div style="text-align:center; font-weight:bold; font-size:28px;
                                margin-bottom:12px;">
                        Futures Monitor Dashboard
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                # Global file error banner
                if global_file_errors:
                    st.error(
                        "**Missing / unreadable files:**\n\n"
                        + "\n\n".join(f"- {e}" for e in global_file_errors)
                    )

                # Summary table
                st.subheader("Overview")
                st.dataframe(styled_df, width="stretch")

                # Detail tables (one expander per product)
                st.markdown("---")
                st.subheader("Per-Instrument Detail")

                for prod_name, (cfg, ddf) in detail_map.items():
                    title = (
                        f"[{('cncf' if cfg['futures_type'] == 'commodity' else 'cnif').upper()}] "
                        f"{prod_name}  |  {cfg['broker']}"
                    )
                    with st.expander(title, expanded=False):
                        display_cols = [
                            "instrument", "position",
                            "close_profit", "position_profit", "total_pnl",
                            "instrument_margin", "exchange", "last_trade_time",
                        ]
                        display_ddf = ddf[[c for c in display_cols if c in ddf.columns]].copy()

                        # Rename columns to Chinese / readable labels
                        display_ddf.columns = [
                            "合约名称", "持仓(+多/-空)",
                            "平仓盈亏", "持仓盈亏", "总盈亏",
                            "单合约保证金", "交易所", "最后成交时间",
                        ][:len(display_ddf.columns)]

                        st.dataframe(display_ddf, use_container_width=True)

                        # Show per-instrument warnings if any
                        if "_warnings" in ddf.columns:
                            inst_warns = ddf[ddf["_warnings"].str.len() > 0]
                            if not inst_warns.empty:
                                for _, wr in inst_warns.iterrows():
                                    st.warning(
                                        f"[{wr['instrument']}] {wr['_warnings']}"
                                    )

        except Exception as outer_err:
            with placeholder.container():
                st.error(f"Dashboard loop error: {outer_err}")

        time.sleep(1)


# ─────────────────────────────────────────────

if __name__ == "__main__":
    dashboard()
