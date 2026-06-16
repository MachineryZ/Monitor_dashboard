import os
import time
import math
import requests
import json
import datetime
import pandas as pd
import numpy as np
import streamlit as st
from typing import List

# ─────────────────────────────────────────────
# CONSTANTS & CONFIGURATION
# ─────────────────────────────────────────────

CALENDAR_PATH = "/cpfs/intrastats/calendar"

_price_cache: dict[str, float] = {}

# ── 商品期货 (commodity / cncf) 交易时段 ─────
COMMODITY_SESSIONS = [
    (datetime.time(9,  0),  datetime.time(10, 15), False),
    (datetime.time(10, 30), datetime.time(11, 30), False),
    (datetime.time(13, 30), datetime.time(15,  0), False),
    (datetime.time(21,  0), datetime.time(2,  30), True ),
]

# ── 股指期货 (futures / cnif) 交易时段 ────────
FUTURES_SESSIONS = [
    (datetime.time(9,  30), datetime.time(11, 30), False),
    (datetime.time(13,  0), datetime.time(15,  0), False),
]

# ── Product registry ──────────────────────────
PRODUCT_CONFIGS = [
    {
        "path":         "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_data_baguatian",
        "broker":       "dz",
        "product":      "bgt_ax1h",
        "market":       "commodity",
        "init_capital": 0,
        "aum_mul":      4.0,
        "db_product":   "commodity_melt_bgt",
    },
    {
        "path":         "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_data_shjq_zx",
        "broker":       "zx",
        "product":      "shjq",
        "market":       "commodity",
        "init_capital": 0,
        "db_product":   "cncf_melt_shjq_zx",
    },
    {
        "path":         "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_data_shph1h_zx",
        "broker":       "zx",
        "product":      "shph1h",
        "market":       "commodity",
        "init_capital": 0,
        "db_product":   "commodity_melt_shph_zx",
    },
    {
        "path":         "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_date",
        "broker":       "zx",
        "product":      "zz1h",
        "market":       "commodity",
        "init_capital": 0,
        "aum_formula":  lambda pb, bal: 25_000_000 + (bal - 6_000_000),
        "db_product":   "commodity_melt",
    },
    {
        "path":         "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_jz1h",
        "broker":       "dz",
        "product":      "jz1h",
        "market":       "futures",
        "init_capital": 0,
        "aum_mul":      4.0,
        "db_product":   None,
    },
    {
        "path":         "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_ly1h",
        "broker":       "dz",
        "product":      "ly1h",
        "market":       "futures",
        "init_capital": 0,
        "aum_mul":      5.0,
        "db_product":   None,
    },
    {
        "path":         "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_zz1h",
        "broker":       "zx",
        "product":      "zz1h",
        "market":       "futures",
        "init_capital": 0,
        "aum_mul":      4.7858,
        "db_product":   None,
    },
]


# ─────────────────────────────────────────────
# CLICKHOUSE CLIENT & 数据库查询函数
# ─────────────────────────────────────────────

_ch_client = None

def get_ch_client():
    global _ch_client
    if _ch_client is None:
        try:
            from clickhouse_connect.driver import create_client
            _ch_client = create_client(
                host='10.51.4.21',
                port=8123,
                username='dashboard',
                password='123456',
                database='cffex_zx'
            )
        except Exception as e:
            return None
    return _ch_client


def get_product_clip(product_name: str) -> int | None:
    if not product_name:
        return None
    client = get_ch_client()
    if client is None:
        return None
    query = f"""
        SELECT clip
        FROM commodity_meta.product_clip
        WHERE product_name = '{product_name}'
        LIMIT 1
    """
    try:
        result = client.query_df(query)
        if not result.empty:
            return int(result.iloc[0]["clip"])
        return None
    except Exception:
        return None


def get_product_uplimit_coef(product_name: str) -> float | None:
    if not product_name:
        return None
    client = get_ch_client()
    if client is None:
        return None
    query = f"""
        SELECT coef
        FROM commodity_meta.product_uplimit_coef
        WHERE product_name = 'all'
        LIMIT 1
    """
    try:
        result = client.query_df(query)
        if not result.empty:
            return float(result.iloc[0]["coef"])
        return None
    except Exception:
        return None


# ─────────────────────────────────────────────
# uplimit_holding_position
# ─────────────────────────────────────────────

def load_uplimit_holding_position() -> dict[str, float] | None:
    csv_path = "/cpfs/rawdata/cncf_all_nedd_before_open/margin_uplimit_include_ine.csv"
    uplimit_data = {}
    try:
        df, err = safe_read_csv(csv_path)
        if err or df is None or df.empty:
            return None
        if "instrument" not in df.columns or "up_limit_holding_position" not in df.columns:
            return None
        for idx, row in df.iterrows():
            try:
                inst = str(row["instrument"]).strip()
                uplimit_hp_raw = row.get("up_limit_holding_position", 0)
                if inst:
                    try:
                        uplimit_hp = float(uplimit_hp_raw)
                        uplimit_data[inst] = uplimit_hp
                    except (ValueError, TypeError):
                        continue
            except Exception:
                continue
        return uplimit_data if uplimit_data else None
    except Exception:
        import traceback
        traceback.print_exc()
        return None


def calculate_uplimit(instrument: str, product_name: str,
                      uplimit_data: dict[str, float] | None) -> float | None:
    coef = get_product_uplimit_coef(product_name) or 1
    if uplimit_data is None:
        return None
    if instrument not in uplimit_data:
        return None
    uplimit_hp = uplimit_data[instrument]
    try:
        return uplimit_hp * coef
    except Exception:
        return None


# ─────────────────────────────────────────────
# AUM RESOLVER
# ─────────────────────────────────────────────

def resolve_init_capital(cfg: dict, pre_balance: float, balance: float) -> float:
    formula = cfg.get("aum_formula")
    if formula is not None:
        return float(formula(pre_balance, balance))
    aum_mul = cfg.get("aum_mul")
    if aum_mul is not None:
        return float(pre_balance * aum_mul)
    ic = float(cfg.get("init_capital", 0))
    if ic > 0:
        return ic
    return float(pre_balance)


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def get_date_from_calendar() -> tuple[int, int]:
    date     = datetime.datetime.now().date()
    date_int = int(date.strftime("%Y%m%d"))
    date_list = np.loadtxt(CALENDAR_PATH, dtype=np.int64, ndmin=1)
    pos = np.searchsorted(date_list, date_int, side="right")
    next_trade_day = int(date_list[pos])
    return date_int, next_trade_day


def _time_in_session(t: datetime.time, start: datetime.time,
                     end: datetime.time, crosses_midnight: bool) -> bool:
    if crosses_midnight:
        return t >= start or t <= end
    else:
        return start <= t <= end


def is_commodity_night_session_pre_midnight(t: datetime.time) -> bool:
    return t >= datetime.time(21, 0)


def is_market_open(market: str) -> bool:
    t = datetime.datetime.now().time()
    sessions = COMMODITY_SESSIONS if market == "commodity" else FUTURES_SESSIONS
    return any(_time_in_session(t, s, e, cross) for s, e, cross in sessions)


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


def get_next_trade_date(current_date: int) -> int:
    try:
        date_list = np.loadtxt(CALENDAR_PATH, dtype=np.int64, ndmin=1)
        pos = np.searchsorted(date_list, current_date, side="right")
        if pos < len(date_list):
            return int(date_list[pos])
    except Exception:
        pass
    d = datetime.datetime.strptime(str(current_date), "%Y%m%d")
    d += datetime.timedelta(days=1)
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


def file_exists_for_date(path: str, date_int: int) -> bool:
    fp = os.path.join(path, f"account_info_{date_int}.csv")
    return os.path.exists(fp) and os.path.getsize(fp) > 0


def _extract_latest_update_time(*dfs: pd.DataFrame | None) -> str:
    candidates: list[str] = []
    for df in dfs:
        if df is None or df.empty:
            continue
        if "update_time" not in df.columns:
            continue
        col = df["update_time"].dropna().astype(str)
        col = col[col.str.strip() != ""]
        if col.empty:
            continue
        candidates.append(col.max())
    return max(candidates) if candidates else ""


# ─────────────────────────────────────────────
# get_data_date
# ─────────────────────────────────────────────

def get_data_date(
    market: str,
    path: str,
    current_date: int,
    market_open: bool,
) -> tuple[int, str]:
    now = datetime.datetime.now()
    t   = now.time()
    if market_open:
        if market == "commodity" and is_commodity_night_session_pre_midnight(t):
            next_td = get_next_trade_date(current_date)
            return next_td, f" (night→{next_td})"
        return current_date, ""
    if file_exists_for_date(path, current_date):
        return current_date, " (today data)"
    prev = get_previous_trade_date(current_date)
    return prev, " (prev day data)"


# ─────────────────────────────────────────────
# PATH HELPERS
# ─────────────────────────────────────────────

def get_margin_file_path(path: str, market: str, data_date: int) -> str:
    if market == "commodity":
        return "/cpfs/rawdata/cncf_all_nedd_before_open/margin_uplimit_include_ine.csv"
    mapping = {
        "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_jz1h":
            f"/cpfs/rawdata/cnif_all_need_before_open/margin_uplimit_jz1h_{data_date}.csv",
        "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_ly1h":
            f"/cpfs/rawdata/cnif_all_need_before_open/margin_uplimit_ly1h_{data_date}.csv",
        "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_zz1h":
            f"/cpfs/rawdata/cnif_all_need_before_open/margin_uplimit_zz1h_{data_date}.csv",
    }
    return mapping.get(path, "")


def get_static_info_path(market: str) -> str:
    if market == "commodity":
        return "/cpfs/rawdata/cncf_all_nedd_before_open/ins_static_info.csv"
    return "/cpfs/rawdata/cnif_all_need_before_open/ins_static_info.csv"


def get_market_data_path(market: str, data_date: int) -> str:
    kind = "commodity" if market == "commodity" else "futures"
    return (
        f"/mnt/nfs_bohr_data1/china/trading_realdata"
        f"/partial_market_data_realtime/{kind}/{data_date}.csv"
    )


def get_trade_file_path(path: str, data_date: int) -> str:
    return os.path.join(path, f"trade_data_{data_date}.csv")


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

def init_price_cache(market: str, current_date: int):
    for cfg in PRODUCT_CONFIGS:
        if cfg["market"] != market:
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
# RISK POSITION LOADER
# ─────────────────────────────────────────────

def load_risk_position(market: str, product: str, data_date: int) -> dict[str, float] | None:
    result = {}
    if market == "commodity":
        strategy_mapping = {
            "bgt_ax1h": "cncf_melt_bgt_dz_bohr",
            "shjq": "cncf_melt_shjq_zx_bohr",
            "shph1h": "cncf_melt_shph1h_zx_bohr",
            "zz1h": "cncf_melt_zhizeng_dz_bohr",
        }
        if product not in strategy_mapping:
            return None
        dir_name = strategy_mapping[product]
        csv_path = f"/cpfs/prod/prod_log/china_future/cncf/{dir_name}/{data_date}.csv"
        df, err = safe_read_csv(csv_path)
        if err or df is None or df.empty:
            return None
        for _, row in df.iterrows():
            try:
                inst = str(row.get("instrument", "")).strip()
                all_stats_str = str(row.get("all_stats", "")).strip().strip("[]").strip()
                if all_stats_str:
                    value = float(all_stats_str)
                    if inst:
                        result[inst] = value
            except (ValueError, TypeError, AttributeError):
                continue
    elif market == "futures":
        strategy_mapping = {
            "jz1h": "cnif_short_jz1h_dz_dashboard_bohr",
            "ly1h": "cnif_position_melt_ly1h_dz_dashboard_bohr",
            "zz1h": "cnif_short_zz1h_zx_dashboard_bohr",
        }
        if product not in strategy_mapping:
            return None
        dir_name = strategy_mapping[product]
        csv_path = f"/cpfs/prod/prod_log/china_future/cnif/{dir_name}/{data_date}.csv"
        df, err = safe_read_csv(csv_path)
        if err or df is None or df.empty:
            return None
        for _, row in df.iterrows():
            try:
                inst = str(row.get("instrument", "")).strip()
                value = float(row.get("value", 0))
                if inst:
                    result[inst] = value
            except (ValueError, TypeError):
                continue
    return result if result else None


# ─────────────────────────────────────────────
# ★ NEW: TRADE STATS CALCULATOR
# ─────────────────────────────────────────────

# trade_data CSV 中常见的字段名别名映射
# direction:    'B'=买 / 'S'=卖
# offset_flag:  'O'=开 / 'C'=平 / 'CT'=平今（均归类为"平"）
_DIRECTION_COL_CANDIDATES  = ["direction",    "Direction",    "trade_direction"]
_OFFSET_COL_CANDIDATES     = ["offset_flag",  "OffsetFlag",   "offset",         "Offset"]
_VOLUME_COL_CANDIDATES     = ["volume",        "Volume",       "trade_volume",   "TradeVolume"]
_PRICE_COL_CANDIDATES      = ["price",         "Price",        "trade_price",    "TradePrice"]
_INST_COL_CANDIDATES       = ["instrument_id", "InstrumentID", "instrument",     "Instrument"]


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """在 df.columns 中找第一个匹配的候选列名"""
    for c in candidates:
        if c in df.columns:
            return c
    return None


def calculate_trade_stats(
    trade_df: pd.DataFrame | None,
    inst: str,
    multiplier: float,
) -> dict:
    """
    从 trade_data DataFrame 中，针对单个合约 inst 计算 8 个交易统计值。

    字段定义：
      BuyOpenNumber      : 买开手数  = 方向为 B 且 offset 为 O 的成交手数合计
      BuyOpenMarketValue : 买开市值  = sum(买开成交价 × 手数 × 乘数)
      BuyCloseNumber     : 买平手数  = 方向为 B 且 offset 为 C/CT 的成交手数合计
      BuyCloseMarketValue: 买平市值  = sum(买平成交价 × 手数 × 乘数)
      SellOpenNumber     : 卖开手数  = 方向为 S 且 offset 为 O 的成交手数合计
      SellOpenMarketValue: 卖开市值  = sum(卖开成交价 × 手数 × 乘数)
      SellCloseNumber    : 卖平手数  = 方向为 S 且 offset 为 C/CT 的成交手数合计
      SellCloseMarketValue:卖平市值  = sum(卖平成交价 × 手数 × 乘数)

    Args:
        trade_df   : trade_data_{date}.csv 对应的 DataFrame（可为 None）
        inst       : 合约代码
        multiplier : 合约乘数（来自 ins_static_info）

    Returns:
        包含 8 个键的 dict，默认值均为 0
    """
    zero = {
        "BuyOpenNumber":       0,
        "BuyOpenMarketValue":  0,
        "BuyCloseNumber":      0,
        "BuyCloseMarketValue": 0,
        "SellOpenNumber":      0,
        "SellOpenMarketValue": 0,
        "SellCloseNumber":     0,
        "SellCloseMarketValue":0,
    }

    if trade_df is None or trade_df.empty:
        return zero

    # ── 找列名 ────────────────────────────────────────────────
    inst_col   = _find_col(trade_df, _INST_COL_CANDIDATES)
    dir_col    = _find_col(trade_df, _DIRECTION_COL_CANDIDATES)
    offset_col = _find_col(trade_df, _OFFSET_COL_CANDIDATES)
    vol_col    = _find_col(trade_df, _VOLUME_COL_CANDIDATES)
    price_col  = _find_col(trade_df, _PRICE_COL_CANDIDATES)

    # 任意必要列缺失则返回零值
    if any(c is None for c in [inst_col, dir_col, offset_col, vol_col, price_col]):
        return zero

    # ── 筛选当前合约行 ─────────────────────────────────────────
    rows = trade_df[trade_df[inst_col].astype(str).str.strip() == str(inst).strip()].copy()
    if rows.empty:
        return zero

    # ── 标准化列值 ────────────────────────────────────────────
    rows["_dir"]    = rows[dir_col].astype(str).str.strip().str.upper()
    rows["_offset"] = rows[offset_col].astype(str).str.strip().str.upper()
    rows["_vol"]    = pd.to_numeric(rows[vol_col],   errors="coerce").fillna(0)
    rows["_price"]  = pd.to_numeric(rows[price_col], errors="coerce").fillna(0)
    rows["_mv"]     = rows["_price"] * rows["_vol"] * multiplier

    # offset 归类：O=开仓  C/CT=平仓
    is_open  = rows["_offset"] == "O"
    is_close = rows["_offset"].isin(["C", "CT"])
    is_buy   = rows["_dir"] == "B"
    is_sell  = rows["_dir"] == "S"

    result = {
        "BuyOpenNumber":        int(rows.loc[is_buy  & is_open,  "_vol"].sum()),
        "BuyOpenMarketValue":   round(rows.loc[is_buy  & is_open,  "_mv"].sum(), 2),
        "BuyCloseNumber":       int(rows.loc[is_buy  & is_close, "_vol"].sum()),
        "BuyCloseMarketValue":  round(rows.loc[is_buy  & is_close, "_mv"].sum(), 2),
        "SellOpenNumber":       int(rows.loc[is_sell & is_open,  "_vol"].sum()),
        "SellOpenMarketValue":  round(rows.loc[is_sell & is_open,  "_mv"].sum(), 2),
        "SellCloseNumber":      int(rows.loc[is_sell & is_close, "_vol"].sum()),
        "SellCloseMarketValue": round(rows.loc[is_sell & is_close, "_mv"].sum(), 2),
    }
    return result


def aggregate_trade_stats(detail_rows: list[dict]) -> dict:
    """
    将若干 detail_row 中的 8 个 trade stats 字段求和，用于 overview 行级聚合。
    """
    keys = [
        "BuyOpenNumber", "BuyOpenMarketValue",
        "BuyCloseNumber", "BuyCloseMarketValue",
        "SellOpenNumber", "SellOpenMarketValue",
        "SellCloseNumber", "SellCloseMarketValue",
    ]
    agg = {k: 0 for k in keys}
    for row in detail_rows:
        for k in keys:
            agg[k] += row.get(k, 0)
    return agg


# ─────────────────────────────────────────────
# STYLERS
# ─────────────────────────────────────────────

def style_product_low_limit(row: pd.Series) -> list[str]:
    styles = [""] * len(row)
    if "product_low_limit" not in row.index:
        return styles
    col_idx = row.index.get_loc("product_low_limit")
    try:
        val = float(row["product_low_limit"])
        if val < 0.8:
            if row.get("product", "") == "ly1h":
                styles[col_idx] = "background-color: #ffd700; color: black"
            else:
                styles[col_idx] = "background-color: #ff4b4b; color: white"
    except (ValueError, TypeError):
        pass
    return styles


def style_max_margin(val):
    try:
        if float(val.rstrip('%')) / 100 > 0.25:
            return "background-color: #ff4b4b; color: white"
    except (ValueError, TypeError):
        pass
    return ""


# ─────────────────────────────────────────────
# SUMMARY_COLS & DEFAULT_SUMMARY  ★ 新增 8 列
# ─────────────────────────────────────────────

SUMMARY_COLS = [
    "market", "product", "broker",
    "init_capital",
    "balance", "pre_balance", "market_value",
    "cost", "net_return", "fee", "pnl",
    "max_margin", "product_low_limit",
    "margin", "margin_ratio",
    # ★ 8 new trade-stat columns
    "BuyOpenNumber",       "BuyOpenMarketValue",
    "BuyCloseNumber",      "BuyCloseMarketValue",
    "SellOpenNumber",      "SellOpenMarketValue",
    "SellCloseNumber",     "SellCloseMarketValue",
    "update_time", "time", "warnings", "deposit_withdraw", "is_market_open",
]

DEFAULT_SUMMARY = {
    "market": "",
    "product": "",
    "broker": "",
    "init_capital": 0,
    "balance": 0,
    "pre_balance": 0,
    "market_value": 0,
    "cost": 0,
    "net_return": 0,
    "fee": "0.000%",
    "pnl": "0.000%",
    "max_margin": 0.0,
    "product_low_limit": 0.0,
    "margin": 0.0,
    "margin_ratio": "0.000%",
    # ★ 8 new defaults
    "BuyOpenNumber":        0,
    "BuyOpenMarketValue":   0,
    "BuyCloseNumber":       0,
    "BuyCloseMarketValue":  0,
    "SellOpenNumber":       0,
    "SellOpenMarketValue":  0,
    "SellCloseNumber":      0,
    "SellCloseMarketValue": 0,
    "deposit_withdraw": 0,
    "time": "",
    "warnings": "",
    "is_market_open": False,
}


# ─────────────────────────────────────────────
# _get_last_trade_time_adjusted
# ─────────────────────────────────────────────

def _get_last_trade_time_adjusted(
    trade_df: pd.DataFrame | None,
    inst: str,
    data_date: int,
    current_date: int,
    market: str,
) -> str:
    if trade_df is None or trade_df.empty:
        return ""

    inst_col = (
        "instrument_id" if "instrument_id" in trade_df.columns
        else ("instrument" if "instrument" in trade_df.columns else None)
    )
    if inst_col is None:
        return ""

    t_rows = trade_df[trade_df[inst_col] == inst]
    if t_rows.empty:
        return ""

    time_col = (
        "trade_time"  if "trade_time"  in t_rows.columns else
        "update_time" if "update_time" in t_rows.columns else None
    )
    if time_col is None:
        return ""

    try:
        trade_time_raw = t_rows[time_col].iloc[-1]
        trade_time_str = str(trade_time_raw).strip()

        if not trade_time_str or trade_time_str.lower() == "nan":
            prev_date = get_previous_trade_date(data_date)
            return f"{prev_date} 20:00:00"

        if ':' in trade_time_str:
            time_part = trade_time_str.split()[-1]
        else:
            time_part = trade_time_str[-6:] if len(trade_time_str) >= 6 else trade_time_str
            time_part = f"{time_part[0:2]}:{time_part[2:4]}:{time_part[4:6]}"

        hour = int(time_part[:2])
        if hour >= 21:
            prev_date = get_previous_trade_date(data_date)
            return f"{prev_date} {time_part}"
        else:
            return f"{data_date} {time_part}"

    except (ValueError, IndexError, AttributeError):
        pass

    return str(trade_time_str)


def _check_risk_position_match(
    long_pos: float | None,
    short_pos: float | None,
    risk_pos: float | None,
) -> str:
    long_int  = int(round(long_pos))  if long_pos  is not None else 0
    short_int = int(round(short_pos)) if short_pos is not None else 0
    risk_int  = int(round(risk_pos))  if risk_pos  is not None else 0
    net_pos   = long_int - short_int
    return "red" if net_pos != risk_int else "matched"


# ─────────────────────────────────────────────
# CORE: calculate_product  ★ 新增 8 列计算
# ─────────────────────────────────────────────

def calculate_product(
    cfg: dict,
    path: str,
    broker: str,
    product: str,
    market: str,
    current_date: int,
    market_open: bool,
    shared_sd_df: pd.DataFrame | None,
    shared_future_df: pd.DataFrame | None,
    shared_margin_df: pd.DataFrame | None,
) -> tuple[dict, pd.DataFrame | None, dict]:

    warnings_list: list[str] = []
    data = dict(DEFAULT_SUMMARY)
    data["market"]         = "cncf" if market == "commodity" else "cnif"
    data["product"]        = product
    data["broker"]         = broker
    data["time"]           = datetime.datetime.now().strftime("%H:%M:%S")
    data["is_market_open"] = market_open

    data_date, time_suffix = get_data_date(market, path, current_date, market_open)
    data["time"] += time_suffix

    # ── 1. account_info ──────────────────────────────────────
    ai_path = os.path.join(path, f"account_info_{data_date}.csv")
    ai_df, ai_err = safe_read_csv(ai_path)
    if ai_err:
        warnings_list.append(ai_err)
        data["init_capital"] = 0
        data["warnings"]     = " | ".join(warnings_list)
        return data, None, {"has_warning": True, "has_risk": False}

    if ai_df.empty:
        warnings_list.append(f"Header-only file (using defaults): {ai_path}")
        balance = pre_balance = deposit = withdraw = fee = 0.0
        margin = 0.0
    else:
        try:
            balance      = float(ai_df["balance"].iloc[0])
            pre_balance  = float(ai_df["pre_balance"].iloc[0])
            deposit      = float(ai_df["deposit"].iloc[0])
            withdraw     = float(ai_df["withdraw"].iloc[0])
            fee          = float(ai_df["fee"].iloc[0])
            margin       = float(ai_df["curr_margin"].iloc[0])
            margin_ratio = margin / pre_balance if pre_balance > 0 else 0
        except Exception as e:
            warnings_list.append(f"account_info parsing error: {e}")
            balance = pre_balance = fee = margin = 0.0
            margin_ratio = 0

    data["margin_ratio"]    = f"{100*margin_ratio:.2f}%"
    data["balance"]         = balance
    data["pre_balance"]     = pre_balance
    data["deposit_withdraw"]= deposit - withdraw
    data["cost"]            = fee
    data["margin"]          = margin
    init_capital = resolve_init_capital(cfg, pre_balance, balance)
    data["init_capital"]    = init_capital

    # ── 2. position_data ─────────────────────────────────────
    pd_path = os.path.join(path, f"position_data_{data_date}.csv")
    pd_df, pd_err = safe_read_csv(pd_path)
    if pd_err:
        warnings_list.append(pd_err)
        data["warnings"] = " | ".join(warnings_list)
        return data, None, {"has_warning": True, "has_risk": False}

    if pd_df.empty:
        warnings_list.append(f"Header-only file (using defaults): {pd_path}")
        pd_df = pd.DataFrame(columns=[
            "instrument_id", "pos_type", "position",
            "position_profit", "close_profit", "pre_settlement_price",
        ])

    try:
        abs_return = float(
            (pd_df.get("position_profit", pd.Series([0])).fillna(0)
             + pd_df.get("close_profit",  pd.Series([0])).fillna(0)).sum()
        )
    except Exception as e:
        warnings_list.append(f"PnL calculation error: {e}")
        abs_return = 0.0

    # ── 3. net_return / fee ───────────────────────────────────
    data["net_return"] = abs_return - fee
    data["fee"] = f"{(fee/init_capital)*100:.3f}%" if init_capital > 0 else "0.000%"

    # ── 4. PnL ───────────────────────────────────────────────
    pnl = round(data["net_return"] / init_capital * 100, 3) if init_capital > 0 else 0.0
    data["pnl"] = f"{pnl:.3f}%"

    sd_df     = shared_sd_df
    future_df = shared_future_df
    margin_df = shared_margin_df

    # ── 5. risk_position / clip / uplimit ─────────────────────
    risk_position_map = load_risk_position(market, product, data_date)
    db_product = cfg.get("db_product")
    clip = get_product_clip(db_product) if db_product else None
    uplimit_holding_position_data = None
    if market == "commodity":
        uplimit_holding_position_data = load_uplimit_holding_position()

    # ── 6. trade_data ─────────────────────────────────────────
    # trade_data 路径：path/trade_data_{data_date}.csv
    trade_path = get_trade_file_path(path, data_date)
    trade_df, trade_err = safe_read_csv(trade_path)
    if trade_err:
        warnings_list.append(trade_err)
        trade_df = None

    # ── 7. Per-instrument loop ────────────────────────────────
    market_value          = 0.0
    instrument_margin_max = 0.0
    detail_rows: list[dict] = []
    has_warning = False
    has_risk    = False

    instruments = (
        pd_df["instrument_id"].dropna().unique().tolist()
        if not pd_df.empty else []
    )

    for inst in instruments:
        inst_warnings: list[str] = []

        try:
            long_rows  = pd_df.query(f"instrument_id == '{inst}' and pos_type == 'LONG'")
            short_rows = pd_df.query(f"instrument_id == '{inst}' and pos_type == 'SHORT'")
            long_pos   = int(long_rows["position"].iloc[0])  if not long_rows.empty  else 0
            short_pos  = int(short_rows["position"].iloc[0]) if not short_rows.empty else 0
        except Exception as e:
            inst_warnings.append(f"position parsing error: {e}")
            long_pos = short_pos = 0
            has_warning = True

        # 静态信息
        multiplier = 1.0
        exchange   = ""
        try:
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
                    has_warning = True
        except Exception as e:
            inst_warnings.append(f"static info error: {e}")
            has_warning = True

        # 保证金比率
        margin_ratio_inst = 0.0
        try:
            if margin_df is not None and not margin_df.empty:
                m_row = margin_df[margin_df["instrument"] == inst]
                if not m_row.empty:
                    margin_ratio_inst = float(m_row["margin_ratio"].iloc[0])
        except Exception as e:
            inst_warnings.append(f"margin_ratio error: {e}")
            has_warning = True

        # 价格
        price = get_price(inst)
        if price is None:
            inst_warnings.append(f"no price available for {inst}")
            has_warning = True
            price = 0.0

        # 最后成交时间
        try:
            last_trade_time = _get_last_trade_time_adjusted(
                trade_df, inst, data_date, current_date, market
            )
        except Exception as e:
            inst_warnings.append(f"trade_time error: {e}")
            has_warning = True
            last_trade_time = ""

        # uplimit
        uplimit_value = None
        try:
            if market == "commodity":
                uplimit_value = calculate_uplimit(inst, "all", uplimit_holding_position_data)
        except Exception as e:
            inst_warnings.append(f"uplimit calculation error: {e}")
            has_warning = True

        # risk_position
        try:
            risk_pos = risk_position_map.get(inst) if risk_position_map else None
        except Exception as e:
            inst_warnings.append(f"risk_position error: {e}")
            has_warning = True
            risk_pos = None

        risk_match = _check_risk_position_match(long_pos, short_pos, risk_pos)
        if risk_match == "red":
            has_risk = True

        # ★ 计算本合约的 8 个 trade stats
        try:
            trade_stats = calculate_trade_stats(trade_df, inst, multiplier)
        except Exception as e:
            inst_warnings.append(f"trade_stats error: {e}")
            has_warning = True
            trade_stats = {
                "BuyOpenNumber": 0, "BuyOpenMarketValue": 0,
                "BuyCloseNumber": 0, "BuyCloseMarketValue": 0,
                "SellOpenNumber": 0, "SellOpenMarketValue": 0,
                "SellCloseNumber": 0, "SellCloseMarketValue": 0,
            }

        # ── 长仓行 ────────────────────────────────────────────
        if long_pos > 0 or short_pos > 0 or (risk_pos is not None and risk_pos != 0):

            if long_pos > 0:
                try:
                    cp_long = float(long_rows["close_profit"].iloc[0])   if not long_rows.empty else 0.0
                    pp_long = float(long_rows["position_profit"].iloc[0]) if not long_rows.empty else 0.0
                    inst_margin_long      = price * long_pos * multiplier * margin_ratio_inst
                    inst_market_val_long  = price * long_pos * multiplier
                    market_value         += inst_market_val_long
                    instrument_margin_max = max(inst_margin_long, instrument_margin_max)

                    detail_rows.append({
                        "instrument":          inst,
                        "market_value":        round(inst_market_val_long, 2),
                        "position":            int(long_pos),
                        "risk_position":       risk_pos,
                        "clip":                clip,
                        "uplimit":             int(uplimit_value) if uplimit_value is not None else None,
                        "position_type":       "LONG",
                        "close_profit":        round(cp_long, 2),
                        "position_profit":     round(pp_long, 2),
                        "total_pnl":           round(cp_long + pp_long, 2),
                        "instrument_margin":   round(inst_margin_long, 2),
                        "exchange":            exchange,
                        "last_trade_time":     last_trade_time,
                        "risk_match":          risk_match,
                        "_warnings":           "; ".join(inst_warnings),
                        # ★ trade stats
                        "BuyOpenNumber":       trade_stats["BuyOpenNumber"],
                        "BuyOpenMarketValue":  trade_stats["BuyOpenMarketValue"],
                        "BuyCloseNumber":      trade_stats["BuyCloseNumber"],
                        "BuyCloseMarketValue": trade_stats["BuyCloseMarketValue"],
                        "SellOpenNumber":      trade_stats["SellOpenNumber"],
                        "SellOpenMarketValue": trade_stats["SellOpenMarketValue"],
                        "SellCloseNumber":     trade_stats["SellCloseNumber"],
                        "SellCloseMarketValue":trade_stats["SellCloseMarketValue"],
                    })
                except Exception as e:
                    inst_warnings.append(f"LONG row error: {e}")
                    has_warning = True

            # ── 短仓行 ───────────────────────────────────────
            if short_pos > 0:
                try:
                    cp_short = float(short_rows["close_profit"].iloc[0])   if not short_rows.empty else 0.0
                    pp_short = float(short_rows["position_profit"].iloc[0]) if not short_rows.empty else 0.0
                    inst_margin_short     = price * short_pos * multiplier * margin_ratio_inst
                    inst_market_val_short = price * short_pos * multiplier
                    market_value         += inst_market_val_short

                    detail_rows.append({
                        "instrument":          inst,
                        "market_value":        round(inst_market_val_short, 2),
                        "position":            -int(short_pos),
                        "risk_position":       risk_pos,
                        "clip":                clip,
                        "uplimit":             int(uplimit_value) if uplimit_value is not None else None,
                        "position_type":       "SHORT",
                        "close_profit":        round(cp_short, 2),
                        "position_profit":     round(pp_short, 2),
                        "total_pnl":           round(cp_short + pp_short, 2),
                        "instrument_margin":   0.0,
                        "exchange":            exchange,
                        "last_trade_time":     last_trade_time,
                        "risk_match":          risk_match,
                        "_warnings":           "; ".join(inst_warnings),
                        # ★ trade stats（SHORT 行也附上相同合约统计；不重复加权）
                        "BuyOpenNumber":       trade_stats["BuyOpenNumber"],
                        "BuyOpenMarketValue":  trade_stats["BuyOpenMarketValue"],
                        "BuyCloseNumber":      trade_stats["BuyCloseNumber"],
                        "BuyCloseMarketValue": trade_stats["BuyCloseMarketValue"],
                        "SellOpenNumber":      trade_stats["SellOpenNumber"],
                        "SellOpenMarketValue": trade_stats["SellOpenMarketValue"],
                        "SellCloseNumber":     trade_stats["SellCloseNumber"],
                        "SellCloseMarketValue":trade_stats["SellCloseMarketValue"],
                    })
                except Exception as e:
                    inst_warnings.append(f"SHORT row error: {e}")
                    has_warning = True

        # 空仓行（持仓为 0 但目标仓位非 0）
        if long_pos == 0 and short_pos == 0 and risk_pos is not None and risk_pos != 0:
            detail_rows.append({
                "instrument":          inst,
                "market_value":        0,
                "position":            0,
                "risk_position":       risk_pos,
                "clip":                clip,
                "uplimit":             int(uplimit_value) if uplimit_value is not None else None,
                "position_type":       "NONE",
                "close_profit":        0.0,
                "position_profit":     0.0,
                "total_pnl":           0.0,
                "instrument_margin":   0.0,
                "exchange":            exchange,
                "last_trade_time":     last_trade_time,
                "risk_match":          risk_match,
                "_warnings":           "; ".join(inst_warnings),
                # ★ trade stats
                "BuyOpenNumber":       trade_stats["BuyOpenNumber"],
                "BuyOpenMarketValue":  trade_stats["BuyOpenMarketValue"],
                "BuyCloseNumber":      trade_stats["BuyCloseNumber"],
                "BuyCloseMarketValue": trade_stats["BuyCloseMarketValue"],
                "SellOpenNumber":      trade_stats["SellOpenNumber"],
                "SellOpenMarketValue": trade_stats["SellOpenMarketValue"],
                "SellCloseNumber":     trade_stats["SellCloseNumber"],
                "SellCloseMarketValue":trade_stats["SellCloseMarketValue"],
            })

    # ── 汇总 8 列到 overview 行（对所有合约求和）────────────────
    # 注意：若一个合约同时有 LONG 和 SHORT 两行，trade_stats 在两行中相同，
    # 为避免重复累加，这里直接从 trade_df 全局聚合，而不是 sum(detail_rows)。
    try:
        product_trade_stats = _aggregate_product_trade_stats(trade_df, instruments, sd_df)
    except Exception as e:
        warnings_list.append(f"product trade stats aggregation error: {e}")
        product_trade_stats = {k: 0 for k in [
            "BuyOpenNumber", "BuyOpenMarketValue",
            "BuyCloseNumber", "BuyCloseMarketValue",
            "SellOpenNumber", "SellOpenMarketValue",
            "SellCloseNumber", "SellCloseMarketValue",
        ]}

    data.update(product_trade_stats)

    data["market_value"]       = market_value
    data["product_low_limit"]  = market_value / balance if balance > 0 else 0.0
    data["max_margin"]         = instrument_margin_max / balance if balance > 0 else 0.0

    try:
        data["update_time"] = _extract_latest_update_time(ai_df, pd_df, sd_df)
    except Exception as e:
        warnings_list.append(f"update_time error: {e}")

    data["warnings"] = " | ".join(warnings_list)
    detail_df = pd.DataFrame(detail_rows) if detail_rows else None

    return data, detail_df, {"has_warning": has_warning, "has_risk": has_risk}


def _aggregate_product_trade_stats(
    trade_df: pd.DataFrame | None,
    instruments: list[str],
    sd_df: pd.DataFrame | None,
) -> dict:
    """
    对产品内所有合约求和，返回 8 个 trade stats 的产品级汇总值。
    使用 calculate_trade_stats 逐合约计算后累加，避免 LONG/SHORT 双行重复。
    """
    agg = {
        "BuyOpenNumber": 0, "BuyOpenMarketValue": 0,
        "BuyCloseNumber": 0, "BuyCloseMarketValue": 0,
        "SellOpenNumber": 0, "SellOpenMarketValue": 0,
        "SellCloseNumber": 0, "SellCloseMarketValue": 0,
    }
    if trade_df is None or trade_df.empty:
        return agg

    for inst in instruments:
        multiplier = 1.0
        try:
            if sd_df is not None and not sd_df.empty:
                sd_row = sd_df[sd_df["instrument"] == inst]
                if not sd_row.empty:
                    multiplier = float(sd_row["multiplier"].iloc[0])
        except Exception:
            pass
        stats = calculate_trade_stats(trade_df, inst, multiplier)
        for k in agg:
            agg[k] += stats[k]

    # round market value sums
    for k in ["BuyOpenMarketValue", "BuyCloseMarketValue",
              "SellOpenMarketValue", "SellCloseMarketValue"]:
        agg[k] = round(agg[k], 2)

    return agg


# ─────────────────────────────────────────────
# SHARED FILE LOADER
# ─────────────────────────────────────────────

def load_shared_files(
    market: str,
    path: str,
    current_date: int,
    market_open: bool,
) -> tuple[pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None, list[str]]:
    errors: list[str] = []
    data_date, _ = get_data_date(market, path, current_date, market_open)

    sd_path = get_static_info_path(market)
    sd_df, e = safe_read_csv(sd_path)
    if e:
        errors.append(e)

    mkt_path = get_market_data_path(market, data_date)
    future_df, e = safe_read_csv(mkt_path)
    if e:
        errors.append(e)
    else:
        update_price_cache(future_df)

    margin_path = get_margin_file_path(path, market, data_date)
    margin_df, e = safe_read_csv(margin_path) if margin_path else (None, None)
    if e:
        errors.append(e)

    return sd_df, future_df, margin_df, errors


# ─────────────────────────────────────────────
# OVERVIEW TOOLTIP  ★ 新增 8 个字段说明
# ─────────────────────────────────────────────

def display_overview_with_tooltips(styled_df):
    st.dataframe(styled_df, use_container_width=True)
    st.markdown("---")

    with st.expander("Overview 字段完整说明", expanded=False):
        field_data = {
            "字段名": [
                "market", "product", "broker", "init_capital",
                "balance", "pre_balance", "market_value",
                "cost", "ret", "net_return", "fee",
                "pnl", "max_margin", "product_low_limit",
                "margin", "margin_ratio",
                # ★ 8 new
                "BuyOpenNumber",       "BuyOpenMarketValue",
                "BuyCloseNumber",      "BuyCloseMarketValue",
                "SellOpenNumber",      "SellOpenMarketValue",
                "SellCloseNumber",     "SellCloseMarketValue",
                "update_time", "time", "deposit_withdraw", "warnings",
            ],
            "分类": [
                "市场", "市场", "市场", "资金",
                "资金", "资金", "持仓",
                "资金", "资金", "资金", "资金",
                "资金", "风险", "风险",
                "风险", "风险",
                # ★
                "交易统计", "交易统计",
                "交易统计", "交易统计",
                "交易统计", "交易统计",
                "交易统计", "交易统计",
                "时间", "时间", "资金", "系统",
            ],
            "说明": [
                "市场类型：cncf=商品期货 / cnif=股指期货",
                "产品/策略代码，如 bgt_ax1h / jz1h / ly1h / zz1h",
                "交易券商：dz=东正 / zx=中信",
                "初始资金/策略规模 = pre_balance × aum_mul（或自定义公式）",
                "当前账户余额 = 前日余额 + 入金 - 出金 + 盈亏 - 手续费",
                "前一交易日的账户余额，用于计算初始资金基数",
                "当前持仓市值 = sum(合约数量 × 市场价格 × 合约乘数)",
                "累计手续费，交易费用总和",
                "总回报/盈亏 = 平仓盈亏 + 持仓盈亏",
                "净收益 = ret - cost (总回报 - 手续费)",
                "手续费占比 = cost / init_capital × 100%",
                "收益率 = net_return / init_capital × 100%",
                "最大单合约保证金占比 = max(单合约保证金) / 余额，警告阈值 > 25%",
                "持仓市值占比 = 持仓市值 / 账户余额，警告阈值 < 0.8",
                "当前占用保证金 = sum(持仓数量 × 价格 × 乘数 × 保证金率)",
                "保证金占用比 = 占用保证金 / 前日余额",
                # ★ 8 新字段说明
                "【买开手数】当日 trade_data 中方向=B(买)、offset=O(开) 的成交手数合计（产品内所有合约加总）",
                "【买开市值】当日买开成交的名义市值合计 = sum(买开成交价 × 手数 × 合约乘数)",
                "【买平手数】当日 trade_data 中方向=B(买)、offset=C/CT(平) 的成交手数合计",
                "【买平市值】当日买平成交的名义市值合计 = sum(买平成交价 × 手数 × 合约乘数)",
                "【卖开手数】当日 trade_data 中方向=S(卖)、offset=O(开) 的成交手数合计",
                "【卖开市值】当日卖开成交的名义市值合计 = sum(卖开成交价 × 手数 × 合约乘数)",
                "【卖平手数】当日 trade_data 中方向=S(卖)、offset=C/CT(平) 的成交手数合计",
                "【卖平市值】当日卖平成交的名义市值合计 = sum(卖平成交价 × 手数 × 合约乘数)",
                "最后一次数据更新时刻，从数据文件中提取的时间戳",
                "当前仪表板查询时刻（系统时间）",
                "净入出金 = 入金 - 出金",
                "数据加载或计算过程中的警告信息",
            ],
        }

        desc_df = pd.DataFrame(field_data)
        st.dataframe(desc_df, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("""
**风险阈值速查：**
- `max_margin` > **25%** → 单合约保证金过高 (红色告警)
- `product_low_limit` < **0.8** → 流动性不足 (红色告警，ly1h 为黄色)

**Trade Stats 数据来源：**
- 文件路径：`{path}/trade_data_{data_date}.csv`
- 字段识别：自动兼容 `direction/Direction`、`offset_flag/OffsetFlag`、`volume/Volume`、`price/Price`
- offset 归类：`O` = 开仓；`C` / `CT` = 平仓（平今归入平仓）
        """)


# ─────────────────────────────────────────────
# BUILD SUMMARY TABLE
# ─────────────────────────────────────────────

def build_summary_table(df: pd.DataFrame) -> pd.DataFrame:
    summary_rows = []
    df_numeric = df.copy()
    for col in ["balance", "pre_balance", "init_capital", "cost", "net_return", "market_value"]:
        if col in df_numeric.columns:
            df_numeric[col] = pd.to_numeric(
                df_numeric[col].astype(str).str.replace(",", ""),
                errors="coerce",
            ).fillna(0)

    def _build_row(label: str, subset: pd.DataFrame) -> dict:
        aum        = subset["init_capital"].sum()
        cost       = subset["cost"].sum()
        net_return = subset["net_return"].sum()
        pnl_pct    = (net_return / aum * 100) if aum > 0 else 0.0
        return {
            "summary":    label,
            "aum":        int(aum),
            "cost":       int(cost),
            "net_return": int(net_return),
            "pnl":        f"{pnl_pct:.3f}%",
        }

    cncf_data = df_numeric[df_numeric["market"] == "cncf"]
    cnif_data = df_numeric[df_numeric["market"] == "cnif"]

    if not cncf_data.empty:
        summary_rows.append(_build_row("cncf", cncf_data))
    if not cnif_data.empty:
        summary_rows.append(_build_row("cnif", cnif_data))
    summary_rows.append(_build_row("cn_all", df_numeric))

    summary_df = pd.DataFrame(summary_rows)
    for col in ["aum", "net_return"]:
        summary_df[col] = summary_df[col].apply(lambda x: f"{x:,}")
    return summary_df


# ─────────────────────────────────────────────
# DASHBOARD MAIN
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

            summary_rows:      list[dict]       = []
            detail_map:        dict[str, tuple]  = {}
            detail_status_map: dict[str, dict]   = {}
            global_file_errors: list[str]        = []
            shared_cache:      dict[str, tuple]  = {}

            for cfg in PRODUCT_CONFIGS:
                ft   = cfg["market"]
                path = cfg["path"]
                name = cfg["product"]

                market_open = is_market_open(ft)
                data_date_for_shared, _ = get_data_date(ft, path, current_date, market_open)
                cache_key = (ft, data_date_for_shared)

                if cache_key not in shared_cache:
                    sd_df, future_df, _dummy_margin, errs = load_shared_files(
                        ft, path, current_date, market_open
                    )
                    shared_cache[cache_key] = (sd_df, future_df, errs)
                    global_file_errors.extend(errs)

                sd_df, future_df, _shared_errs = shared_cache[cache_key]

                margin_path = get_margin_file_path(path, ft, data_date_for_shared)
                margin_df, m_err = safe_read_csv(margin_path) if margin_path else (None, None)
                if m_err:
                    global_file_errors.append(m_err)

                try:
                    row, detail_df, detail_status = calculate_product(
                        cfg              = cfg,
                        path             = path,
                        broker           = cfg["broker"],
                        product          = name,
                        market           = ft,
                        current_date     = current_date,
                        market_open      = market_open,
                        shared_sd_df     = sd_df,
                        shared_future_df = future_df,
                        shared_margin_df = margin_df,
                    )
                except Exception as calc_err:
                    row = dict(DEFAULT_SUMMARY)
                    row.update({
                        "market":         "cncf" if ft == "commodity" else "cnif",
                        "product":        name,
                        "broker":         cfg["broker"],
                        "init_capital":   0,
                        "time":           now.strftime("%H:%M:%S"),
                        "warnings":       f"Calculation error: {calc_err}",
                        "is_market_open": market_open,
                    })
                    detail_df     = None
                    detail_status = {"has_warning": True, "has_risk": False}

                summary_rows.append(row)
                if detail_df is not None:
                    detail_map[cfg["path"]]        = (cfg, detail_df)
                    detail_status_map[cfg["path"]] = detail_status

                if market_open:
                    try:
                        pll = float(row["product_low_limit"])
                        imu = float(row["max_margin"])
                        if pll < 0.8 and name not in {"ly1h"}:
                            send_alert(
                                f"[ALERT] product_low_limit < 0.8 | "
                                f"broker={row['broker']} product={name}"
                            )
                        if imu > 0.25:
                            send_alert(
                                f"[ALERT] max_margin > 0.25 | "
                                f"broker={row['broker']} product={name}"
                            )
                    except (ValueError, TypeError):
                        pass

            # ── Build overview DataFrame ───────────────────────
            df = pd.DataFrame(summary_rows, columns=SUMMARY_COLS)

            money_cols = [
                "balance", "pre_balance", "market_value",
                "deposit_withdraw", "cost", "net_return", "init_capital", "margin",
            ]
            for col in money_cols:
                df[col] = (
                    pd.to_numeric(df[col], errors="coerce")
                    .fillna(0).round(0).astype(int)
                    .apply(lambda x: f"{x:,}")
                )

            # ★ 格式化 8 个 trade stats 列（整数）
            trade_stat_cols = [
                "BuyOpenNumber", "BuyOpenMarketValue",
                "BuyCloseNumber", "BuyCloseMarketValue",
                "SellOpenNumber", "SellOpenMarketValue",
                "SellCloseNumber", "SellCloseMarketValue",
            ]
            for col in trade_stat_cols:
                if col in df.columns:
                    df[col] = (
                        pd.to_numeric(df[col], errors="coerce")
                        .fillna(0).round(0).astype(int)
                        .apply(lambda x: f"{x:,}")
                    )

            df["max_margin"] = (
                pd.to_numeric(df["max_margin"], errors="coerce")
                .fillna(0).apply(lambda x: f"{100*x:.2f}%")
            )
            df["product_low_limit"] = (
                pd.to_numeric(df["product_low_limit"], errors="coerce")
                .fillna(0).apply(lambda x: f"{x:.4f}")
            )

            display_df = df.drop(columns=["is_market_open"])

            styled_df = (
                display_df.style
                .apply(style_product_low_limit, axis=1)
                .map(style_max_margin, subset=["max_margin"])
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

                st.markdown("---")
                st.subheader("Trading Summary")
                summary_table = build_summary_table(df)
                st.dataframe(summary_table, use_container_width=True)

                if global_file_errors:
                    st.error(
                        "**Missing / unreadable files:**\n\n"
                        + "\n\n".join(f"- {e}" for e in global_file_errors)
                    )

                st.markdown("---")
                st.subheader("Overview")
                display_overview_with_tooltips(styled_df)

                st.markdown("---")
                st.subheader("Per-Instrument Detail")

                for prod_path, (cfg, ddf) in detail_map.items():
                    market_label  = "CNCF" if cfg["market"] == "commodity" else "CNIF"
                    product_label = cfg["product"]
                    broker_label  = cfg["broker"]

                    status      = detail_status_map.get(prod_path, {"has_warning": False, "has_risk": False})
                    has_risk    = status.get("has_risk", False)
                    has_warning = status.get("has_warning", False)

                    if has_risk:
                        title_color = "[RED]"
                    elif has_warning:
                        title_color = "[WARN]"
                    else:
                        title_color = ""

                    title = f"{title_color} [{market_label}] {product_label} | {broker_label}"

                    with st.expander(title, expanded=False):
                        # ★ 列顺序：原有列 + 8 个 trade stats 列
                        display_cols = [
                            "instrument", "market_value",
                            "position", "risk_position", "clip", "uplimit",
                            "close_profit", "position_profit", "total_pnl",
                            "instrument_margin", "exchange", "last_trade_time",
                            # ★ 8 new columns
                            "BuyOpenNumber",       "BuyOpenMarketValue",
                            "BuyCloseNumber",      "BuyCloseMarketValue",
                            "SellOpenNumber",      "SellOpenMarketValue",
                            "SellCloseNumber",     "SellCloseMarketValue",
                        ]

                        display_ddf = ddf[
                            [c for c in display_cols if c in ddf.columns]
                        ].copy()

                        # 整数格式化
                        int_cols = [
                            "market_value", "risk_position",
                            "close_profit", "position_profit", "total_pnl",
                            "instrument_margin",
                            # ★
                            "BuyOpenNumber",       "BuyOpenMarketValue",
                            "BuyCloseNumber",      "BuyCloseMarketValue",
                            "SellOpenNumber",      "SellOpenMarketValue",
                            "SellCloseNumber",     "SellCloseMarketValue",
                        ]
                        for col in int_cols:
                            if col in display_ddf.columns:
                                display_ddf[col] = (
                                    pd.to_numeric(display_ddf[col], errors="coerce")
                                    .fillna(0).astype(int)
                                )

                        if "uplimit" in display_ddf.columns:
                            display_ddf["uplimit"] = display_ddf["uplimit"].apply(
                                lambda x: f"{float(x):.2f}" if pd.notna(x) and x is not None else None
                            )

                        col_mapping = {
                            "instrument":          "合约名称",
                            "market_value":        "合约市值",
                            "position":            "持仓数量",
                            "risk_position":       "目标仓位",
                            "clip":                "Clip",
                            "uplimit":             "Uplimit",
                            "close_profit":        "平仓盈亏",
                            "position_profit":     "持仓盈亏",
                            "total_pnl":           "当日盈亏",
                            "instrument_margin":   "保证金",
                            "exchange":            "交易所",
                            "last_trade_time":     "最后成交时间",
                            # ★ 8 new
                            "BuyOpenNumber":       "买开手数",
                            "BuyOpenMarketValue":  "买开市值",
                            "BuyCloseNumber":      "买平手数",
                            "BuyCloseMarketValue": "买平市值",
                            "SellOpenNumber":      "卖开手数",
                            "SellOpenMarketValue": "卖开市值",
                            "SellCloseNumber":     "卖平手数",
                            "SellCloseMarketValue":"卖平市值",
                        }
                        display_ddf = display_ddf.rename(columns=col_mapping)

                        # 风险行着色
                        def style_risk_match_row(row_idx):
                            styles = [""] * len(display_ddf.columns)
                            if row_idx < len(ddf) and "risk_match" in ddf.columns:
                                if ddf.iloc[row_idx].get("risk_match", "matched") == "red":
                                    styles = [
                                        "background-color: #ff4b4b; color: white; font-weight: bold;"
                                    ] * len(display_ddf.columns)
                            return styles

                        styled_detail = display_ddf.style
                        for row_idx in range(len(display_ddf)):
                            row_styles = style_risk_match_row(row_idx)
                            if any(row_styles):
                                for col_name, style in zip(display_ddf.columns, row_styles):
                                    if style:
                                        styled_detail = styled_detail.map(
                                            lambda x, s=style: s,
                                            subset=pd.IndexSlice[[row_idx], col_name]
                                        )

                        st.dataframe(styled_detail, use_container_width=True)

                        # ★ 新增：Detail 下方的字段说明（可折叠）
                        with st.expander("Detail 字段说明 - 交易统计列", expanded=False):
                            detail_field_data = {
                                "字段名（中文）": [
                                    "买开手数", "买开市值",
                                    "买平手数", "买平市值",
                                    "卖开手数", "卖开市值",
                                    "卖平手数", "卖平市值",
                                ],
                                "英文键名": [
                                    "BuyOpenNumber",       "BuyOpenMarketValue",
                                    "BuyCloseNumber",      "BuyCloseMarketValue",
                                    "SellOpenNumber",      "SellOpenMarketValue",
                                    "SellCloseNumber",     "SellCloseMarketValue",
                                ],
                                "计算来源": ["trade_data"] * 8,
                                "说明": [
                                    "当日该合约 direction=B(买) 且 offset=O(开) 的成交手数合计",
                                    "当日该合约买开成交名义市值 = sum(成交价 × 手数 × 乘数)，direction=B & offset=O",
                                    "当日该合约 direction=B(买) 且 offset=C/CT(平) 的成交手数合计",
                                    "当日该合约买平成交名义市值 = sum(成交价 × 手数 × 乘数)，direction=B & offset=C/CT",
                                    "当日该合约 direction=S(卖) 且 offset=O(开) 的成交手数合计",
                                    "当日该合约卖开成交名义市值 = sum(成交价 × 手数 × 乘数)，direction=S & offset=O",
                                    "当日该合约 direction=S(卖) 且 offset=C/CT(平) 的成交手数合计",
                                    "当日该合约卖平成交名义市值 = sum(成交价 × 手数 × 乘数)，direction=S & offset=C/CT",
                                ],
                            }
                            st.dataframe(
                                pd.DataFrame(detail_field_data),
                                use_container_width=True,
                                hide_index=True,
                            )

                        # 仓位异常注释
                        if "risk_match" in ddf.columns and "instrument" in ddf.columns:
                            risk_red_rows = ddf[ddf["risk_match"] == "red"]
                            if not risk_red_rows.empty:
                                st.error("**Instrument Risk Errors (Position Mismatch):**")
                                for _, rr in risk_red_rows.iterrows():
                                    inst_name  = rr["instrument"]
                                    pos_type   = rr.get("position_type", "")
                                    actual_pos = rr.get("position", 0)
                                    risk_pos_v = rr.get("risk_position", None)
                                    try:
                                        if risk_pos_v is not None and math.isnan(float(risk_pos_v)):
                                            risk_pos_v = 0
                                    except (TypeError, ValueError):
                                        pass
                                    risk_pos_display = int(round(float(risk_pos_v))) if risk_pos_v is not None else 0
                                    st.markdown(
                                        f"- **{inst_name}** ({pos_type}): "
                                        f"实际持仓 = `{actual_pos}`, "
                                        f"目标仓位 = `{risk_pos_display}` "
                                        f"-> 净仓位与目标仓位不一致"
                                    )

                        # 警告信息
                        if "_warnings" in ddf.columns:
                            inst_warns = ddf[ddf["_warnings"].str.len() > 0]
                            if not inst_warns.empty:
                                st.warning("**Instrument Warnings:**")
                                for _, wr in inst_warns.iterrows():
                                    st.markdown(f"- **{wr['instrument']}**: {wr['_warnings']}")

        except Exception as outer_err:
            with placeholder.container():
                st.error(f"Dashboard loop error: {outer_err}")
                import traceback
                st.error(traceback.format_exc())

        time.sleep(10)


if __name__ == "__main__":
    dashboard()
