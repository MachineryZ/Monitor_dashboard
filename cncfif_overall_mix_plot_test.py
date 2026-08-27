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
import rwp_api
import json
import re  # 新增

# ── 新增：Plotly 用于图表 ──
import plotly.graph_objects as go
from datetime import timedelta

# ── RWP API 配置 ──────────────────────────────────────
RWP_CREDENTIALS = {
    "username": "jiangl",
    "password": "666666@dunhe",
}

# ── 产品与银行账户映射 ────────────────────────────────
PRODUCT_BANK_MAPPING = {
    "/mnt/nfs_bohr_data1/china/trading_realdata/cncf_trade_data_ax1h_ya/": (58, 230),
    "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_data_baguatian": (58, 230),
    "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_data_shjq_zx":   (569, 9118),
    "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_data_shph1h_zx": (568, 9122),
    "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_date":           (215, 1049),
    "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_jz1h":           (319, 1604),
    "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_ly1h":           (34, 216),
    "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_zz1h":           (215, 1049),
    "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_zz1h_ya":           (215, 1049),
}

_rwp_api_cache: dict[str, float] = {}
_rwp_login_status = False

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
        "path":         "/mnt/nfs_bohr_data1/china/trading_realdata/cncf_trade_data_ax1h_ya",
        "broker":       "ya",
        "product":      "ax1h_ya",
        "market":       "commodity",
        "init_capital": 0,
        "aum_mul":      4.0,
        "db_product":   "commodity_melt_ax1h",
    },
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
        "db_product":   "commodity_melt_shjq_zx",
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
        "broker":       "dz",
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
    {
        "path":         "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_zz1h_ya",
        "broker":       "ya",
        "product":      "zz1h_ya",
        "market":       "futures",
        "init_capital": 0,
        "aum_mul":      4.7858,
        "db_product":   None,
    },
]

# ─────────────────────────────────────────────
# RWP API 交互函数（不变）
# ─────────────────────────────────────────────

def rwp_api_login() -> bool:
    global _rwp_login_status
    try:
        res = rwp_api.login(
            RWP_CREDENTIALS["username"],
            RWP_CREDENTIALS["password"]
        )
        _rwp_login_status = (res == 1)
        return _rwp_login_status
    except Exception as e:
        import traceback
        traceback.print_exc()
        _rwp_login_status = False
        return False

def get_bank_account_balance(path: str) -> float | None:
    global _rwp_login_status
    if path not in PRODUCT_BANK_MAPPING:
        return None
    cache_key = f"bank_{path}"
    if cache_key in _rwp_api_cache:
        return _rwp_api_cache[cache_key]
    if not _rwp_login_status:
        if not rwp_api_login():
            return None
    try:
        fund_id, unit_id = PRODUCT_BANK_MAPPING[path]
        if fund_id == 569 or fund_id == 568 or fund_id == 215 or fund_id == 58 or fund_id == 319 or fund_id == 34:
            today_date = datetime.datetime.now().strftime("%Y%m%d")
            req_text = {"fund_id": fund_id, "unit_id": unit_id, "start_date": today_date}
            req_json = json.dumps(req_text)
            resp = rwp_api.get_unit_asset_chart(req_json)
            if resp.get("unit_list", None) is None:
                bank_account = None
            else:
                bank_account = float(resp['unit_list'][0]['nav_list'][0]['total_asset'])
            _rwp_api_cache[cache_key] = bank_account
        return bank_account
    except Exception:
        import traceback
        traceback.print_exc()
        return None

def clear_bank_cache():
    global _rwp_api_cache
    _rwp_api_cache.clear()

# ─────────────────────────────────────────────
# CLICKHOUSE CLIENT & 数据库查询（不变）
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
    query = f"SELECT coef FROM commodity_meta.product_uplimit_coef WHERE product_name = 'all' LIMIT 1"
    try:
        result = client.query_df(query)
        if not result.empty:
            return float(result.iloc[0]["coef"])
        return None
    except Exception:
        return None

# ─────────────────────────────────────────────
# 辅助函数（不变）
# ─────────────────────────────────────────────

def load_uplimit_holding_position(path: str, market: str, data_date: int) -> dict[str, float] | None:
    csv_path = get_margin_file_path(path, market, data_date)
    if not csv_path:
        return None
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

def get_date_from_calendar() -> tuple[int, int]:
    date     = datetime.datetime.now().date()
    date_int = int(date.strftime("%Y%m%d"))
    date_list = np.loadtxt(CALENDAR_PATH, dtype=np.int64, ndmin=1)
    pos = np.searchsorted(date_list, date_int, side="right")
    date_int = int(date_list[pos-1])
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

def safe_read_csv(filepath: str | list[str]) -> tuple[pd.DataFrame | None, str | None]:
    if isinstance(filepath, str):
        filepath = [filepath]
    dfs = []
    for path in filepath:
        if not os.path.exists(path):
            return None, f"File not found: {path}"
        if os.path.getsize(path) == 0:
            return None, f"File is completely empty (0 bytes): {path}"
        try:
            df = pd.read_csv(path)
            dfs.append(df)
        except Exception as e:
            return None, f"CSV parse error [{path}]: {e}"
    if not dfs:
        return None, "No CSV files provided"
    try:
        df = pd.concat(dfs, ignore_index=True)
        return df, None
    except Exception as e:
        return None, f"CSV concat error: {e}"

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

def get_data_date(market: str, path: str, current_date: int, market_open: bool) -> tuple[int, str]:
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

def get_margin_file_path(path: str, market: str, data_date: int) -> list[str]:
    mapping = {
        "/mnt/nfs_bohr_data1/china/trading_realdata/cncf_trade_data_ax1h_ya":
            [f"/cpfs/rawdata/cncf_all_nedd_before_open/margin_uplimit_ax1h_ya_{data_date}.csv",
             f"/cpfs/rawdata/cnif_all_need_before_open/ziyong_margin_uplimit.csv"],
        "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_data_baguatian":
            [f"/cpfs/rawdata/cncf_all_nedd_before_open/margin_uplimit_baguatian_{data_date}.csv",
             f"/cpfs/rawdata/cnif_all_need_before_open/ziyong_margin_uplimit.csv"],
        "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_data_shjq_zx":
            [f"/cpfs/rawdata/cncf_all_nedd_before_open/margin_uplimit_shjq_zx_{data_date}.csv",
             f"/cpfs/rawdata/cnif_all_need_before_open/ziyong_margin_uplimit.csv"],
        "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_data_shph1h_zx":
            [f"/cpfs/rawdata/cncf_all_nedd_before_open/margin_uplimit_{data_date}.csv",
             f"/cpfs/rawdata/cnif_all_need_before_open/ziyong_margin_uplimit.csv"],
        "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_date":
            [f"/cpfs/rawdata/cncf_all_nedd_before_open/margin_uplimit_{data_date}.csv",
             f"/cpfs/rawdata/cnif_all_need_before_open/ziyong_margin_uplimit.csv"],
        "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_jz1h":
            [f"/cpfs/rawdata/cnif_all_need_before_open/margin_uplimit_jz1h_{data_date}.csv"],
        "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_ly1h":
            [f"/cpfs/rawdata/cnif_all_need_before_open/margin_uplimit_ly1h_{data_date}.csv"],
        "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_zz1h":
            [f"/cpfs/rawdata/cnif_all_need_before_open/margin_uplimit_zz1h_{data_date}.csv"],
        "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_zz1h_ya":
            [f"/cpfs/rawdata/cnif_all_need_before_open/margin_uplimit_zz1h_{data_date}.csv"],
    }
    return mapping.get(path, [])

def get_static_info_path(market: str) -> list[str]:
    return ["/cpfs/rawdata/cncf_all_nedd_before_open/ins_static_info.csv",
            "/cpfs/rawdata/cnif_all_need_before_open/ins_static_info.csv"]

def get_market_data_path(market: str, data_date: int) -> list[str]:
    kinds = ["commodity", "futures"]
    if datetime.datetime.now().hour >= 20 or datetime.datetime.now().hour < 9 or (datetime.datetime.now().hour == 9 and datetime.datetime.now().minute < 30):
        kinds.remove("futures")
    return [f"/mnt/nfs_bohr_data1/china/trading_realdata/partial_market_data_realtime/{kind}/{data_date}.csv" for kind in kinds]

def get_trade_file_path(path: str, data_date: int) -> str:
    return os.path.join(path, f"trade_data_{data_date}.csv")

def get_order_file_path(path: str, data_date: int) -> str:
    return os.path.join(path, f"order_data_{data_date}.csv")

def send_alert(message: str):
    webhook_url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=1f5ccb85-9f37-46a5-b5a7-d5e0a7cc9b3c"
    webhook_url_ope = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=a125709c-94f3-4234-8b58-8d591845d150"
    msg = {"msgtype": "text", "text": {"content": message}}
    try:
        requests.post(webhook_url, data=json.dumps(msg), timeout=5)
        requests.post(webhook_url_ope, data=json.dumps(msg), timeout=5)
    except Exception:
        pass

def safe_float(val):
    try:
        if isinstance(val, str) and val.endswith("%"):
            num_str = val.replace("%", "")
            return float(num_str) / 100
        return float(val)
    except (ValueError, TypeError):
        return 0.0

# ─────────────────────────────────────────────
# PRICE CACHE MANAGEMENT（不变）
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
# RISK POSITION LOADER（不变）
# ─────────────────────────────────────────────

def load_risk_position(market: str, product: str, data_date: int) -> dict[str, float] | None:
    result = {}
    if market == "commodity":
        strategy_mapping = {
            "ax1h_ya": "cncf_melt_ax1h_ya_bohr",
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
                all_stats_str = str(row.get("all_stats", "")).strip()
                all_stats_str = all_stats_str.strip("[]").strip()
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
# 交易统计函数（不变）
# ─────────────────────────────────────────────

_OPEN_FLAGS  = {79, 48, 0}
_CLOSE_FLAGS = {67, 68}

def _calc_trade_stats_product(trade_df: pd.DataFrame | None, price_map: dict, multiplier_map: dict) -> dict:
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
    needed = {"instrument_id", "direction", "offset_flag", "volume"}
    if not needed.issubset(trade_df.columns):
        return zero
    try:
        df = trade_df.copy()
        df["direction"]   = pd.to_numeric(df["direction"],   errors="coerce").fillna(0).astype(int)
        df["offset_flag"] = pd.to_numeric(df["offset_flag"], errors="coerce").fillna(0).astype(int)
        df["volume"]      = pd.to_numeric(df["volume"],      errors="coerce").fillna(0)
        buy_open   = df[(df["direction"] == 66) & (df["offset_flag"].isin(_OPEN_FLAGS))]
        buy_close  = df[(df["direction"] == 66) & (df["offset_flag"].isin(_CLOSE_FLAGS))]
        sell_open  = df[(df["direction"] == 83) & (df["offset_flag"].isin(_OPEN_FLAGS))]
        sell_close = df[(df["direction"] == 83) & (df["offset_flag"].isin(_CLOSE_FLAGS))]
        def _mv(subset: pd.DataFrame) -> float:
            total = 0.0
            for inst, grp in subset.groupby("instrument_id"):
                vol = grp["volume"].sum()
                p   = price_map.get(inst, 0.0)
                mul = multiplier_map.get(inst, 1.0)
                total += vol * p * mul
            return round(total, 2)
        result = {
            "BuyOpenNumber":        int(buy_open["volume"].sum()),
            "BuyOpenMarketValue":   _mv(buy_open),
            "BuyCloseNumber":       int(buy_close["volume"].sum()),
            "BuyCloseMarketValue":  _mv(buy_close),
            "SellOpenNumber":       int(sell_open["volume"].sum()),
            "SellOpenMarketValue":  _mv(sell_open),
            "SellCloseNumber":      int(sell_close["volume"].sum()),
            "SellCloseMarketValue": _mv(sell_close),
        }
        return result
    except Exception:
        return zero

def _calc_trade_stats_for_inst(trade_df: pd.DataFrame | None, inst: str, price: float, multiplier: float) -> dict:
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
    needed = {"instrument_id", "direction", "offset_flag", "volume"}
    if not needed.issubset(trade_df.columns):
        return zero
    try:
        df = trade_df[trade_df["instrument_id"] == inst].copy()
        if df.empty:
            return zero
        df["direction"]   = pd.to_numeric(df["direction"],   errors="coerce").fillna(0).astype(int)
        df["offset_flag"] = pd.to_numeric(df["offset_flag"], errors="coerce").fillna(0).astype(int)
        df["volume"]      = pd.to_numeric(df["volume"],      errors="coerce").fillna(0)
        buy_open_n   = int(df[(df["direction"] == 66) & (df["offset_flag"].isin(_OPEN_FLAGS))]["volume"].sum())
        buy_close_n  = int(df[(df["direction"] == 66) & (df["offset_flag"].isin(_CLOSE_FLAGS))]["volume"].sum())
        sell_open_n  = int(df[(df["direction"] == 83) & (df["offset_flag"].isin(_OPEN_FLAGS))]["volume"].sum())
        sell_close_n = int(df[(df["direction"] == 83) & (df["offset_flag"].isin(_CLOSE_FLAGS))]["volume"].sum())
        mv_mul = price * multiplier
        return {
            "BuyOpenNumber":        buy_open_n,
            "BuyOpenMarketValue":   round(buy_open_n  * mv_mul, 2),
            "BuyCloseNumber":       buy_close_n,
            "BuyCloseMarketValue":  round(buy_close_n * mv_mul, 2),
            "SellOpenNumber":       sell_open_n,
            "SellOpenMarketValue":  round(sell_open_n * mv_mul, 2),
            "SellCloseNumber":      sell_close_n,
            "SellCloseMarketValue": round(sell_close_n * mv_mul, 2),
        }
    except Exception:
        return zero

# ─────────────────────────────────────────────
# STYLERS（不变）
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

def style_margin_ratio(val):
    try:
        if float(val.rstrip('%')) / 100 > 0.75:
            return "background-color: #ff4b4b; color: white"
    except (ValueError, TypeError):
        pass
    return ""

# ─────────────────────────────────────────────
# CORE: calculate_product（不变）
# ─────────────────────────────────────────────

SUMMARY_COLS = [
    "market", "product", "init_capital", "balance", "pre_balance",
    "market_value", "cost", "net_return", "fee", "pnl",
    "max_margin", "product_low_limit", "margin", "margin_ratio",
    "update_time", "broker", "bank", "time",
    "BuyOpenNumber",  "BuyOpenMarketValue",  "BOMVRatio",
    "BuyCloseNumber", "BuyCloseMarketValue", "BCMVRatio",
    "SellOpenNumber", "SellOpenMarketValue", "SOMVRatio",
    "SellCloseNumber","SellCloseMarketValue","SCMVRatio",
    "warnings", "deposit_withdraw", "is_market_open",
]

DEFAULT_SUMMARY = {
    "market": "", "product": "", "broker": "", "init_capital": 0,
    "balance": 0, "pre_balance": 0, "bank": 0, "market_value": 0,
    "cost": 0, "net_return": 0, "fee": "0.000%", "pnl": "0.000%",
    "max_margin": 0.0, "product_low_limit": 0.0, "margin": 0.0,
    "margin_ratio": "0.000%", "time": "", "deposit_withdraw": 0,
    "warnings": "", "is_market_open": False,
    "BuyOpenNumber": 0, "BuyOpenMarketValue": 0, "BOMVRatio": "0.000%",
    "BuyCloseNumber": 0, "BuyCloseMarketValue": 0, "BCMVRatio": "0.000%",
    "SellOpenNumber": 0, "SellOpenMarketValue": 0, "SOMVRatio": "0.000%",
    "SellCloseNumber": 0, "SellCloseMarketValue": 0, "SCMVRatio": "0.000%",
}

def _get_last_trade_time_adjusted(trade_df: pd.DataFrame | None, inst: str, data_date: int, current_date: int, market: str) -> str:
    if trade_df is None or trade_df.empty:
        return ""
    inst_col = "instrument_id" if "instrument_id" in trade_df.columns else ("instrument" if "instrument" in trade_df.columns else None)
    if inst_col is None:
        return ""
    t_rows = trade_df[trade_df[inst_col] == inst]
    if t_rows.empty:
        return ""
    time_col = "trade_time" if "trade_time" in t_rows.columns else ("update_time" if "update_time" in t_rows.columns else None)
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

def _check_risk_position_match(long_pos: float | None, short_pos: float | None, risk_pos: float | None, uplimit_value: float | None = None) -> str:
    if risk_pos is None:
        return "no_risk_data"
    long_int  = int(round(long_pos))  if long_pos  is not None else 0
    short_int = int(round(short_pos)) if short_pos is not None else 0
    risk_int  = int(round(risk_pos))
    net_pos = long_int - short_int
    if uplimit_value is not None:
        uplimit_int = int(uplimit_value)
        if abs(risk_int) >= uplimit_int:
            return "uplimit_hit"
    if net_pos != risk_int:
        return "red"
    return "matched"

def calculate_product(cfg: dict, path: str, broker: str, product: str, market: str,
                      current_date: int, market_open: bool, shared_sd_df: pd.DataFrame | None,
                      shared_future_df: pd.DataFrame | None, shared_margin_df: pd.DataFrame | None) -> tuple[dict, pd.DataFrame | None, dict]:
    warnings_list: list[str] = []
    data = dict(DEFAULT_SUMMARY)
    data["market"]         = "cncf" if market == "commodity" else "cnif"
    data["product"]        = product
    data["broker"]         = broker
    data["time"]           = datetime.datetime.now().strftime("%H:%M:%S")
    data["is_market_open"] = market_open
    is_position_empty = False
    data["is_position_empty"] = False

    data_date, time_suffix = get_data_date(market, path, current_date, market_open)
    data["time"] += time_suffix

    # account_info
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
            margin_ratio = margin / balance if balance > 0 else 0
        except Exception as e:
            warnings_list.append(f"account_info parsing error: {e}")
            balance = pre_balance = fee = margin = 0.0
            margin_ratio = 0
    data["margin_ratio"]     = f"{100*margin_ratio:.2f}%"
    data["balance"]          = balance
    data["pre_balance"]      = pre_balance
    data["deposit_withdraw"] = deposit - withdraw
    data["cost"]             = fee
    data["margin"]           = margin
    init_capital = resolve_init_capital(cfg, (pre_balance + deposit - withdraw), balance)
    data["init_capital"] = init_capital

    try:
        bank_account = get_bank_account_balance(path)
        if bank_account is not None:
            data["bank"] = bank_account
        else:
            data["bank"] = pre_balance
    except Exception as e:
        warnings_list.append(f"bank account fetch error: {e}")
        data["bank"] = pre_balance

    # position_data
    pd_path = os.path.join(path, f"position_data_{data_date}.csv")
    pd_df, pd_err = safe_read_csv(pd_path)
    if pd_err:
        warnings_list.append(pd_err)
        data["warnings"] = " | ".join(warnings_list)
        return data, None, {"has_warning": True, "has_risk": False}
    if pd_df.empty:
        warnings_list.append(f"Header-only file (using defaults): {pd_path}")
        pd_df = pd.DataFrame(columns=["instrument_id", "pos_type", "position", "position_profit", "close_profit", "pre_settlement_price"])
        is_position_empty = True
        data["is_position_empty"] = True

    try:
        abs_return = float((pd_df.get("position_profit", pd.Series([0])).fillna(0) + pd_df.get("close_profit", pd.Series([0])).fillna(0)).sum())
    except Exception as e:
        warnings_list.append(f"PnL calculation error: {e}")
        abs_return = 0.0

    data["net_return"] = abs_return - fee
    if init_capital > 0:
        fee_pct = (fee / init_capital) * 100
        data["fee"] = f"{fee_pct:.3f}%"
    else:
        data["fee"] = "0.000%"
    if init_capital > 0:
        pnl = round((data["net_return"]) / init_capital * 100, 3)
    else:
        pnl = 0.0
    data["pnl"] = f"{pnl:.3f}%"

    sd_df     = shared_sd_df
    future_df = shared_future_df
    margin_df = shared_margin_df

    risk_position_map = load_risk_position(market, product, data_date)
    db_product = cfg.get("db_product")
    clip = get_product_clip(db_product) if db_product else None
    uplimit_holding_position_data = None
    if market == "commodity":
        uplimit_holding_position_data = load_uplimit_holding_position(path, market, data_date)

    market_value          = 0.0
    instrument_margin_max = 0.0
    detail_rows: list[dict] = []
    has_warning = False
    has_risk = False
    if is_position_empty:
        has_warning = True

    instruments = pd_df["instrument_id"].dropna().unique().tolist() if not pd_df.empty else []
    trade_path = get_trade_file_path(path, data_date)
    trade_df, trade_err = safe_read_csv(trade_path)
    if trade_err:
        warnings_list.append(trade_err)
        trade_df = None

    _price_map_for_product      = {}
    _multiplier_map_for_product = {}

    for inst in instruments:
        inst_warnings: list[str] = []
        try:
            long_rows  = pd_df.query(f"instrument_id == '{inst}' and pos_type == 'LONG'")
            short_rows = pd_df.query(f"instrument_id == '{inst}' and pos_type == 'SHORT'")
            long_pos   = int(long_rows["position"].iloc[0])  if not long_rows.empty  else 0.0
            short_pos  = int(short_rows["position"].iloc[0]) if not short_rows.empty else 0.0
            long_today_pos = long_yd_pos = short_today_pos = short_yd_pos = 0
            if not long_rows.empty:
                if "today_position" in long_rows.columns:
                    long_today_pos = int(float(long_rows["today_position"].iloc[0]))
                if "yd_position" in long_rows.columns:
                    long_yd_pos = int(float(long_rows["yd_position"].iloc[0]))
            if not short_rows.empty:
                if "today_position" in short_rows.columns:
                    short_today_pos = int(float(short_rows["today_position"].iloc[0]))
                if "yd_position" in short_rows.columns:
                    short_yd_pos = int(float(short_rows["yd_position"].iloc[0]))
        except Exception as e:
            inst_warnings.append(f"position parsing error: {e}")
            long_pos = short_pos = 0
            long_today_pos = long_yd_pos = short_today_pos = short_yd_pos = 0
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

        margin_ratio = 0.0
        try:
            if margin_df is not None and not margin_df.empty:
                m_row = margin_df[margin_df["instrument"] == inst]
                if not m_row.empty:
                    margin_ratio = float(m_row["margin_ratio"].iloc[0])
        except Exception as e:
            inst_warnings.append(f"margin_ratio error: {e}")
            has_warning = True

        price = get_price(inst)
        if price is None:
            inst_warnings.append(f"no price available for {inst}")
            has_warning = True
            price = 0.0

        _price_map_for_product[inst]      = price
        _multiplier_map_for_product[inst] = multiplier

        try:
            last_trade_time = _get_last_trade_time_adjusted(trade_df, inst, data_date, current_date, market)
        except Exception as e:
            inst_warnings.append(f"trade_time error: {e}")
            has_warning = True
            last_trade_time = ""

        uplimit_value = None
        try:
            if market == "commodity":
                uplimit_value = calculate_uplimit(inst, "all", uplimit_holding_position_data)
        except Exception as e:
            inst_warnings.append(f"uplimit calculation error: {e}")
            has_warning = True

        try:
            risk_pos = risk_position_map.get(inst) if risk_position_map else None
        except Exception as e:
            inst_warnings.append(f"risk_position error: {e}")
            has_warning = True
            risk_pos = None

        risk_match = _check_risk_position_match(long_pos, short_pos, risk_pos, uplimit_value)
        if risk_match in ("red", "uplimit_hit"):
            has_risk = True
            if risk_match == "uplimit_hit":
                inst_warnings.append(f"目标仓位达到开仓上限 (uplimit={int(uplimit_value) if uplimit_value is not None else 'N/A'})")

        inst_trade_stats = _calc_trade_stats_for_inst(trade_df, inst, price, multiplier)

        if long_pos > 0 or short_pos > 0 or (risk_pos is not None and risk_pos != 0):
            if long_pos > 0:
                try:
                    cp_long = float(long_rows["close_profit"].iloc[0]) if not long_rows.empty else 0.0
                    pp_long = float(long_rows["position_profit"].iloc[0]) if not long_rows.empty else 0.0
                    total_pnl_long = cp_long + pp_long
                    inst_margin_long = price * long_pos * multiplier * margin_ratio
                    inst_market_value_long = price * long_pos * multiplier
                    market_value += inst_market_value_long
                    instrument_margin_max = max(inst_margin_long, instrument_margin_max)
                    row_dict = {
                        "instrument":        inst,
                        "market_value":      round(inst_market_value_long, 2),
                        "position":          int(long_pos),
                        "yd_position":       long_yd_pos,
                        "today_position":    long_today_pos,
                        "risk_position":     risk_pos,
                        "clip":              clip,
                        "uplimit":           int(uplimit_value) if uplimit_value is not None else None,
                        "position_type":     "LONG",
                        "close_profit":      round(cp_long, 2),
                        "position_profit":   round(pp_long, 2),
                        "total_pnl":         round(total_pnl_long, 2),
                        "instrument_margin": round(inst_margin_long, 2) if abs(inst_margin_long) > abs(price * short_pos * multiplier * margin_ratio) else round(price * short_pos * multiplier * margin_ratio, 2),
                        "exchange":          exchange,
                        "last_trade_time":   last_trade_time,
                        "risk_match":        risk_match,
                        "_warnings":         "; ".join(inst_warnings),
                    }
                    row_dict.update(inst_trade_stats)
                    detail_rows.append(row_dict)
                except Exception as e:
                    inst_warnings.append(f"LONG row error: {e}")
                    has_warning = True

            if short_pos > 0:
                try:
                    cp_short = float(short_rows["close_profit"].iloc[0]) if not short_rows.empty else 0.0
                    pp_short = float(short_rows["position_profit"].iloc[0]) if not short_rows.empty else 0.0
                    total_pnl_short = cp_short + pp_short
                    inst_margin_short = price * short_pos * multiplier * margin_ratio
                    inst_market_value_short = price * short_pos * multiplier
                    market_value += inst_market_value_short
                    instrument_margin_max = max(inst_margin_short, instrument_margin_max)
                    row_dict = {
                        "instrument":        inst,
                        "market_value":      round(inst_market_value_short, 2),
                        "position":          -int(short_pos),
                        "yd_position":       -int(short_yd_pos),
                        "today_position":    -int(short_today_pos),
                        "risk_position":     risk_pos,
                        "clip":              clip,
                        "uplimit":           int(uplimit_value) if uplimit_value is not None else None,
                        "position_type":     "SHORT",
                        "close_profit":      round(cp_short, 2),
                        "position_profit":   round(pp_short, 2),
                        "total_pnl":         round(total_pnl_short, 2),
                        "instrument_margin": round(inst_margin_short, 2) if abs(inst_margin_long) < abs(inst_margin_short) else round(inst_margin_short),
                        "exchange":          exchange,
                        "last_trade_time":   last_trade_time,
                        "risk_match":        risk_match,
                        "_warnings":         "; ".join(inst_warnings),
                    }
                    row_dict.update(inst_trade_stats)
                    detail_rows.append(row_dict)
                except Exception as e:
                    inst_warnings.append(f"SHORT row error: {e}")
                    has_warning = True

        if long_pos == 0 and short_pos == 0 and risk_pos is not None and risk_pos != 0:
            row_dict = {
                "instrument":        inst,
                "market_value":      0,
                "position":          0,
                "yd_position":       0,
                "today_position":    0,
                "risk_position":     risk_pos,
                "clip":              clip,
                "uplimit":           int(uplimit_value) if uplimit_value is not None else None,
                "position_type":     "NONE",
                "close_profit":      0.0,
                "position_profit":   0.0,
                "total_pnl":         0.0,
                "instrument_margin": 0.0,
                "exchange":          exchange,
                "last_trade_time":   last_trade_time,
                "risk_match":        risk_match,
                "_warnings":         "; ".join(inst_warnings),
            }
            row_dict.update(inst_trade_stats)
            detail_rows.append(row_dict)

    data["market_value"] = market_value
    data["product_low_limit"] = market_value / balance if balance > 0 else 0.0
    data["max_margin"] = instrument_margin_max / balance if balance > 0 else 0.0
    try:
        data["update_time"] = _extract_latest_update_time(ai_df, pd_df, sd_df)
    except Exception as e:
        warnings_list.append(f"update_time error: {e}")
    data["warnings"] = " | ".join(warnings_list)

    try:
        product_trade_stats = _calc_trade_stats_product(trade_df, _price_map_for_product, _multiplier_map_for_product)
        data.update(product_trade_stats)
    except Exception as e:
        warnings_list.append(f"trade stats calculation error: {e}")

    try:
        _ratio_pairs = [("BuyOpenMarketValue", "BOMVRatio"), ("BuyCloseMarketValue", "BCMVRatio"),
                        ("SellOpenMarketValue", "SOMVRatio"), ("SellCloseMarketValue", "SCMVRatio")]
        for mv_col, ratio_col in _ratio_pairs:
            mv_val = float(data.get(mv_col, 0) or 0)
            if init_capital > 0:
                data[ratio_col] = mv_val / init_capital
            else:
                data[ratio_col] = 0.0
    except Exception as e:
        warnings_list.append(f"market value ratio calculation error: {e}")

    detail_df = pd.DataFrame(detail_rows) if detail_rows else None
    if is_position_empty:
        empty_detail_df = pd.DataFrame(columns=[
            "instrument", "market_value", "position", "yd_position", "today_position",
            "risk_position", "clip", "uplimit", "position_type", "close_profit",
            "position_profit", "total_pnl", "instrument_margin", "exchange",
            "last_trade_time", "risk_match", "_warnings",
            "BuyOpenNumber", "BuyOpenMarketValue",
            "BuyCloseNumber", "BuyCloseMarketValue",
            "SellOpenNumber", "SellOpenMarketValue",
            "SellCloseNumber", "SellCloseMarketValue",
        ])
        detail_df = empty_detail_df

    detail_status = {"has_warning": has_warning, "has_risk": has_risk}
    return data, detail_df, detail_status

# ─────────────────────────────────────────────
# SHARED FILE LOADER（不变）
# ─────────────────────────────────────────────

def load_shared_files(market: str, path: str, current_date: int, market_open: bool) -> tuple[pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None, list[str]]:
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
# OVERVIEW TOOLTIP（不变）
# ─────────────────────────────────────────────

def display_overview_with_tooltips(styled_df):
    st.dataframe(styled_df, width="stretch")
    st.markdown("---")
    with st.expander("Overview 字段完整说明", expanded=False):
        field_data = {
            "字段名": [
                "market", "product", "broker", "init_capital",
                "balance", "pre_balance", "bank", "market_value",
                "cost", "ret", "net_return", "fee",
                "pnl", "max_margin", "product_low_limit",
                "margin", "margin_ratio",
                "BuyOpenNumber",  "BuyOpenMarketValue",  "BOMVRatio",
                "BuyCloseNumber", "BuyCloseMarketValue", "BCMVRatio",
                "SellOpenNumber", "SellOpenMarketValue", "SOMVRatio",
                "SellCloseNumber","SellCloseMarketValue","SCMVRatio",
                "update_time", "time", "deposit_withdraw", "warnings",
            ],
            "分类": [
                "市场", "市场", "市场", "资金",
                "资金", "资金", "资金", "持仓",
                "资金", "资金", "资金", "资金",
                "资金", "风险", "风险",
                "风险", "风险",
                "交易统计", "交易统计", "交易统计",
                "交易统计", "交易统计", "交易统计",
                "交易统计", "交易统计", "交易统计",
                "交易统计", "交易统计", "交易统计",
                "时间", "时间", "资金", "系统",
            ],
            "说明": [
                "市场类型：cncf=商品期货 / cnif=股指期货",
                "产品/策略代码",
                "交易券商",
                "初始资金/策略规模",
                "当前账户余额",
                "前一交易日余额",
                "银行账户余额（RWP API）",
                "当前持仓市值",
                "累计手续费",
                "总回报/盈亏",
                "净收益 = ret - cost",
                "手续费占比 = cost/init_capital×100%",
                "收益率 = net_return/init_capital×100%",
                "最大单合约保证金占比",
                "持仓市值占比",
                "当前占用保证金",
                "保证金占用比",
                "买入开仓手数",
                "买入开仓市值",
                "买入开仓市值占比",
                "买入平仓手数",
                "买入平仓市值",
                "买入平仓市值占比",
                "卖出开仓手数",
                "卖出开仓市值",
                "卖出开仓市值占比",
                "卖出平仓手数",
                "卖出平仓市值",
                "卖出平仓市值占比",
                "最后数据更新时间",
                "当前查询时刻",
                "净入出金",
                "警告信息",
            ],
        }
        desc_df = pd.DataFrame(field_data)
        st.dataframe(desc_df, width="stretch", hide_index=True)
        st.markdown("---")
        st.markdown("""
**风险阈值速查：**
- `max_margin` > **25%** -> 单合约保证金过高 (红色告警)
- `product_low_limit` < **0.8** -> 流动性不足 (红色告警，ly1h 为黄色)
**交易统计编码说明：**
- `direction`: 66=买(B)，83=卖(S)
- `offset_flag`: 79/48/0=开仓，67=平仓，68=平今
- 数据来源：`trade_data_{date}.csv`，字段 `volume`
        """)

# ─────────────────────────────────────────────
# BUILD SUMMARY TABLE（不变）
# ─────────────────────────────────────────────

def build_summary_table(df: pd.DataFrame) -> pd.DataFrame:
    summary_rows = []
    df_numeric = df.copy()
    for col in ["balance", "pre_balance", "bank", "init_capital", "cost", "net_return", "market_value"]:
        if col in df_numeric.columns:
            df_numeric[col] = pd.to_numeric(df_numeric[col].astype(str).str.replace(",", ""), errors="coerce").fillna(0)
    def _build_row(label: str, subset: pd.DataFrame) -> dict:
        aum        = subset["init_capital"].sum()
        cost       = subset["cost"].sum()
        net_return = subset["net_return"].sum()
        pnl_pct    = (net_return / aum * 100) if aum > 0 else 0.0
        return {"summary": label, "aum": int(aum), "cost": int(cost), "net_return": int(net_return), "pnl": f"{pnl_pct:.3f}%"}
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
# 日内图表构建与绘制函数（修正版）
# ─────────────────────────────────────────────

def load_prev_position(path: str, prev_date: int) -> pd.DataFrame | None:
    pos_path = os.path.join(path, f"position_data_{prev_date}.csv")
    if not os.path.exists(pos_path):
        return None
    df, err = safe_read_csv(pos_path)
    if err or df is None or df.empty:
        return None
    return df

def load_trade_data(path: str, date: int) -> pd.DataFrame | None:
    trade_path = os.path.join(path, f"trade_data_{date}.csv")
    if not os.path.exists(trade_path):
        return None
    df, err = safe_read_csv(trade_path)
    if err or df is None or df.empty:
        return None
    return df

def build_intraday_series(
    cfg: dict,
    current_date: int,
    static_df: pd.DataFrame | None,
    init_capital: float,
) -> dict | None:
    """
    扫描产品路径下的 position_data_YYYYMMDD_YYYYMMDD_HH:MM:SS.csv 文件，
    构建每个合约的日内时序（时间→交易分钟索引，净持仓，市值，累计盈亏）。
    返回 {instrument: DataFrame}，DataFrame 包含列：
        'time_idx'   : 从夜盘21:00开始的交易分钟索引（连续整数）
        'time_label' : 显示时间标签（如 '21:05'）
        'net_pos'    : 净持仓（多头-空头）
        'market_value' : 市值（abs(net_pos) * price * multiplier）
        'cum_pnl'    : 累计盈亏（close_profit + position_profit）
        'open_net'   : 开盘净持仓（取第一个快照的净持仓）
        'price'      : 使用价格（优先从价格缓存获取，否则用pre_settlement_price）
    """
    path = cfg["path"]
    # 获取所有 position_data_ 文件
    files = [f for f in os.listdir(path) if f.startswith("position_data_") and f.endswith(".csv")]
    if not files:
        return None

    # 使用正则解析文件名
    def parse_time_from_filename(fname: str):
        pattern = r'position_data_(\d{8})_(\d{8})_(\d{2}:\d{2}:\d{2})\.csv'
        match = re.match(pattern, fname)
        if match:
            date_str = match.group(1)
            time_str = match.group(3)
            try:
                return datetime.datetime.strptime(f"{date_str} {time_str}", "%Y%m%d %H:%M:%S")
            except ValueError:
                return None
        return None

    timed_files = []
    for f in files:
        dt = parse_time_from_filename(f)
        if dt is not None:
            timed_files.append((dt, os.path.join(path, f)))
    timed_files.sort(key=lambda x: x[0])  # 按时间排序

    if not timed_files:
        return None

    # 合约乘数映射
    mult_map = {}
    if static_df is not None and not static_df.empty:
        for _, row in static_df.iterrows():
            inst = row.get("instrument")
            mult = row.get("multiplier", 1)
            if inst:
                mult_map[inst] = float(mult)

    # 数据字典
    data_dict = {}

    # 定义交易时段（用于计算交易分钟索引）
    def get_trade_minute_index(dt: datetime.datetime, base_date: datetime.datetime) -> int:
        start = base_date.replace(hour=21, minute=0, second=0, microsecond=0)
        minutes = 0
        sessions = [
            (datetime.time(21, 0), datetime.time(23, 59), False),
            (datetime.time(0, 0), datetime.time(2, 30), True),
            (datetime.time(9, 0), datetime.time(10, 15), False),
            (datetime.time(10, 30), datetime.time(11, 30), False),
            (datetime.time(13, 30), datetime.time(15, 0), False),
        ]
        cur = start
        while cur < dt:
            in_session = False
            cur_time = cur.time()
            for s_start, s_end, cross in sessions:
                if not cross:
                    if s_start <= cur_time <= s_end:
                        in_session = True
                        break
                else:
                    if cur_time <= s_end or cur_time >= s_start:
                        in_session = True
                        break
            if in_session:
                minutes += 1
            cur += timedelta(minutes=1)
        return minutes

    # 遍历所有快照
    for dt, fpath in timed_files:
        df, err = safe_read_csv(fpath)
        if err or df is None or df.empty:
            continue

        long_df = df[df["pos_type"] == "LONG"]
        short_df = df[df["pos_type"] == "SHORT"]

        inst_net = {}
        inst_profit = {}
        inst_price = {}
        inst_mult = {}
        for inst in set(long_df["instrument_id"]).union(set(short_df["instrument_id"])):
            long_rows = long_df[long_df["instrument_id"] == inst]
            short_rows = short_df[short_df["instrument_id"] == inst]
            long_pos = long_rows["position"].sum() if not long_rows.empty else 0
            short_pos = short_rows["position"].sum() if not short_rows.empty else 0
            net = long_pos - short_pos
            close_profit = long_rows["close_profit"].sum() + short_rows["close_profit"].sum() if not (long_rows.empty and short_rows.empty) else 0
            position_profit = long_rows["position_profit"].sum() + short_rows["position_profit"].sum() if not (long_rows.empty and short_rows.empty) else 0
            total_pnl = close_profit + position_profit
            # 若净持仓和盈亏均为0，跳过该合约（避免大量零值点）
            if net == 0 and total_pnl == 0:
                continue
            price = get_price(inst)
            if price is None:
                if not long_rows.empty:
                    price = float(long_rows["pre_settlement_price"].iloc[0])
                elif not short_rows.empty:
                    price = float(short_rows["pre_settlement_price"].iloc[0])
                else:
                    price = 0.0
            mult = mult_map.get(inst, 1.0)
            inst_net[inst] = net
            inst_profit[inst] = total_pnl
            inst_price[inst] = price
            inst_mult[inst] = mult

        if not inst_net:
            continue

        # 计算时间索引
        base = datetime.datetime.combine(
            (datetime.datetime.strptime(str(current_date), "%Y%m%d") - timedelta(days=1)).date(),
            datetime.time(21, 0)
        )
        time_idx = get_trade_minute_index(dt, base)
        time_label = dt.strftime("%H:%M")

        for inst, net in inst_net.items():
            if inst not in data_dict:
                data_dict[inst] = []
            data_dict[inst].append({
                "time_idx": time_idx,
                "time_label": time_label,
                "net_pos": net,
                "market_value": abs(net * inst_price.get(inst, 0) * inst_mult.get(inst, 1.0)),
                "cum_pnl": inst_profit.get(inst, 0),
                "open_net": 0,
                "price": inst_price.get(inst, 0),
            })

    # 填充 open_net（第一个快照的净持仓）
    for inst, records in data_dict.items():
        if records:
            first_record = records[0]
            open_net = first_record["net_pos"]
            for rec in records:
                rec["open_net"] = open_net

    # 转为 DataFrame
    result = {}
    for inst, records in data_dict.items():
        df_inst = pd.DataFrame(records)
        if not df_inst.empty:
            df_inst = df_inst.sort_values("time_idx")
            result[inst] = df_inst

    return result if result else None

def draw_intraday_charts(
    product_configs: list,
    current_date: int,
    static_df: pd.DataFrame | None,
    product_checks: dict,
    show_all: bool,
    contract_filter: str,
    init_capital_map: dict,
):
    """
    绘制三个日内图表，init_capital_map 用于将产品PnL转为百分比
    """
    all_product_data = {}
    for cfg in product_configs:
        key = f"{cfg['market']}_{cfg['product']}"
        if not product_checks.get(key, True):
            continue
        init_cap = init_capital_map.get(key, 1.0)
        data = build_intraday_series(cfg, current_date, static_df, init_cap)
        if data:
            all_product_data[key] = (data, init_cap)

    if not all_product_data:
        st.error("⚠️ 没有可用的日内数据，请检查快照文件是否包含非零持仓。")
        return

    # 收集所有时间索引用于刻度
    all_time_idxs = []
    for _, (instrument_data, _) in all_product_data.items():
        for inst, df in instrument_data.items():
            all_time_idxs.extend(df["time_idx"].tolist())
    if all_time_idxs:
        min_idx = min(all_time_idxs)
        max_idx = max(all_time_idxs)
        tick_vals = list(range(min_idx, max_idx+1, 30))
        label_map = {}
        for _, (instrument_data, _) in all_product_data.items():
            for inst, df in instrument_data.items():
                for _, row in df.iterrows():
                    idx = int(row["time_idx"])
                    label = row["time_label"]
                    if idx not in label_map:
                        label_map[idx] = label
        ticktext = [label_map.get(v, "") for v in tick_vals if v in label_map]
        tickvals = [v for v in tick_vals if v in label_map]
        if not ticktext:
            tickvals = sorted(all_time_idxs)[::30]
            ticktext = [label_map.get(v, "") for v in tickvals]
    else:
        tickvals = None
        ticktext = None

    # ---- 图1: 产品 PnL（百分比） ----
    fig1 = go.Figure()
    for product_key, (instrument_data, init_cap) in all_product_data.items():
        all_dfs = []
        for inst, df in instrument_data.items():
            df_temp = df[["time_idx", "time_label", "cum_pnl"]].copy()
            df_temp["time_idx"] = df_temp["time_idx"].astype(int)
            all_dfs.append(df_temp)
        if not all_dfs:
            continue
        combined = pd.concat(all_dfs)
        grouped = combined.groupby("time_idx").agg(
            cum_pnl=("cum_pnl", "sum"),
            time_label=("time_label", "first")
        ).reset_index()
        grouped["pnl_pct"] = (grouped["cum_pnl"] / init_cap) * 100
        grouped = grouped.sort_values("time_idx")
        fig1.add_trace(go.Scatter(
            x=grouped["time_idx"],
            y=grouped["pnl_pct"],
            mode="lines+markers",
            name=product_key,
            marker=dict(size=4),
        ))

    xaxis_dict = dict(title="Time")
    if tickvals and ticktext:
        xaxis_dict.update(tickvals=tickvals, ticktext=ticktext)
    fig1.update_layout(
        title="Product PnL (%) Over Time (Intraday)",
        xaxis=xaxis_dict,
        yaxis=dict(title="PnL (%)", autorange=True, rangemode="tozero"),
        legend_title="Products",
        hovermode="x unified",
    )

    # ---- 图2: 合约盈亏比例 ----
    all_contract_data = []
    for product_key, (instrument_data, _) in all_product_data.items():
        for inst, df in instrument_data.items():
            df_temp = df[["time_idx", "time_label", "cum_pnl", "market_value"]].copy()
            df_temp["instrument"] = inst
            df_temp["product"] = product_key
            all_contract_data.append(df_temp)

    fig2 = go.Figure()
    if all_contract_data:
        combined2 = pd.concat(all_contract_data)
        if not show_all and contract_filter.strip():
            contract_list = [c.strip() for c in contract_filter.split() if c.strip()]
            if contract_list:
                combined2 = combined2[combined2["instrument"].isin(contract_list)]
        combined2["pnl_ratio"] = combined2.apply(
            lambda row: row["cum_pnl"] / row["market_value"] if row["market_value"] != 0 else 0,
            axis=1
        )
        for inst, group in combined2.groupby("instrument"):
            group = group.sort_values("time_idx")
            fig2.add_trace(go.Scatter(
                x=group["time_idx"],
                y=group["pnl_ratio"],
                mode="lines",
                name=inst,
                line=dict(width=1),
                hovertemplate="%{text}<extra></extra>",
                text=group["time_label"],
            ))
    xaxis_dict2 = dict(title="Time")
    if tickvals and ticktext:
        xaxis_dict2.update(tickvals=tickvals, ticktext=ticktext)
    fig2.update_layout(
        title="Contract PnL / Market Value",
        xaxis=xaxis_dict2,
        yaxis=dict(title="PnL Ratio", autorange=True),
        legend_title="Contracts",
        hovermode="x unified",
    )

    # ---- 图3: 手数比例 ----
    all_contract_data2 = []
    for product_key, (instrument_data, _) in all_product_data.items():
        for inst, df in instrument_data.items():
            if "open_net" not in df.columns:
                continue
            df_temp = df[["time_idx", "time_label", "net_pos", "open_net"]].copy()
            df_temp["instrument"] = inst
            df_temp["product"] = product_key
            all_contract_data2.append(df_temp)
    fig3 = go.Figure()
    if all_contract_data2:
        combined3 = pd.concat(all_contract_data2)
        if not show_all and contract_filter.strip():
            contract_list = [c.strip() for c in contract_filter.split() if c.strip()]
            if contract_list:
                combined3 = combined3[combined3["instrument"].isin(contract_list)]
        combined3["pos_ratio"] = combined3.apply(
            lambda row: (row["net_pos"] - row["open_net"]) / row["open_net"] if row["open_net"] != 0 else 0,
            axis=1
        )
        for inst, group in combined3.groupby("instrument"):
            group = group.sort_values("time_idx")
            fig3.add_trace(go.Scatter(
                x=group["time_idx"],
                y=group["pos_ratio"],
                mode="lines",
                name=inst,
                line=dict(width=1),
                hovertemplate="%{text}<extra></extra>",
                text=group["time_label"],
            ))
    xaxis_dict3 = dict(title="Time")
    if tickvals and ticktext:
        xaxis_dict3.update(tickvals=tickvals, ticktext=ticktext)
    fig3.update_layout(
        title="Position Change Ratio (Current - Open) / Open",
        xaxis=xaxis_dict3,
        yaxis=dict(title="Position Ratio", autorange=True),
        legend_title="Contracts",
        hovermode="x unified",
    )

    st.plotly_chart(fig1, width="stretch")
    st.plotly_chart(fig2, width="stretch")
    st.plotly_chart(fig3, width="stretch")


# ─────────────────────────────────────────────
# DASHBOARD MAIN（修改：增加 init_capital_map）
# ─────────────────────────────────────────────

ALERT_FILE = "alert_status_test.json"

def load_alert_status():
    if os.path.exists(ALERT_FILE):
        with open(ALERT_FILE, "r") as f:
            return json.load(f)
    return {"product_low_limit": {}, "max_margin": {}, "margin_ratio": {}}

def save_alert_status(status):
    with open(ALERT_FILE, "w") as f:
        json.dump(status, f)

def dashboard():
    st.set_page_config(page_title="Futures Monitor Dashboard", layout="wide")

    # ── 侧边栏控件 ──
    with st.sidebar:
        st.header("Chart Controls")
        st.subheader("Product PnL Display")
        product_checks = {}
        for cfg in PRODUCT_CONFIGS:
            label = f"{cfg['market']}_{cfg['product']}"
            product_checks[label] = st.checkbox(label, value=True)
        st.subheader("Contract Selection")
        show_all = st.checkbox("Show All Contracts", value=True)
        contract_input = st.text_input("Filter contracts (space separated)", "")

    placeholder = st.empty()

    try:
        current_date, _ = get_date_from_calendar()
        # ── 加载通用静态信息 ──
        static_paths = []
        for market in ["commodity", "futures"]:
            paths = get_static_info_path(market)
            if isinstance(paths, list):
                static_paths.extend(paths)
            else:
                static_paths.append(paths)
        static_df, _ = safe_read_csv(static_paths)

        init_price_cache("commodity", current_date)
        init_price_cache("futures",   current_date)
    except Exception as e:
        st.warning(f"Price cache init failed: {e}")

    placeholder = st.empty()

    try:
        current_date, _ = get_date_from_calendar()
        now = datetime.datetime.now()

        summary_rows: list[dict]           = []
        detail_map:   dict[str, tuple]     = {}
        detail_status_map: dict[str, dict] = {}
        global_file_errors: list[str]      = []
        shared_cache: dict[str, tuple]     = {}

        # 新增：用于收集各产品 init_capital 的字典
        init_capital_map = {}

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

            # 保存 init_capital
            key = f"{ft}_{name}"
            init_capital_map[key] = row.get("init_capital", 0.0)

            summary_rows.append(row)
            if detail_df is not None:
                detail_map[cfg["path"]]        = (cfg, detail_df)
                detail_status_map[cfg["path"]] = detail_status

            # ── 告警逻辑（不变） ──
            ALERT_STATUS = load_alert_status()
            if market_open:
                try:
                    pll = safe_float(row["product_low_limit"])
                    imu = safe_float(row["max_margin"])
                    mrt = safe_float(row["margin_ratio"])
                    alert_key = f"{ft}_{row['broker']}_{name}_market_value"
                    if name not in {"ly1h"}:
                        if pll < 0.8:
                            if not ALERT_STATUS["product_low_limit"].get(alert_key, False):
                                send_alert(f"[ALERT] product_low_limit < 0.8 | broker={row['broker']} product={name}")
                                ALERT_STATUS["product_low_limit"][alert_key] = True
                                save_alert_status(ALERT_STATUS)
                        else:
                            if ALERT_STATUS["product_low_limit"].get(alert_key, False):
                                ALERT_STATUS["product_low_limit"][alert_key] = False
                                save_alert_status(ALERT_STATUS)

                    alert_key = f"{ft}_{row['broker']}_{name}_max_margin"
                    if imu > 0.25:
                        if not ALERT_STATUS["max_margin"].get(alert_key, False):
                            send_alert(f"[ALERT] max_margin > 0.25 | broker={row['broker']} product={name}")
                            ALERT_STATUS["max_margin"][alert_key] = True
                            save_alert_status(ALERT_STATUS)
                    else:
                        if ALERT_STATUS["max_margin"].get(alert_key, False):
                            ALERT_STATUS["max_margin"][alert_key] = False
                            save_alert_status(ALERT_STATUS)

                    alert_key = f"{ft}_{row['broker']}_{name}_margin_ratio"
                    if mrt > 0.75:
                        if not ALERT_STATUS["margin_ratio"].get(alert_key, False):
                            send_alert(f"[ALERT] margin_ratio > 0.75 | broker={row['broker']} product={name}")
                            ALERT_STATUS["margin_ratio"][alert_key] = True
                            save_alert_status(ALERT_STATUS)
                    else:
                        if ALERT_STATUS["margin_ratio"].get(alert_key, False):
                            ALERT_STATUS["margin_ratio"][alert_key] = False
                            save_alert_status(ALERT_STATUS)
                except (ValueError, TypeError) as e:
                    print("异常打印:", e)
                    pass

        # ── 构建展示表格 ──
        df = pd.DataFrame(summary_rows, columns=SUMMARY_COLS)
        money_cols = ["balance", "pre_balance", "bank","market_value",
                      "deposit_withdraw", "cost", "net_return", "init_capital", "margin"]
        for col in money_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).round(0).astype(int).apply(lambda x: f"{x:,}")
        df["max_margin"] = pd.to_numeric(df["max_margin"], errors="coerce").fillna(0).apply(lambda x: f"{100*x:.2f}%")
        df["product_low_limit"] = pd.to_numeric(df["product_low_limit"], errors="coerce").fillna(0).apply(lambda x: f"{x:.4f}")
        trade_mv_cols = ["BuyOpenMarketValue", "BuyCloseMarketValue", "SellOpenMarketValue", "SellCloseMarketValue"]
        for col in trade_mv_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).round(0).astype(int).apply(lambda x: f"{x:,}")
        trade_ratio_cols = ["BOMVRatio", "BCMVRatio", "SOMVRatio", "SCMVRatio"]
        for col in trade_ratio_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).apply(lambda x: f"{x * 100:.3f}%")
        display_df = df.drop(columns=["is_market_open"])
        styled_df = display_df.style.apply(style_product_low_limit, axis=1).map(style_max_margin, subset=["max_margin"]).map(style_margin_ratio, subset=["margin_ratio"])

        with placeholder.container():
            st.markdown("""<div style="text-align:center; font-weight:bold; font-size:28px; margin-bottom:12px;">Futures Monitor Dashboard</div>""", unsafe_allow_html=True)
            st.markdown("---")
            st.subheader("Trading Summary")
            summary_table = build_summary_table(df)
            st.dataframe(summary_table, width="stretch")
            if global_file_errors:
                st.error("**Missing / unreadable files:**\n\n" + "\n\n".join(f"- {e}" for e in global_file_errors))
            st.markdown("---")
            st.subheader("Overview")
            display_overview_with_tooltips(styled_df)

            # 显示 product_low_limit 错误汇总
            _low_limit_errors = []
            for _r in summary_rows:
                try:
                    _pll = float(_r["product_low_limit"])
                    if _pll < 0.8:
                        _is_ly1h = _r.get("product") == "ly1h"
                        _low_limit_errors.append({
                            "product":          _r.get("product", ""),
                            "market":           _r.get("market", ""),
                            "broker":           _r.get("broker", ""),
                            "product_low_limit": f"{_pll:.4f}",
                            "warnings":         _r.get("warnings", ""),
                            "reason":           "流动性不足-ly1h" if _is_ly1h else "流动性不足",
                        })
                except (ValueError, TypeError):
                    pass
            if _low_limit_errors:
                _err_df = pd.DataFrame(_low_limit_errors)
                with st.expander(f"Product Low Limit Errors ({len(_low_limit_errors)})", expanded=False):
                    st.markdown("##### Product Low Limit Errors (流动性不足)")
                    st.dataframe(_err_df, width="stretch", hide_index=True)
                    st.caption("product_low_limit < 0.8（ly1h 例外，仅标记为黄色, 老产品暂时还没有市值要求）")

            # ── Per-Instrument Detail ──
            st.markdown("---")
            st.subheader("Per-Instrument Detail")
            for prod_path, (cfg, ddf) in detail_map.items():
                market_label  = "CNCF" if cfg["market"] == "commodity" else "CNIF"
                product_label = cfg["product"]
                broker_label  = cfg["broker"]
                status      = detail_status_map.get(prod_path, {"has_warning": False, "has_risk": False})
                has_risk    = status.get("has_risk",    False)
                has_warning = status.get("has_warning", False)
                title_color = "🔴" if has_risk else ("🟡" if has_warning else "")
                title = f"{title_color} [{market_label}] {product_label} | {broker_label}"
                if ddf is not None and ddf.empty:
                    title += " (清仓)"
                with st.expander(title, expanded=False):
                    display_cols = [
                        "instrument", "market_value",
                        "position", "yd_position", "today_position", "risk_position", "clip", "uplimit",
                        "close_profit", "position_profit", "total_pnl",
                        "instrument_margin", "exchange", "last_trade_time",
                        "BuyOpenNumber", "BuyOpenMarketValue",
                        "BuyCloseNumber", "BuyCloseMarketValue",
                        "SellOpenNumber", "SellOpenMarketValue",
                        "SellCloseNumber", "SellCloseMarketValue",
                    ]
                    display_ddf = ddf[[c for c in display_cols if c in ddf.columns]].copy()
                    int_cols = [
                        "market_value", "risk_position",
                        "yd_position", "today_position",
                        "close_profit", "position_profit", "total_pnl",
                        "instrument_margin",
                        "BuyOpenNumber", "BuyOpenMarketValue",
                        "BuyCloseNumber", "BuyCloseMarketValue",
                        "SellOpenNumber", "SellOpenMarketValue",
                        "SellCloseNumber", "SellCloseMarketValue",
                    ]
                    for col in int_cols:
                        if col in display_ddf.columns:
                            display_ddf[col] = pd.to_numeric(display_ddf[col], errors="coerce").fillna(0).astype(int)
                    if "uplimit" in display_ddf.columns:
                        display_ddf["uplimit"] = display_ddf["uplimit"].apply(lambda x: f"{float(x):.2f}" if pd.notna(x) and x is not None else None)
                    col_mapping = {
                        "instrument":          "合约名称",
                        "market_value":        "合约市值",
                        "position":            "持仓数量",
                        "yd_position":         "昨仓",
                        "today_position":      "今仓",
                        "risk_position":       "目标仓位",
                        "clip":                "Clip",
                        "uplimit":             "Uplimit",
                        "close_profit":        "平仓盈亏",
                        "position_profit":     "持仓盈亏",
                        "total_pnl":           "当日盈亏",
                        "instrument_margin":   "保证金",
                        "exchange":            "交易所",
                        "last_trade_time":     "最后成交时间",
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

                    def style_risk_match_row(row_idx):
                        styles = [""] * len(display_ddf.columns)
                        if row_idx < len(ddf) and "risk_match" in ddf.columns:
                            risk_match = ddf.iloc[row_idx].get("risk_match", "matched")
                            if risk_match == "red":
                                styles = ["background-color: #ff4b4b; color: white; font-weight: bold;"] * len(display_ddf.columns)
                        return styles
                    styled_detail = display_ddf.style
                    for row_idx in range(len(display_ddf)):
                        row_styles = style_risk_match_row(row_idx)
                        if any(row_styles):
                            for col_idx, (col_name, style) in enumerate(zip(display_ddf.columns, row_styles)):
                                if style:
                                    styled_detail = styled_detail.map(lambda x, s=style: s, subset=pd.IndexSlice[[row_idx], col_name])
                    st.dataframe(styled_detail, width="stretch")
                    if "risk_match" in ddf.columns and "instrument" in ddf.columns:
                        risk_red_rows = ddf[ddf["risk_match"] == "red"]
                        if not risk_red_rows.empty:
                            st.error("🔴 **Instrument Risk Errors (Position Mismatch):**")
                            for _, rr in risk_red_rows.iterrows():
                                inst_name  = rr["instrument"]
                                pos_type   = rr.get("position_type", "")
                                actual_pos = rr.get("position", 0)
                                risk_pos   = rr.get("risk_position", None)
                                if risk_pos is None:
                                    risk_pos = 0
                                elif math.isnan(risk_pos):
                                    risk_pos = 0
                                risk_pos_display = int(round(risk_pos)) if (risk_pos is not None) else 0
                                st.markdown(f"- **{inst_name}** ({pos_type}): 实际持仓 = `{actual_pos}`, 目标仓位 = `{risk_pos_display}` → 净仓位与目标仓位不一致")
                    if "_warnings" in ddf.columns:
                        inst_warns = ddf[ddf["_warnings"].str.len() > 0]
                        if not inst_warns.empty:
                            st.warning("**Instrument Warnings:**")
                            for idx, wr in inst_warns.iterrows():
                                st.markdown(f"- **{wr['instrument']}**: {wr['_warnings']}")

            # ── 新增：日内图表 ──
            st.markdown("---")
            st.subheader("Intraday Charts")
            draw_intraday_charts(
                PRODUCT_CONFIGS,
                current_date,
                static_df,
                product_checks,
                show_all,
                contract_input,
                init_capital_map,   # 传入收集的资金字典
            )

    except Exception as outer_err:
        with placeholder.container():
            st.error(f"Dashboard loop error: {outer_err}")
            import traceback
            st.error(traceback.format_exc())

    time.sleep(300)
    st.rerun()

if __name__ == "__main__":
    dashboard()