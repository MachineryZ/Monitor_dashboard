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

COMMODITY_SESSIONS = [
    (datetime.time(9,  0),  datetime.time(10, 15), False),
    (datetime.time(10, 30), datetime.time(11, 30), False),
    (datetime.time(13, 30), datetime.time(15,  0), False),
    (datetime.time(21,  0), datetime.time(2,  30), True ),
]

FUTURES_SESSIONS = [
    (datetime.time(9,  30), datetime.time(11, 30), False),
    (datetime.time(13,  0), datetime.time(15,  0), False),
]

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
# CLICKHOUSE CLIENT
# ─────────────────────────────────────────────

_ch_client = None

def get_ch_client():
    global _ch_client
    if _ch_client is None:
        try:
            from clickhouse_connect.driver import create_client
            _ch_client = create_client(
                host='10.51.4.21', port=8123,
                username='dashboard', password='123456',
                database='cffex_zx'
            )
        except Exception:
            return None
    return _ch_client


def get_product_clip(product_name: str) -> int | None:
    if not product_name:
        return None
    client = get_ch_client()
    if client is None:
        return None
    query = f"SELECT clip FROM commodity_meta.product_clip WHERE product_name = '{product_name}' LIMIT 1"
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
    query = "SELECT coef FROM commodity_meta.product_uplimit_coef WHERE product_name = 'all' LIMIT 1"
    try:
        result = client.query_df(query)
        if not result.empty:
            return float(result.iloc[0]["coef"])
        return None
    except Exception:
        return None


# ─────────────────────────────────────────────
# UPLIMIT
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
        for _, row in df.iterrows():
            try:
                inst = str(row["instrument"]).strip()
                uplimit_hp_raw = row.get("up_limit_holding_position", 0)
                if inst:
                    uplimit_data[inst] = float(uplimit_hp_raw)
            except (ValueError, TypeError):
                continue
        return uplimit_data if uplimit_data else None
    except Exception:
        import traceback
        traceback.print_exc()
        return None


def calculate_uplimit(instrument: str, product_name: str,
                      uplimit_data: dict[str, float] | None) -> float | None:
    coef = get_product_uplimit_coef(product_name) or 1
    if uplimit_data is None or instrument not in uplimit_data:
        return None
    try:
        return uplimit_data[instrument] * coef
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
    return date_int, int(date_list[pos])


def _time_in_session(t, start, end, crosses_midnight):
    if crosses_midnight:
        return t >= start or t <= end
    return start <= t <= end


def is_commodity_night_session_pre_midnight(t):
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
    d = datetime.datetime.strptime(str(current_date), "%Y%m%d") - datetime.timedelta(days=1)
    return int(d.strftime("%Y%m%d"))


def get_next_trade_date(current_date: int) -> int:
    try:
        date_list = np.loadtxt(CALENDAR_PATH, dtype=np.int64, ndmin=1)
        pos = np.searchsorted(date_list, current_date, side="right")
        if pos < len(date_list):
            return int(date_list[pos])
    except Exception:
        pass
    d = datetime.datetime.strptime(str(current_date), "%Y%m%d") + datetime.timedelta(days=1)
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


def _extract_latest_update_time(*dfs) -> str:
    candidates = []
    for df in dfs:
        if df is None or df.empty or "update_time" not in df.columns:
            continue
        col = df["update_time"].dropna().astype(str)
        col = col[col.str.strip() != ""]
        if not col.empty:
            candidates.append(col.max())
    return max(candidates) if candidates else ""


# ─────────────────────────────────────────────
# get_data_date
# ─────────────────────────────────────────────

def get_data_date(market, path, current_date, market_open):
    t = datetime.datetime.now().time()
    if market_open:
        if market == "commodity" and is_commodity_night_session_pre_midnight(t):
            next_td = get_next_trade_date(current_date)
            return next_td, f" (night→{next_td})"
        return current_date, ""
    if file_exists_for_date(path, current_date):
        return current_date, " (today data)"
    return get_previous_trade_date(current_date), " (prev day data)"


# ─────────────────────────────────────────────
# PATH HELPERS
# ─────────────────────────────────────────────

def get_margin_file_path(path, market, data_date):
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


def get_static_info_path(market):
    if market == "commodity":
        return "/cpfs/rawdata/cncf_all_nedd_before_open/ins_static_info.csv"
    return "/cpfs/rawdata/cnif_all_need_before_open/ins_static_info.csv"


def get_market_data_path(market, data_date):
    kind = "commodity" if market == "commodity" else "futures"
    return f"/mnt/nfs_bohr_data1/china/trading_realdata/partial_market_data_realtime/{kind}/{data_date}.csv"


def get_trade_file_path(path, data_date):
    return os.path.join(path, f"trade_data_{data_date}.csv")


def send_alert(message):
    webhook_url = (
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
        "?key=1f5ccb85-9f37-46a5-b5a7-d5e0a7cc9b3c"
    )
    try:
        requests.post(webhook_url, data=json.dumps(
            {"msgtype": "text", "text": {"content": message}}
        ), timeout=5)
    except Exception:
        pass


# ─────────────────────────────────────────────
# PRICE CACHE
# ─────────────────────────────────────────────

def init_price_cache(market, current_date):
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


def update_price_cache(future_df):
    if future_df is None or future_df.empty:
        return
    if not {"instrument", "ask_price1", "bid_price1"}.issubset(future_df.columns):
        return
    for _, row in future_df.iterrows():
        inst = row["instrument"]
        ask, bid = row.get("ask_price1", 0), row.get("bid_price1", 0)
        if pd.notna(ask) and pd.notna(bid) and (ask + bid) > 0:
            _price_cache[inst] = float((ask + bid) / 2)


def get_price(instrument):
    return _price_cache.get(instrument)


# ─────────────────────────────────────────────
# RISK POSITION LOADER
# ─────────────────────────────────────────────

def load_risk_position(market, product, data_date):
    result = {}
    if market == "commodity":
        strategy_mapping = {
            "bgt_ax1h": "cncf_melt_bgt_dz_bohr",
            "shjq":     "cncf_melt_shjq_zx_bohr",
            "shph1h":   "cncf_melt_shph1h_zx_bohr",
            "zz1h":     "cncf_melt_zhizeng_dz_bohr",
        }
        if product not in strategy_mapping:
            return None
        csv_path = f"/cpfs/prod/prod_log/china_future/cncf/{strategy_mapping[product]}/{data_date}.csv"
        df, err = safe_read_csv(csv_path)
        if err or df is None or df.empty:
            return None
        for _, row in df.iterrows():
            try:
                inst = str(row.get("instrument", "")).strip()
                val  = str(row.get("all_stats", "")).strip().strip("[]").strip()
                if inst and val:
                    result[inst] = float(val)
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
        csv_path = f"/cpfs/prod/prod_log/china_future/cnif/{strategy_mapping[product]}/{data_date}.csv"
        df, err = safe_read_csv(csv_path)
        if err or df is None or df.empty:
            return None
        for _, row in df.iterrows():
            try:
                inst = str(row.get("instrument", "")).strip()
                if inst:
                    result[inst] = float(row.get("value", 0))
            except (ValueError, TypeError):
                continue
    return result if result else None


# ─────────────────────────────────────────────
# ★ TRADE STATS CALCULATOR
#
# trade_data 字段说明（实际存储格式）：
#   instrument_id : 合约代码字符串，如 "IF2506"
#   direction     : ASCII整数  66=B(买)  83=S(卖)
#   offset_flag   : ASCII整数  79=O(开)  67=C(平)  84=T(平今)
#   price         : 浮点数，成交价格
#   volume        : 整数，成交手数
#   trade_time    : 字符串 "HH:MM:SS"，如 "14:56:18"
# ─────────────────────────────────────────────

# ★ 关键映射：ASCII整数 -> 标准字符
_DIRECTION_ASCII_MAP = {
    66: "B",   # ord('B') = 66  -> 买
    83: "S",   # ord('S') = 83  -> 卖
}
_OFFSET_ASCII_MAP = {
    79: "O",   # ord('O') = 79  -> 开仓
    67: "C",   # ord('C') = 67  -> 平仓
    84: "T",   # ord('T') = 84  -> 平今（归类为平仓）
}

_INST_COL_CANDIDATES   = ["instrument_id", "InstrumentID", "instrument"]
_DIRECTION_COL_CANDIDATES  = ["direction",   "Direction"]
_OFFSET_COL_CANDIDATES     = ["offset_flag", "OffsetFlag",  "offset"]
_VOLUME_COL_CANDIDATES     = ["volume",      "Volume",      "trade_volume"]
_PRICE_COL_CANDIDATES      = ["price",       "Price",       "trade_price"]


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _normalize_direction(series: pd.Series) -> pd.Series:
    """
    将 direction 列统一为 'B' / 'S' 字符串。
    兼容两种格式：
      - 整数 ASCII 码：66 -> 'B'，83 -> 'S'
      - 字符串：'B'/'b'/'BUY' -> 'B'，'S'/'s'/'SELL' -> 'S'
    """
    def _convert(val):
        # 尝试转为整数（ASCII码格式）
        try:
            iv = int(float(str(val).strip()))
            return _DIRECTION_ASCII_MAP.get(iv, "")
        except (ValueError, TypeError):
            pass
        # 字符串格式
        s = str(val).strip().upper()
        if s.startswith("B"):
            return "B"
        if s.startswith("S"):
            return "S"
        return ""
    return series.map(_convert)


def _normalize_offset(series: pd.Series) -> pd.Series:
    """
    将 offset_flag 列统一为 'O' / 'C' / 'T' 字符串。
    兼容两种格式：
      - 整数 ASCII 码：79 -> 'O'，67 -> 'C'，84 -> 'T'
      - 字符串：'O'/'OPEN'/'开' -> 'O'，'C'/'CT'/'CLOSE'/'平' -> 'C'
    """
    def _convert(val):
        # 尝试转为整数（ASCII码格式）
        try:
            iv = int(float(str(val).strip()))
            return _OFFSET_ASCII_MAP.get(iv, "")
        except (ValueError, TypeError):
            pass
        # 字符串格式
        s = str(val).strip().upper()
        if s in ("O", "OPEN"):
            return "O"
        if s in ("C", "CT", "CLOSE"):
            return "C"
        if s == "T":
            return "T"
        return ""
    return series.map(_convert)


def calculate_trade_stats(
    trade_df: pd.DataFrame | None,
    inst: str,
    multiplier: float,
) -> dict:
    """
    从 trade_data DataFrame 针对单个合约计算 8 个交易统计值。

    direction  存储为 ASCII 整数：66=B(买)  83=S(卖)
    offset_flag 存储为 ASCII 整数：79=O(开)  67=C(平)  84=T(平今)

    BuyOpenNumber       = direction==B & offset==O 的 volume 合计
    BuyOpenMarketValue  = sum(price × volume × multiplier)，条件同上
    BuyCloseNumber      = direction==B & offset in {C,T} 的 volume 合计
    BuyCloseMarketValue = sum(price × volume × multiplier)，条件同上
    SellOpenNumber      = direction==S & offset==O 的 volume 合计
    SellOpenMarketValue = sum(price × volume × multiplier)，条件同上
    SellCloseNumber     = direction==S & offset in {C,T} 的 volume 合计
    SellCloseMarketValue= sum(price × volume × multiplier)，条件同上
    """
    zero = {
        "BuyOpenNumber": 0,       "BuyOpenMarketValue": 0,
        "BuyCloseNumber": 0,      "BuyCloseMarketValue": 0,
        "SellOpenNumber": 0,      "SellOpenMarketValue": 0,
        "SellCloseNumber": 0,     "SellCloseMarketValue": 0,
    }

    if trade_df is None or trade_df.empty:
        return zero

    # 找各列
    inst_col   = _find_col(trade_df, _INST_COL_CANDIDATES)
    dir_col    = _find_col(trade_df, _DIRECTION_COL_CANDIDATES)
    offset_col = _find_col(trade_df, _OFFSET_COL_CANDIDATES)
    vol_col    = _find_col(trade_df, _VOLUME_COL_CANDIDATES)
    price_col  = _find_col(trade_df, _PRICE_COL_CANDIDATES)

    if any(c is None for c in [inst_col, dir_col, offset_col, vol_col, price_col]):
        return zero

    # 筛选当前合约的所有成交行
    rows = trade_df[
        trade_df[inst_col].astype(str).str.strip() == str(inst).strip()
    ].copy()

    if rows.empty:
        return zero

    # ★ 核心修复：将 ASCII 整数码转换为标准字符，再做分类比较
    rows["_dir"]    = _normalize_direction(rows[dir_col])
    rows["_offset"] = _normalize_offset(rows[offset_col])
    rows["_vol"]    = pd.to_numeric(rows[vol_col],   errors="coerce").fillna(0)
    rows["_price"]  = pd.to_numeric(rows[price_col], errors="coerce").fillna(0)
    rows["_mv"]     = rows["_price"] * rows["_vol"] * multiplier

    # 分类掩码
    is_buy   = rows["_dir"] == "B"
    is_sell  = rows["_dir"] == "S"
    is_open  = rows["_offset"] == "O"
    is_close = rows["_offset"].isin(["C", "T"])   # C=平仓, T=平今，均算平仓

    return {
        "BuyOpenNumber":        int(rows.loc[is_buy  & is_open,  "_vol"].sum()),
        "BuyOpenMarketValue":   round(rows.loc[is_buy  & is_open,  "_mv"].sum(), 2),
        "BuyCloseNumber":       int(rows.loc[is_buy  & is_close, "_vol"].sum()),
        "BuyCloseMarketValue":  round(rows.loc[is_buy  & is_close, "_mv"].sum(), 2),
        "SellOpenNumber":       int(rows.loc[is_sell & is_open,  "_vol"].sum()),
        "SellOpenMarketValue":  round(rows.loc[is_sell & is_open,  "_mv"].sum(), 2),
        "SellCloseNumber":      int(rows.loc[is_sell & is_close, "_vol"].sum()),
        "SellCloseMarketValue": round(rows.loc[is_sell & is_close, "_mv"].sum(), 2),
    }


def _aggregate_product_trade_stats(trade_df, instruments, sd_df) -> dict:
    """对产品内所有合约逐个计算后求和，避免 LONG/SHORT 双行重复累加。"""
    agg = {
        "BuyOpenNumber": 0,   "BuyOpenMarketValue": 0,
        "BuyCloseNumber": 0,  "BuyCloseMarketValue": 0,
        "SellOpenNumber": 0,  "SellOpenMarketValue": 0,
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

    for k in ["BuyOpenMarketValue", "BuyCloseMarketValue",
              "SellOpenMarketValue", "SellCloseMarketValue"]:
        agg[k] = round(agg[k], 2)
    return agg


def aggregate_trade_stats(detail_rows: list[dict]) -> dict:
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

def style_product_low_limit(row):
    styles = [""] * len(row)
    if "product_low_limit" not in row.index:
        return styles
    col_idx = row.index.get_loc("product_low_limit")
    try:
        val = float(row["product_low_limit"])
        if val < 0.8:
            styles[col_idx] = (
                "background-color: #ffd700; color: black"
                if row.get("product", "") == "ly1h"
                else "background-color: #ff4b4b; color: white"
            )
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
# SUMMARY_COLS & DEFAULT_SUMMARY
# ─────────────────────────────────────────────

SUMMARY_COLS = [
    "market", "product", "broker", "init_capital",
    "balance", "pre_balance", "market_value",
    "cost", "net_return", "fee", "pnl",
    "max_margin", "product_low_limit",
    "margin", "margin_ratio",
    "BuyOpenNumber",  "BuyOpenMarketValue",
    "BuyCloseNumber", "BuyCloseMarketValue",
    "SellOpenNumber", "SellOpenMarketValue",
    "SellCloseNumber","SellCloseMarketValue",
    "update_time", "time", "warnings", "deposit_withdraw", "is_market_open",
]

DEFAULT_SUMMARY = {
    "market": "", "product": "", "broker": "",
    "init_capital": 0, "balance": 0, "pre_balance": 0, "market_value": 0,
    "cost": 0, "net_return": 0, "fee": "0.000%", "pnl": "0.000%",
    "max_margin": 0.0, "product_low_limit": 0.0, "margin": 0.0,
    "margin_ratio": "0.000%",
    "BuyOpenNumber": 0,   "BuyOpenMarketValue": 0,
    "BuyCloseNumber": 0,  "BuyCloseMarketValue": 0,
    "SellOpenNumber": 0,  "SellOpenMarketValue": 0,
    "SellCloseNumber": 0, "SellCloseMarketValue": 0,
    "deposit_withdraw": 0, "time": "", "warnings": "",
    "update_time": "", "is_market_open": False,
}


# ─────────────────────────────────────────────
# _get_last_trade_time_adjusted
# trade_time 列格式为 "HH:MM:SS"，如 "14:56:18"
# ─────────────────────────────────────────────

def _get_last_trade_time_adjusted(trade_df, inst, data_date, current_date, market):
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

    # trade_data 有 trade_time 列，格式 "HH:MM:SS"
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
            return f"{get_previous_trade_date(data_date)} 20:00:00"

        # trade_time 已是 "HH:MM:SS" 格式，直接取最后部分
        if ':' in trade_time_str:
            time_part = trade_time_str.split()[-1]  # 防止带日期前缀
        else:
            time_part = trade_time_str[-6:] if len(trade_time_str) >= 6 else trade_time_str
            time_part = f"{time_part[0:2]}:{time_part[2:4]}:{time_part[4:6]}"

        hour = int(time_part[:2])
        if hour >= 21:
            return f"{get_previous_trade_date(data_date)} {time_part}"
        return f"{data_date} {time_part}"

    except (ValueError, IndexError, AttributeError):
        pass
    return str(trade_time_raw)


def _check_risk_position_match(long_pos, short_pos, risk_pos):
    long_int  = int(round(long_pos))  if long_pos  is not None else 0
    short_int = int(round(short_pos)) if short_pos is not None else 0
    risk_int  = int(round(risk_pos))  if risk_pos  is not None else 0
    return "red" if (long_int - short_int) != risk_int else "matched"


# ─────────────────────────────────────────────
# CORE: calculate_product
# ─────────────────────────────────────────────

def calculate_product(cfg, path, broker, product, market, current_date,
                      market_open, shared_sd_df, shared_future_df, shared_margin_df):

    warnings_list = []
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
        data["warnings"] = " | ".join(warnings_list)
        return data, None, {"has_warning": True, "has_risk": False}

    balance = pre_balance = deposit = withdraw = fee = margin = 0.0
    margin_ratio = 0.0

    if ai_df.empty:
        warnings_list.append(f"Header-only file: {ai_path}")
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

    data["margin_ratio"]     = f"{100*margin_ratio:.2f}%"
    data["balance"]          = balance
    data["pre_balance"]      = pre_balance
    data["deposit_withdraw"] = deposit - withdraw
    data["cost"]             = fee
    data["margin"]           = margin
    init_capital             = resolve_init_capital(cfg, pre_balance, balance)
    data["init_capital"]     = init_capital

    # ── 2. position_data ─────────────────────────────────────
    pd_path = os.path.join(path, f"position_data_{data_date}.csv")
    pd_df, pd_err = safe_read_csv(pd_path)
    if pd_err:
        warnings_list.append(pd_err)
        data["warnings"] = " | ".join(warnings_list)
        return data, None, {"has_warning": True, "has_risk": False}

    if pd_df.empty:
        warnings_list.append(f"Header-only file: {pd_path}")
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

    data["net_return"] = abs_return - fee
    data["fee"]  = f"{(fee/init_capital)*100:.3f}%" if init_capital > 0 else "0.000%"
    pnl = round(data["net_return"] / init_capital * 100, 3) if init_capital > 0 else 0.0
    data["pnl"]  = f"{pnl:.3f}%"

    sd_df     = shared_sd_df
    future_df = shared_future_df
    margin_df = shared_margin_df

    # ── 3. risk / clip / uplimit ─────────────────────────────
    risk_position_map = load_risk_position(market, product, data_date)
    db_product = cfg.get("db_product")
    clip = get_product_clip(db_product) if db_product else None
    uplimit_holding_position_data = None
    if market == "commodity":
        uplimit_holding_position_data = load_uplimit_holding_position()

    # ── 4. trade_data ─────────────────────────────────────────
    # ★ 直接用 os.path.join 拼接，确保路径正确
    trade_path = os.path.join(path, f"trade_data_{data_date}.csv")
    trade_df, trade_err = safe_read_csv(trade_path)
    if trade_err:
        warnings_list.append(f"trade_data: {trade_err}")
        trade_df = None

    # ── 5. Per-instrument loop ────────────────────────────────
    market_value = 0.0
    instrument_margin_max = 0.0
    detail_rows = []
    has_warning = has_risk = False

    instruments = (
        pd_df["instrument_id"].dropna().unique().tolist()
        if not pd_df.empty else []
    )

    for inst in instruments:
        inst_warnings = []

        try:
            long_rows  = pd_df.query(f"instrument_id == '{inst}' and pos_type == 'LONG'")
            short_rows = pd_df.query(f"instrument_id == '{inst}' and pos_type == 'SHORT'")
            long_pos   = int(long_rows["position"].iloc[0])  if not long_rows.empty  else 0
            short_pos  = int(short_rows["position"].iloc[0]) if not short_rows.empty else 0
        except Exception as e:
            inst_warnings.append(f"position parsing error: {e}")
            long_pos = short_pos = 0
            has_warning = True

        multiplier = 1.0
        exchange   = ""
        try:
            if sd_df is not None and not sd_df.empty:
                sd_row = sd_df[sd_df["instrument"] == inst]
                if not sd_row.empty:
                    multiplier = float(sd_row["multiplier"].iloc[0])
                    exchange   = str(sd_row["exchange"].iloc[0]) if "exchange" in sd_row.columns else ""
                else:
                    inst_warnings.append(f"no static info for {inst}")
                    has_warning = True
        except Exception as e:
            inst_warnings.append(f"static info error: {e}")
            has_warning = True

        margin_ratio_inst = 0.0
        try:
            if margin_df is not None and not margin_df.empty:
                m_row = margin_df[margin_df["instrument"] == inst]
                if not m_row.empty:
                    margin_ratio_inst = float(m_row["margin_ratio"].iloc[0])
        except Exception as e:
            inst_warnings.append(f"margin_ratio error: {e}")
            has_warning = True

        price = get_price(inst)
        if price is None:
            inst_warnings.append(f"no price for {inst}")
            has_warning = True
            price = 0.0

        try:
            last_trade_time = _get_last_trade_time_adjusted(
                trade_df, inst, data_date, current_date, market
            )
        except Exception as e:
            inst_warnings.append(f"trade_time error: {e}")
            has_warning = True
            last_trade_time = ""

        uplimit_value = None
        try:
            if market == "commodity":
                uplimit_value = calculate_uplimit(inst, "all", uplimit_holding_position_data)
        except Exception as e:
            inst_warnings.append(f"uplimit error: {e}")
            has_warning = True

        try:
            risk_pos = risk_position_map.get(inst) if risk_position_map else None
        except Exception as e:
            inst_warnings.append(f"risk_position error: {e}")
            has_warning = True
            risk_pos = None

        risk_match = _check_risk_position_match(long_pos, short_pos, risk_pos)
        if risk_match == "red":
            has_risk = True

        # ★ 计算 8 个 trade stats（使用修复后的函数，正确解析 ASCII 整数编码）
        try:
            trade_stats = calculate_trade_stats(trade_df, inst, multiplier)
        except Exception as e:
            inst_warnings.append(f"trade_stats error: {e}")
            has_warning = True
            trade_stats = {k: 0 for k in [
                "BuyOpenNumber", "BuyOpenMarketValue",
                "BuyCloseNumber", "BuyCloseMarketValue",
                "SellOpenNumber", "SellOpenMarketValue",
                "SellCloseNumber", "SellCloseMarketValue",
            ]}

        def _make_row(pos_type, position_val, cp, pp, inst_margin, inst_mv):
            return {
                "instrument":          inst,
                "market_value":        round(inst_mv, 2),
                "position":            position_val,
                "risk_position":       risk_pos,
                "clip":                clip,
                "uplimit":             int(uplimit_value) if uplimit_value is not None else None,
                "position_type":       pos_type,
                "close_profit":        round(cp, 2),
                "position_profit":     round(pp, 2),
                "total_pnl":           round(cp + pp, 2),
                "instrument_margin":   round(inst_margin, 2),
                "exchange":            exchange,
                "last_trade_time":     last_trade_time,
                "risk_match":          risk_match,
                "_warnings":           "; ".join(inst_warnings),
                **trade_stats,
            }

        if long_pos > 0 or short_pos > 0 or (risk_pos is not None and risk_pos != 0):

            if long_pos > 0:
                try:
                    cp_l  = float(long_rows["close_profit"].iloc[0])    if not long_rows.empty else 0.0
                    pp_l  = float(long_rows["position_profit"].iloc[0]) if not long_rows.empty else 0.0
                    imv_l = price * long_pos * multiplier
                    img_l = imv_l * margin_ratio_inst
                    market_value          += imv_l
                    instrument_margin_max  = max(img_l, instrument_margin_max)
                    detail_rows.append(_make_row("LONG", int(long_pos), cp_l, pp_l, img_l, imv_l))
                except Exception as e:
                    inst_warnings.append(f"LONG row error: {e}")
                    has_warning = True

            if short_pos > 0:
                try:
                    cp_s  = float(short_rows["close_profit"].iloc[0])    if not short_rows.empty else 0.0
                    pp_s  = float(short_rows["position_profit"].iloc[0]) if not short_rows.empty else 0.0
                    imv_s = price * short_pos * multiplier
                    market_value += imv_s
                    detail_rows.append(_make_row("SHORT", -int(short_pos), cp_s, pp_s, 0.0, imv_s))
                except Exception as e:
                    inst_warnings.append(f"SHORT row error: {e}")
                    has_warning = True

        if long_pos == 0 and short_pos == 0 and risk_pos is not None and risk_pos != 0:
            detail_rows.append(_make_row("NONE", 0, 0.0, 0.0, 0.0, 0.0))

    # ── 产品级 8 列汇总 ───────────────────────────────────────
    try:
        product_trade_stats = _aggregate_product_trade_stats(trade_df, instruments, sd_df)
    except Exception as e:
        warnings_list.append(f"product trade stats error: {e}")
        product_trade_stats = {k: 0 for k in [
            "BuyOpenNumber", "BuyOpenMarketValue",
            "BuyCloseNumber", "BuyCloseMarketValue",
            "SellOpenNumber", "SellOpenMarketValue",
            "SellCloseNumber", "SellCloseMarketValue",
        ]}

    data.update(product_trade_stats)
    data["market_value"]      = market_value
    data["product_low_limit"] = market_value / balance if balance > 0 else 0.0
    data["max_margin"]        = instrument_margin_max / balance if balance > 0 else 0.0

    try:
        data["update_time"] = _extract_latest_update_time(ai_df, pd_df, sd_df)
    except Exception as e:
        warnings_list.append(f"update_time error: {e}")

    data["warnings"] = " | ".join(warnings_list)
    detail_df = pd.DataFrame(detail_rows) if detail_rows else None
    return data, detail_df, {"has_warning": has_warning, "has_risk": has_risk}


# ─────────────────────────────────────────────
# SHARED FILE LOADER
# ─────────────────────────────────────────────

def load_shared_files(market, path, current_date, market_open):
    errors = []
    data_date, _ = get_data_date(market, path, current_date, market_open)

    sd_df, e = safe_read_csv(get_static_info_path(market))
    if e:
        errors.append(e)

    future_df, e = safe_read_csv(get_market_data_path(market, data_date))
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
# OVERVIEW TOOLTIP
# ─────────────────────────────────────────────

def display_overview_with_tooltips(styled_df):
    st.dataframe(styled_df, use_container_width=True)
    st.markdown("---")

    with st.expander("Overview 字段完整说明", expanded=False):
        field_data = {
            "字段名": [
                "market", "product", "broker", "init_capital",
                "balance", "pre_balance", "market_value",
                "cost", "net_return", "fee", "pnl",
                "max_margin", "product_low_limit", "margin", "margin_ratio",
                "BuyOpenNumber",  "BuyOpenMarketValue",
                "BuyCloseNumber", "BuyCloseMarketValue",
                "SellOpenNumber", "SellOpenMarketValue",
                "SellCloseNumber","SellCloseMarketValue",
                "update_time", "time", "deposit_withdraw", "warnings",
            ],
            "分类": [
                "市场","市场","市场","资金",
                "资金","资金","持仓",
                "资金","资金","资金","资金",
                "风险","风险","风险","风险",
                "交易统计","交易统计","交易统计","交易统计",
                "交易统计","交易统计","交易统计","交易统计",
                "时间","时间","资金","系统",
            ],
            "说明": [
                "市场类型：cncf=商品期货 / cnif=股指期货",
                "产品/策略代码",
                "交易券商：dz=东正 / zx=中信",
                "初始资金 = pre_balance × aum_mul（或自定义公式）",
                "当前账户余额",
                "前一交易日余额",
                "当前持仓市值 = sum(数量 × 价格 × 乘数)",
                "累计手续费",
                "净收益 = 盈亏 - 手续费",
                "手续费占比 = cost / init_capital",
                "收益率 = net_return / init_capital",
                "最大单合约保证金占比，警告 > 25%",
                "持仓市值占比，警告 < 0.8",
                "当前占用保证金",
                "保证金占用比",
                "【买开手数】direction=66(B) & offset=79(O) 的成交 volume 合计",
                "【买开市值】sum(price × volume × 乘数)，条件同上",
                "【买平手数】direction=66(B) & offset in {67(C),84(T)} 的成交 volume 合计",
                "【买平市值】sum(price × volume × 乘数)，条件同上",
                "【卖开手数】direction=83(S) & offset=79(O) 的成交 volume 合计",
                "【卖开市值】sum(price × volume × 乘数)，条件同上",
                "【卖平手数】direction=83(S) & offset in {67(C),84(T)} 的成交 volume 合计",
                "【卖平市值】sum(price × volume × 乘数)，条件同上",
                "最后数据更新时间戳",
                "仪表板查询时刻",
                "净入出金 = 入金 - 出金",
                "数据加载或计算警告信息",
            ],
        }
        st.dataframe(pd.DataFrame(field_data), use_container_width=True, hide_index=True)
        st.markdown("---")
        st.markdown("""
**ASCII 编码速查（trade_data 实际存储格式）：**

| 字段 | 数值 | 含义 |
|---|---|---|
| direction | 66 | B = 买 |
| direction | 83 | S = 卖 |
| offset_flag | 79 | O = 开仓 |
| offset_flag | 67 | C = 平仓 |
| offset_flag | 84 | T = 平今（归入平仓统计） |

**风险阈值：** `max_margin` > 25% 红色告警；`product_low_limit` < 0.8 红色告警（ly1h 黄色）
        """)


# ─────────────────────────────────────────────
# BUILD SUMMARY TABLE
# ─────────────────────────────────────────────

def build_summary_table(df: pd.DataFrame) -> pd.DataFrame:
    df_numeric = df.copy()
    for col in ["balance", "pre_balance", "init_capital", "cost", "net_return", "market_value"]:
        if col in df_numeric.columns:
            df_numeric[col] = pd.to_numeric(
                df_numeric[col].astype(str).str.replace(",", ""), errors="coerce"
            ).fillna(0)

    def _build_row(label, subset):
        aum        = subset["init_capital"].sum()
        cost       = subset["cost"].sum()
        net_return = subset["net_return"].sum()
        return {
            "summary": label,
            "aum":        int(aum),
            "cost":       int(cost),
            "net_return": int(net_return),
            "pnl":        f"{(net_return/aum*100) if aum > 0 else 0:.3f}%",
        }

    rows = []
    cncf = df_numeric[df_numeric["market"] == "cncf"]
    cnif = df_numeric[df_numeric["market"] == "cnif"]
    if not cncf.empty:
        rows.append(_build_row("cncf", cncf))
    if not cnif.empty:
        rows.append(_build_row("cnif", cnif))
    rows.append(_build_row("cn_all", df_numeric))

    summary_df = pd.DataFrame(rows)
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

            summary_rows      = []
            detail_map        = {}
            detail_status_map = {}
            global_file_errors = []
            shared_cache      = {}

            for cfg in PRODUCT_CONFIGS:
                ft   = cfg["market"]
                path = cfg["path"]
                name = cfg["product"]

                market_open = is_market_open(ft)
                data_date_for_shared, _ = get_data_date(ft, path, current_date, market_open)
                cache_key = (ft, data_date_for_shared)

                if cache_key not in shared_cache:
                    sd_df, future_df, _, errs = load_shared_files(ft, path, current_date, market_open)
                    shared_cache[cache_key] = (sd_df, future_df, errs)
                    global_file_errors.extend(errs)

                sd_df, future_df, _ = shared_cache[cache_key]

                margin_path = get_margin_file_path(path, ft, data_date_for_shared)
                margin_df, m_err = safe_read_csv(margin_path) if margin_path else (None, None)
                if m_err:
                    global_file_errors.append(m_err)

                try:
                    row, detail_df, detail_status = calculate_product(
                        cfg=cfg, path=path, broker=cfg["broker"], product=name,
                        market=ft, current_date=current_date, market_open=market_open,
                        shared_sd_df=sd_df, shared_future_df=future_df, shared_margin_df=margin_df,
                    )
                except Exception as calc_err:
                    row = dict(DEFAULT_SUMMARY)
                    row.update({
                        "market": "cncf" if ft == "commodity" else "cnif",
                        "product": name, "broker": cfg["broker"],
                        "time": now.strftime("%H:%M:%S"),
                        "warnings": f"Calculation error: {calc_err}",
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
                            send_alert(f"[ALERT] product_low_limit < 0.8 | broker={row['broker']} product={name}")
                        if imu > 0.25:
                            send_alert(f"[ALERT] max_margin > 0.25 | broker={row['broker']} product={name}")
                    except (ValueError, TypeError):
                        pass

            # ── Build overview DataFrame ───────────────────────
            df = pd.DataFrame(summary_rows, columns=SUMMARY_COLS)

            for col in ["balance", "pre_balance", "market_value",
                        "deposit_withdraw", "cost", "net_return", "init_capital", "margin"]:
                df[col] = (
                    pd.to_numeric(df[col], errors="coerce")
                    .fillna(0).round(0).astype(int)
                    .apply(lambda x: f"{x:,}")
                )

            trade_stat_cols = [
                "BuyOpenNumber",  "BuyOpenMarketValue",
                "BuyCloseNumber", "BuyCloseMarketValue",
                "SellOpenNumber", "SellOpenMarketValue",
                "SellCloseNumber","SellCloseMarketValue",
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
                    '<div style="text-align:center;font-weight:bold;font-size:28px;margin-bottom:12px;">'
                    'Futures Monitor Dashboard</div>',
                    unsafe_allow_html=True,
                )

                st.markdown("---")
                st.subheader("Trading Summary")
                st.dataframe(build_summary_table(df), use_container_width=True)

                if global_file_errors:
                    st.error("**Missing / unreadable files:**\n\n"
                             + "\n\n".join(f"- {e}" for e in global_file_errors))

                st.markdown("---")
                st.subheader("Overview")
                display_overview_with_tooltips(styled_df)

                st.markdown("---")
                st.subheader("Per-Instrument Detail")

                for prod_path, (cfg, ddf) in detail_map.items():
                    market_label  = "CNCF" if cfg["market"] == "commodity" else "CNIF"
                    status        = detail_status_map.get(prod_path, {})
                    prefix        = "[RED] " if status.get("has_risk") else ("[WARN] " if status.get("has_warning") else "")
                    title         = f"{prefix}[{market_label}] {cfg['product']} | {cfg['broker']}"

                    with st.expander(title, expanded=False):
                        display_cols = [
                            "instrument", "market_value",
                            "position", "risk_position", "clip", "uplimit",
                            "close_profit", "position_profit", "total_pnl",
                            "instrument_margin", "exchange", "last_trade_time",
                            "BuyOpenNumber",  "BuyOpenMarketValue",
                            "BuyCloseNumber", "BuyCloseMarketValue",
                            "SellOpenNumber", "SellOpenMarketValue",
                            "SellCloseNumber","SellCloseMarketValue",
                        ]
                        display_ddf = ddf[[c for c in display_cols if c in ddf.columns]].copy()

                        # ★ 新增：风险状态指示列
                        def _get_risk_indicator(row_idx):
                            """为每一行生成风险指示符号"""
                            if row_idx >= len(ddf):
                                return "⚪"
                            row = ddf.iloc[row_idx]
                            
                            # 检查风险匹配
                            if row.get("risk_match") == "red":
                                return "🔴 仓位异常"  # 红圈 + 标签
                            
                            # 检查保证金
                            try:
                                instr_margin = float(row.get("instrument_margin", 0))
                                balance = float(df[df["product"] == cfg["product"]]["balance"].iloc[0]
                                            .replace(",", "")) if cfg["product"] in df["product"].values else 1
                                if instr_margin / balance > 0.25 if balance > 0 else False:
                                    return "🟠 保证金高"  # 橙圈
                            except (ValueError, TypeError, IndexError):
                                pass
                            
                            return "🟢"  # 绿圈，正常
                        
                        # 添加指示符列到显示 dataframe 最前
                        display_ddf.insert(0, "状态", [_get_risk_indicator(i) for i in range(len(display_ddf))])

                        # 整数格式化（保持原逻辑）
                        int_cols = [
                            "market_value", "risk_position",
                            "close_profit", "position_profit", "total_pnl", "instrument_margin",
                            "BuyOpenNumber",  "BuyOpenMarketValue",
                            "BuyCloseNumber", "BuyCloseMarketValue",
                            "SellOpenNumber", "SellOpenMarketValue",
                            "SellCloseNumber","SellCloseMarketValue",
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
                            "instrument": "合约名称", "market_value": "合约市值",
                            "position": "持仓数量", "risk_position": "目标仓位",
                            "clip": "Clip", "uplimit": "Uplimit",
                            "close_profit": "平仓盈亏", "position_profit": "持仓盈亏",
                            "total_pnl": "当日盈亏", "instrument_margin": "保证金",
                            "exchange": "交易所", "last_trade_time": "最后成交时间",
                            "BuyOpenNumber":  "买开手数", "BuyOpenMarketValue":  "买开市值",
                            "BuyCloseNumber": "买平手数", "BuyCloseMarketValue": "买平市值",
                            "SellOpenNumber": "卖开手数", "SellOpenMarketValue": "卖开市值",
                            "SellCloseNumber":"卖平手数", "SellCloseMarketValue":"卖平市值",
                        }
                        display_ddf = display_ddf.rename(columns=col_mapping)

                        # ★ 改进的行着色函数：根据状态列和对应风险位置着色
                        def style_risk_match_row(row_idx):
                            styles = [""] * len(display_ddf.columns)
                            if row_idx < len(ddf) and "risk_match" in ddf.columns:
                                if ddf.iloc[row_idx].get("risk_match") == "red":
                                    # 红色：仓位异常
                                    styles = ["background-color: #ff4b4b; color: white; font-weight: bold;"] * len(display_ddf.columns)
                                else:
                                    # 绿色：正常
                                    try:
                                        instr_margin = float(ddf.iloc[row_idx].get("instrument_margin", 0))
                                        balance_val = float(
                                            df[df["product"] == cfg["product"]]["balance"].iloc[0].replace(",", "")
                                        ) if cfg["product"] in df["product"].values else 1
                                        if instr_margin / balance_val > 0.25 if balance_val > 0 else False:
                                            # 橙色：保证金过高
                                            styles = ["background-color: #ffa500; color: white; font-weight: bold;"] * len(display_ddf.columns)
                                    except (ValueError, TypeError, IndexError):
                                        pass
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

                        # ★ 新增：状态指示说明
                        with st.expander("状态指示说明", expanded=False):
                            st.markdown("""
                            | 符号 | 颜色 | 含义 | 触发条件 |
                            |---|---|---|---|
                            | 🔴 | 红 | 仓位异常 | 净仓位 ≠ 目标仓位（risk_position 不匹配） |
                            | 🟠 | 橙 | 保证金过高 | 单合约保证金占比 > 25% |
                            | 🟢 | 绿 | 正常 | 无异常风险 |
                            """)

                        # 仓位异常注释（保持原有逻辑）
                        if "risk_match" in ddf.columns and "instrument" in ddf.columns:
                            risk_red_rows = ddf[ddf["risk_match"] == "red"]
                            if not risk_red_rows.empty:
                                st.error("**🔴 Instrument Risk Errors (Position Mismatch):**")
                                for _, rr in risk_red_rows.iterrows():
                                    risk_pos_v = rr.get("risk_position")
                                    try:
                                        if risk_pos_v is not None and math.isnan(float(risk_pos_v)):
                                            risk_pos_v = 0
                                    except (TypeError, ValueError):
                                        pass
                                    st.markdown(
                                        f"- **{rr['instrument']}** ({rr.get('position_type','')}): "
                                        f"实际持仓 = `{rr.get('position', 0)}`, "
                                        f"目标仓位 = `{int(round(float(risk_pos_v))) if risk_pos_v is not None else 0}` "
                                        f"→ 净仓位与目标仓位不一致"
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
