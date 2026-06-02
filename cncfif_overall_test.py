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
_price_cache: dict[str, float] = {}

# ── Market-open time windows ──────────────────
COMMODITY_MORNING_OPEN = datetime.time(9,  0)
FUTURES_MORNING_OPEN   = datetime.time(9, 30)
MORNING_CLOSE          = datetime.time(15, 15)
EVENING_OPEN           = datetime.time(21,  0)
EVENING_CLOSE_NEXT_DAY = datetime.time(2,  30)

# ── Product registry ──────────────────────────
PRODUCT_CONFIGS = [
    {
        "path":         "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_data_baguatian",
        "broker":       "Dongzheng",
        "product_name": "Baguatian (AnXin 1Hao)",
        "futures_type": "commodity",
        "init_capital": 0,
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
        "init_capital": 0,
    },
    {
        "path":         "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_jz1h",
        "broker":       "Dongzheng",
        "product_name": "jz1h",
        "futures_type": "futures",
        "init_capital": 0,
    },
    {
        "path":         "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_ly1h",
        "broker":       "Dongzheng",
        "product_name": "ly1h",
        "futures_type": "futures",
        "init_capital": 0,
    },
    {
        "path":         "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_zz1h",
        "broker":       "Zhongxin",
        "product_name": "zz1h",
        "futures_type": "futures",
        "init_capital": 0,
    },
]

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def get_date_from_calendar():
    date     = datetime.datetime.now().date()
    date_int = int(date.strftime("%Y%m%d"))
    date_list = np.loadtxt(CALENDAR_PATH, dtype=np.int64, ndmin=1)
    pos = np.searchsorted(date_list, date_int, side="right")
    next_trade_day = int(date_list[pos])
    return date_int, next_trade_day


def is_market_open(futures_type: str) -> bool:
    now = datetime.datetime.now()
    t   = now.time()

    if futures_type == "commodity":
        in_morning = COMMODITY_MORNING_OPEN <= t <= MORNING_CLOSE
    else:
        in_morning = FUTURES_MORNING_OPEN <= t <= MORNING_CLOSE

    if in_morning:
        return True

    if futures_type == "commodity":
        if t >= EVENING_OPEN or t <= EVENING_CLOSE_NEXT_DAY:
            return True

    return False


def get_previous_trade_date(current_date: int) -> int:
    try:
        date_list = np.loadtxt(CALENDAR_PATH, dtype=np.int64, ndmin=1)
        pos = np.searchsorted(date_list, current_date, side="left")
        if pos > 0:
            return int(date_list[pos - 1])
    except Exception:
        pass
    d = datetime.datetime.strptime(str(current_date), "%Y%m%d")
    d -= datetime.timedelta(days=1)
    return int(d.strftime("%Y%m%d"))


def safe_read_csv(filepath: str) -> tuple[pd.DataFrame | None, str | None]:
    if not os.path.exists(filepath):
        return None, f"File not found: {filepath}"
    if os.path.getsize(filepath) == 0:
        return None, f"File is completely empty (0 bytes): {filepath}"
    try:
        df = pd.read_csv(filepath)
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
    return (
        f"/mnt/nfs_bohr_data1/china/trading_realdata"
        f"/partial_market_data_realtime/{kind}/{current_date}.csv"
    )


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
    for cfg in PRODUCT_CONFIGS:
        if cfg["futures_type"] != futures_type:
            continue
        pd_path = os.path.join(cfg["path"], f"position_data_{current_date}.csv")
        df, err = safe_read_csv(pd_path)
        if err or df is None or df.empty:
            continue
        if "instrument_id" in df.columns and "pre_settlement_price" in df.columns:
            for _, row in df.iterrows():
                inst  = row["instrument_id"]
                price = row.get("pre_settlement_price", 0)
                if inst not in _price_cache and pd.notna(price) and price > 0:
                    _price_cache[inst] = float(price)


def update_price_cache(future_df: pd.DataFrame):
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
    "cost", "abs_return", "pnl_ratio",
    "instrument_margin_uplimit", "product_low_limit",
    "deposit_withdraw", "time", "warnings", "is_market_open",
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
    "pnl_ratio": "0.000%",
    "instrument_margin_uplimit": 0.0,
    "product_low_limit": 0.0,
    "deposit_withdraw": 0,
    "time": "",
    "warnings": "",
    "is_market_open": False,
}


def calculate_product(
    path: str,
    broker: str,
    product_name: str,
    futures_type: str,
    init_capital: float,
    current_date: int,
    market_open: bool,
    shared_sd_df: pd.DataFrame | None,
    shared_future_df: pd.DataFrame | None,
    shared_margin_df: pd.DataFrame | None,
) -> tuple[dict, pd.DataFrame | None]:

    warnings_list: list[str] = []
    data = dict(DEFAULT_SUMMARY)
    data["futures_type"]   = "cncf" if futures_type == "commodity" else "cnif"
    data["product_name"]   = product_name
    data["broker"]         = broker
    data["init_capital"]   = init_capital
    data["time"]           = datetime.datetime.now().strftime("%H:%M:%S")
    data["is_market_open"] = market_open

    # ── Select date ───────────────────────────────────────────
    data_date = current_date
    if not market_open:
        data_date    = get_previous_trade_date(current_date)
        data["time"] = f"{data['time']} (prev day data)"

    # ── 1. account_info ──────────────────────────────────────
    ai_path = os.path.join(path, f"account_info_{data_date}.csv")
    ai_df, ai_err = safe_read_csv(ai_path)
    if ai_err:
        warnings_list.append(ai_err)
        data["warnings"] = " | ".join(warnings_list)
        return data, None
    if ai_df.empty:
        warnings_list.append(f"Header-only file (using defaults): {ai_path}")
        balance = pre_balance = deposit = withdraw = fee = 0.0
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
    pd_path = os.path.join(path, f"position_data_{data_date}.csv")
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
        pnl_ratio = round((data["abs_return"] - fee) / pnl_denominator * 100, 3)
    else:
        pnl_ratio = 0.0
    data["pnl_ratio"] = f"{pnl_ratio:.3f}%"

    sd_df     = shared_sd_df
    future_df = shared_future_df
    margin_df = shared_margin_df

    # ── 4. Per-instrument calculations ───────────────────────
    market_value          = 0.0
    total_market_value    = 0.0  # [新增] 用于 product_low_limit
    instrument_margin_max = 0.0
    detail_rows: list[dict] = []

    instruments = (
        pd_df["instrument_id"].dropna().unique().tolist()
        if not pd_df.empty else []
    )

    # Load trade file for last-trade-time lookup
    trade_path = get_trade_file_path(path, data_date)
    trade_df, trade_err = safe_read_csv(trade_path)
    if trade_err:
        warnings_list.append(trade_err)
        trade_df = None

    for inst in instruments:
        inst_warnings: list[str] = []

        # ── Raw positions
        long_rows  = pd_df.query(f"instrument_id == '{inst}' and pos_type == 'LONG'")
        short_rows = pd_df.query(f"instrument_id == '{inst}' and pos_type == 'SHORT'")
        long_pos   = float(long_rows["position"].iloc[0])  if not long_rows.empty  else 0.0
        short_pos  = float(short_rows["position"].iloc[0]) if not short_rows.empty else 0.0

        # ── Net position
        net_pos = long_pos - short_pos

        # ── Dominant position for margin
        margin_pos = max(long_pos, short_pos)

        # ── PnL components
        cp        = float(pd_df[pd_df["instrument_id"] == inst]["close_profit"].fillna(0).sum())
        pp        = float(pd_df[pd_df["instrument_id"] == inst]["position_profit"].fillna(0).sum())
        total_pnl = cp + pp

        # ── Static info
        multiplier = 1.0
        exchange   = ""
        if sd_df is not None and not sd_df.empty:
            sd_row = sd_df[sd_df["instrument"] == inst]
            if not sd_row.empty:
                multiplier = float(sd_row["multiplier"].iloc[0])
                exchange   = (
                    str(sd_row["exchange"].iloc[0])
                    if "exchange" in sd_row.columns else ""
                )
            else:
                inst_warnings.append(f"no static info for {inst}")
        else:
            inst_warnings.append(f"static info file unavailable for {inst}")

        # ── Margin ratio
        margin_ratio = 0.0
        if margin_df is not None and not margin_df.empty:
            m_row = margin_df[margin_df["instrument"] == inst]
            if not m_row.empty:
                margin_ratio = float(m_row["margin_ratio"].iloc[0])

        # ── Price
        price = get_price(inst)
        if price is None:
            inst_warnings.append(f"no price available for {inst} (using 0)")
            price = 0.0

        # ── Market value: use NET position
        market_value += net_pos * price * multiplier

        # ── Total market value: use TOTAL position (long + short) [新增]
        total_market_value += (long_pos + short_pos) * price * multiplier

        # ── Per-instrument margin: use DOMINANT position side
        inst_margin           = price * margin_pos * multiplier * margin_ratio
        instrument_margin_max = max(inst_margin, instrument_margin_max)

        # ── Last trade time
        last_trade_time = ""
        if trade_df is not None and not trade_df.empty:
            inst_col = (
                trade_df.get("instrument_id", None)
                if "instrument_id" in trade_df.columns
                else trade_df.get("instrument", None)
            )
            if inst_col is not None:
                t_rows = trade_df[inst_col == inst]
                if not t_rows.empty:
                    time_col = (
                        "trade_time"  if "trade_time"  in t_rows.columns else
                        "update_time" if "update_time" in t_rows.columns else
                        None
                    )
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
        total_market_value / balance if balance > 0 else 0.0  # [改] 用 total_market_value
    )
    data["instrument_margin_uplimit"] = (
        instrument_margin_max / balance if balance > 0 else 0.0
    )
    data["warnings"] = " | ".join(warnings_list)

    detail_df = pd.DataFrame(detail_rows) if detail_rows else None
    return data, detail_df


# ─────────────────────────────────────────────
# SHARED FILE LOADER
# ─────────────────────────────────────────────

def load_shared_files(
    futures_type: str,
    path: str,
    current_date: int,
    market_open: bool,
) -> tuple[pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None, list[str]]:
    errors: list[str] = []
    data_date = current_date if market_open else get_previous_trade_date(current_date)

    sd_path = get_static_info_path(futures_type)
    sd_df, e = safe_read_csv(sd_path)
    if e:
        errors.append(e)

    mkt_path = get_market_data_path(futures_type, data_date)
    future_df, e = safe_read_csv(mkt_path)
    if e:
        errors.append(e)
    else:
        update_price_cache(future_df)

    margin_path = get_margin_file_path(path, futures_type, data_date)
    margin_df, e = safe_read_csv(margin_path) if margin_path else (None, None)
    if e:
        errors.append(e)

    return sd_df, future_df, margin_df, errors


# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────

def dashboard():
    st.set_page_config(page_title="Futures Monitor Dashboard", layout="wide")

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

            summary_rows: list[dict]       = []
            detail_map:   dict[str, tuple] = {}
            global_file_errors: list[str]  = []
            shared_cache: dict[str, tuple] = {}

            for cfg in PRODUCT_CONFIGS:
                ft   = cfg["futures_type"]
                path = cfg["path"]
                name = cfg["product_name"]

                market_open = is_market_open(ft)

                if ft not in shared_cache:
                    sd_df, future_df, _dummy_margin, errs = load_shared_files(
                        ft, path, current_date, market_open
                    )
                    shared_cache[ft] = (sd_df, future_df, errs)
                    global_file_errors.extend(errs)

                sd_df, future_df, _shared_errs = shared_cache[ft]

                margin_path = get_margin_file_path(path, ft, current_date)
                margin_df, m_err = safe_read_csv(margin_path) if margin_path else (None, None)
                if m_err:
                    global_file_errors.append(m_err)

                try:
                    row, detail_df = calculate_product(
                        path             = path,
                        broker           = cfg["broker"],
                        product_name     = name,
                        futures_type     = ft,
                        init_capital     = cfg["init_capital"],
                        current_date     = current_date,
                        market_open      = market_open,
                        shared_sd_df     = sd_df,
                        shared_future_df = future_df,
                        shared_margin_df = margin_df,
                    )
                except Exception as calc_err:
                    row = dict(DEFAULT_SUMMARY)
                    row.update({
                        "futures_type":  "cncf" if ft == "commodity" else "cnif",
                        "product_name":  name,
                        "broker":        cfg["broker"],
                        "init_capital":  cfg["init_capital"],
                        "time":          now.strftime("%H:%M:%S"),
                        "warnings":      f"Calculation error: {calc_err}",
                        "is_market_open": market_open,
                    })
                    detail_df = None

                summary_rows.append(row)
                if detail_df is not None:
                    detail_map[name] = (cfg, detail_df)

                # Alert only during trading hours
                if market_open:
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

            # ── Build overview DataFrame ───────────────────────────
            df = pd.DataFrame(summary_rows, columns=SUMMARY_COLS)

            money_cols = [
                "balance", "pre_balance", "market_value",
                "deposit_withdraw", "cost", "abs_return", "init_capital",
            ]
            for col in money_cols:
                df[col] = (
                    pd.to_numeric(df[col], errors="coerce")
                    .fillna(0).round(0).astype(int)
                    .apply(lambda x: f"{x:,}")
                )

            df["instrument_margin_uplimit"] = (
                pd.to_numeric(df["instrument_margin_uplimit"], errors="coerce")
                .fillna(0).apply(lambda x: f"{x:.4f}")
            )
            df["product_low_limit"] = (
                pd.to_numeric(df["product_low_limit"], errors="coerce")
                .fillna(0).apply(lambda x: f"{x:.4f}")
            )

            display_df = df.drop(columns=["is_market_open"])
            styled_df = (
                display_df.style
                .map(style_product_low_limit,        subset=["product_low_limit"])
                .map(style_instrument_margin_uplimit, subset=["instrument_margin_uplimit"])
            )

            # ── Render ────────────────────────────────────────────
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

                st.markdown("---")
                st.subheader("Trading Summary")
                summary_table = build_summary_table(df)
                st.dataframe(summary_table, use_container_width=True)

                if global_file_errors:
                    st.error(
                        "**Missing / unreadable files:**\n\n"
                        + "\n\n".join(f"- {e}" for e in global_file_errors)
                    )

                st.subheader("Overview")
                st.dataframe(styled_df, use_container_width=True)

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
                        display_ddf = ddf[
                            [c for c in display_cols if c in ddf.columns]
                        ].copy()

                        display_ddf.columns = [
                            "合约名称", "持仓(+多/-空)",
                            "平仓盈亏", "持仓盈亏", "总盈亏",
                            "单合约保证金", "交易所", "最后成交时间",
                        ][: len(display_ddf.columns)]

                        st.dataframe(display_ddf, use_container_width=True)

                        if "_warnings" in ddf.columns:
                            inst_warns = ddf[ddf["_warnings"].str.len() > 0]
                            if not inst_warns.empty:
                                for _, wr in inst_warns.iterrows():
                                    st.warning(f"[{wr['instrument']}] {wr['_warnings']}")

        except Exception as outer_err:
            with placeholder.container():
                st.error(f"Dashboard loop error: {outer_err}")

        time.sleep(1)


# ─────────────────────────────────────────────
# BUILD SUMMARY TABLE
# ─────────────────────────────────────────────

def build_summary_table(df: pd.DataFrame) -> pd.DataFrame:
    summary_rows = []

    df_numeric = df.copy()
    for col in ["balance", "pre_balance", "init_capital", "cost", "abs_return", "market_value"]:
        if col in df_numeric.columns:
            df_numeric[col] = pd.to_numeric(
                df_numeric[col].astype(str).str.replace(",", ""),
                errors="coerce",
            ).fillna(0)

    def _build_row(label: str, subset: pd.DataFrame) -> dict:
        aum = subset["init_capital"].sum()
        if aum == 0:
            aum = subset["pre_balance"].sum()
        cost        = subset["cost"].sum()
        abs_return  = subset["abs_return"].sum()
        total_pnl   = abs_return - cost
        pnl_pct     = (total_pnl / aum * 100) if aum > 0 else 0.0
        return {
            "summary":    label,
            "aum":        int(aum),
            "cost":       int(cost),
            "abs_return": int(abs_return),
            "total_pnl":  int(total_pnl),
            "pnl_ratio":  f"{pnl_pct:.3f}%",
        }

    cncf_data = df_numeric[df_numeric["futures_type"] == "cncf"]
    cnif_data = df_numeric[df_numeric["futures_type"] == "cnif"]

    if not cncf_data.empty:
        summary_rows.append(_build_row("cncf", cncf_data))
    if not cnif_data.empty:
        summary_rows.append(_build_row("cnif", cnif_data))
    summary_rows.append(_build_row("cn_all", df_numeric))

    summary_df = pd.DataFrame(summary_rows)
    for col in ["aum", "cost", "abs_return", "total_pnl"]:
        summary_df[col] = summary_df[col].apply(lambda x: f"{x:,}")

    return summary_df


# ─────────────────────────────────────────────

if __name__ == "__main__":
    dashboard()
