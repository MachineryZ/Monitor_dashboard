import os
import time
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
    """获取 ClickHouse 连接"""
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
            # print(f"ClickHouse connection failed: {e}")
            return None
    return _ch_client


def get_product_clip(product_name: str) -> int | None:
    """
    根据 product_name 查询 clip
    :param product_name: 产品名，如 'melt'
    :return: clip 数值（int），如果不存在返回 None
    """
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
            clip = int(result.iloc[0]["clip"])
            return clip
        else:
            return None

    except Exception as e:
        # print(f"get_product_clip Query failed: {e}")
        return None


def get_product_uplimit_coef(product_name: str) -> float | None:
    """
    根据 product_name 查询 coef（uplimit系数）
    :param product_name: 产品名，如 'melt'
    :return: coef 数值（double），如果不存在返回 None
    """
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
            coef = float(result.iloc[0]["coef"])
            return coef
        else:
            return None

    except Exception as e:
        # print(f"get_product_uplimit_coef Query failed: {e}")
        return None


# ─────────────────────────────────────────────
# 修复：从CSV读取 uplimit_holding_position
# ─────────────────────────────────────────────

def load_uplimit_holding_position() -> dict[str, float] | None:
    """
    从CSV文件读取 uplimit_holding_position
    文件路径: /cpfs/rawdata/cncf_all_nedd_before_open/margin_uplimit_include_ine.csv
    
    :return: {instrument: uplimit_holding_position} 的字典
    """
    # ⭐ 修复：统一使用这个路径
    csv_path = "/cpfs/rawdata/cncf_all_nedd_before_open/margin_uplimit_include_ine.csv"
    
    uplimit_data = {}
    
    try:
        df, err = safe_read_csv(csv_path)
        
        if err or df is None or df.empty:
            # print(f"❌ load_uplimit_holding_position: {err}")
            return None
        
        # print(f"✅ load_uplimit_holding_position: CSV loaded, shape={df.shape}, columns={list(df.columns)}")
        
        # 必须有 instrument 和 uplimit_holding_position 两列
        if "instrument" not in df.columns or "up_limit_holding_position" not in df.columns:
            # print(f"❌ Missing required columns. Available: {list(df.columns)}")
            return None
        
        # 逐行读取 - ⭐ 修复：不过滤 uplimit_hp，包括 0 值
        loaded_count = 0
        for idx, row in df.iterrows():
            try:
                inst = str(row["instrument"]).strip()
                uplimit_hp_raw = row.get("up_limit_holding_position", 0)
                
                # 允许 0 值和非零值
                if inst:
                    try:
                        uplimit_hp = float(uplimit_hp_raw)
                        uplimit_data[inst] = uplimit_hp
                        loaded_count += 1
                    except (ValueError, TypeError):
                        # print(f"⚠️ Skip row {idx}: uplimit_hp={uplimit_hp_raw} (not a valid number)")
                        continue
            except Exception as e:
                # print(f"⚠️ Parse error for row {idx}: {e}")
                continue
        
        # print(f"✅ Loaded {loaded_count} instruments from uplimit CSV")
        return uplimit_data if uplimit_data else None
    
    except Exception as e:
        # print(f"❌ load_uplimit_holding_position exception: {e}")
        import traceback
        traceback.print_exc()
        return None


def calculate_uplimit(instrument: str, product_name: str, 
                     uplimit_data: dict[str, float] | None) -> float | None:
    """
    计算某个合约的 uplimit
    
    :param instrument: 合约代码
    :param product_name: 产品名称（用于从数据库查询 coef）
    :param uplimit_data: {instrument: uplimit_holding_position} 的字典
    :return: uplimit 值，或 None 如果计算失败
    """
    
    # 1. 查询 coef
    coef = get_product_uplimit_coef(product_name)
    if coef is None:
        # print(f"⚠️ calculate_uplimit: coef is None for product {product_name}")
        return None
    
    # 2. 从 uplimit_data 获取 uplimit_holding_position
    if uplimit_data is None:
        # print(f"⚠️ calculate_uplimit: uplimit_data is None")
        return None
    
    if instrument not in uplimit_data:
        # ⭐ 修复：添加日志，便于调试
        # print(f"⚠️ calculate_uplimit: instrument '{instrument}' not in uplimit_data. Available: {list(uplimit_data.keys())[:5]}...")
        return None
    
    uplimit_hp = uplimit_data[instrument]
    
    # 3. 计算 uplimit
    try:
        uplimit = uplimit_hp * coef
        # print(f"✅ uplimit for {instrument}: {uplimit_hp} × {coef} = {uplimit}")
        return uplimit
    except Exception as e:
        # print(f"❌ calculate_uplimit error for {instrument}: {e}")
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
    """返回 (今日 YYYYMMDD int, 下一交易日 YYYYMMDD int)"""
    date     = datetime.datetime.now().date()
    date_int = int(date.strftime("%Y%m%d"))
    date_list = np.loadtxt(CALENDAR_PATH, dtype=np.int64, ndmin=1)
    pos = np.searchsorted(date_list, date_int, side="right")
    next_trade_day = int(date_list[pos])
    return date_int, next_trade_day


def _time_in_session(t: datetime.time, start: datetime.time,
                     end: datetime.time, crosses_midnight: bool) -> bool:
    """判断时刻 t 是否在 [start, end] 时段内（支持跨午夜）"""
    if crosses_midnight:
        return t >= start or t <= end
    else:
        return start <= t <= end


def is_commodity_night_session_pre_midnight(t: datetime.time) -> bool:
    """判断当前时刻是否处于商品夜盘且在午夜之前（21:00–23:59:59）"""
    return t >= datetime.time(21, 0)


def is_market_open(market: str) -> bool:
    """判断当前时刻，指定品种是否正在交易"""
    t = datetime.datetime.now().time()
    sessions = COMMODITY_SESSIONS if market == "commodity" else FUTURES_SESSIONS
    return any(
        _time_in_session(t, s, e, cross)
        for s, e, cross in sessions
    )


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
    """返回 current_date 之后的下一个交易日"""
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
    """检查 path 目录下当天的 account_info 文件是否存在且非空"""
    fp = os.path.join(path, f"account_info_{date_int}.csv")
    return os.path.exists(fp) and os.path.getsize(fp) > 0


def _extract_latest_update_time(*dfs: pd.DataFrame | None) -> str:
    """从若干 DataFrame 中提取 update_time 列的最大值"""
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
# 核心：get_data_date
# ─────────────────────────────────────────────

def get_data_date(
    market: str,
    path: str,
    current_date: int,
    market_open: bool,
) -> tuple[int, str]:
    """
    返回 (data_date, label_suffix)
    """
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
# RISK POSITION LOADER (修改版)
# ─────────────────────────────────────────────

def load_risk_position(market: str, product: str, data_date: int) -> dict[str, float] | None:
    """
    读取 risk_position（目标仓位）
    
    Args:
        market: "commodity" 或 "futures"
        product: 产品名称
        data_date: YYYYMMDD 格式
    
    Returns:
        {instrument: risk_position_value} 字典，或 None
    """
    result = {}
    
    if market == "commodity":
        # ⭐ COMMODITY 的 strategy_mapping
        strategy_mapping = {
            "bgt_ax1h": "cncf_melt_bgt_dz_bohr",
            "shjq": "cncf_melt_shjq_zx_bohr",
            "shph1h": "cncf_melt_shph1h_zx_bohr",
            "zz1h": "cncf_melt_zhizeng_dz_bohr",
        }
        
        if product not in strategy_mapping:
            # print(f"⚠️ load_risk_position: No strategy mapping for product '{product}'")
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
                
                # 解析 "[0.123]" → 0.123
                all_stats_str = all_stats_str.strip("[]").strip()
                if all_stats_str:
                    value = float(all_stats_str)
                    if inst:
                        result[inst] = value
            except (ValueError, TypeError, AttributeError):
                continue
    
    elif market == "futures":
        # ⭐ FUTURES 的 strategy_mapping
        strategy_mapping = {
            "jz1h": "cnif_short_jz1h_dz_dashboard_bohr",
            "ly1h": "cnif_position_melt_ly1h_dz_dashboard_bohr",
            "zz1h": "cnif_short_zz1h_dz_dashboard_bohr",
        }
        
        if product not in strategy_mapping:
            # print(f"⚠️ load_risk_position: No strategy mapping for product '{product}'")
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
# STYLERS
# ─────────────────────────────────────────────

def style_product_low_limit(row: pd.Series) -> list[str]:
    """按行判断 product_low_limit 的颜色"""
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
# CORE: calculate_product (改进版)
# ─────────────────────────────────────────────

SUMMARY_COLS = [
    "market", "product", "broker",
    "init_capital",
    "balance", "pre_balance", "market_value",
    "cost", "net_return", "fee", "pnl",
    "max_margin", "product_low_limit",
    "margin", "margin_ratio",
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
    "deposit_withdraw": 0,
    "time": "",
    "warnings": "",
    "is_market_open": False,
}




def _get_last_trade_time_adjusted(
    trade_df: pd.DataFrame | None,
    inst: str,
    data_date: int,
    current_date: int,
    market: str,
) -> str:
    """
    获取最后成交时间，应用夜盘日期调整逻辑（需求2）
    规则：
    - 夜盘（>= 21:00） → 使用前一个交易日 + 交易时间
    - 否则 → data_date + 交易时间
    - 如果时间为空 → 使用前一交易日 + 20:00:00
    """
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
        "update_time" if "update_time" in t_rows.columns else
        None
    )
    
    if time_col is None:
        return ""

    try:
        trade_time_raw = t_rows[time_col].iloc[-1]
        trade_time_str = str(trade_time_raw).strip()
        
        if not trade_time_str or trade_time_str.lower() == "nan":
            # 数据为空 → 使用前一交易日 + 20:00:00
            prev_date = get_previous_trade_date(data_date)
            return f"{prev_date} 20:00:00"
        
        # 提取时间部分 (最后8位或冒号分隔的部分)
        if ':' in trade_time_str:
            # 格式: "HH:MM:SS" 或 "YYYY-MM-DD HH:MM:SS"
            time_part = trade_time_str.split()[-1]  # 取最后一个空格后的部分
        else:
            # 格式: "HHMMSS" 或 "YYYYMMDDhhmmss"
            time_part = trade_time_str[-6:] if len(trade_time_str) >= 6 else trade_time_str
            time_part = f"{time_part[0:2]}:{time_part[2:4]}:{time_part[4:6]}"
        
        hour = int(time_part[:2])
        
        # 夜盘判断：21:00 之后
        if hour >= 21:
            # 使用前一个交易日 + 交易时间
            prev_date = get_previous_trade_date(data_date)
            return f"{prev_date} {time_part}"
        else:
            # 普通时段：data_date + 交易时间
            return f"{data_date} {time_part}"
    
    except (ValueError, IndexError, AttributeError):
        pass
    
    return str(trade_time_str)


def _check_risk_position_match(
    actual_pos: float,
    risk_pos: float | None,
) -> str:
    """
    检查实际仓位和目标仓位是否匹配（基于净仓位）
    
    规则:
    - 实际有仓位，目标没有 → yellow (警告)
    - 实际没有仓位，目标有 → yellow (警告)
    - 两者都有，但数值不相等 → red (错误)
    - 都为0 或 相等 → matched (正常)
    """
    # 转为整数比较（因为持仓数量必须是整数）
    actual_int = int(round(actual_pos)) if actual_pos is not None else 0
    
    if risk_pos is None:
        risk_int = 0
    else:
        risk_int = int(round(risk_pos))
    
    # 规则1：实际有持仓，但目标仓位为0或无
    if actual_int != 0 and risk_int == 0:
        return "yellow"
    
    # 规则2：实际没有持仓，但目标仓位有值
    if actual_int == 0 and risk_int != 0:
        return "yellow"
    
    # 规则3：两者都有持仓，但数值不相等
    if actual_int != 0 and risk_int != 0 and actual_int != risk_int:
        return "red"
    
    # 其他情况（都为0，或两者相等）
    return "matched"


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
    """
    返回 (summary_dict, detail_df, detail_status_dict)
    """
    
    warnings_list: list[str] = []
    data = dict(DEFAULT_SUMMARY)
    data["market"]   = "cncf" if market == "commodity" else "cnif"
    data["product"]  = product
    data["broker"]   = broker
    data["time"]     = datetime.datetime.now().strftime("%H:%M:%S")
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

    data["margin_ratio"] = f"{100*margin_ratio:.2f}%"
    data["balance"]          = balance
    data["pre_balance"]      = pre_balance
    data["deposit_withdraw"] = deposit - withdraw
    data["cost"]             = fee
    data["margin"]           = margin
    init_capital = resolve_init_capital(cfg, pre_balance, balance)
    data["init_capital"] = init_capital

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

    # ── 3. 计算 net_return 和 fee ─────────────────────────────
    data["net_return"] = abs_return - fee
    if init_capital > 0:
        fee_pct = (fee / init_capital) * 100
        data["fee"] = f"{fee_pct:.3f}%"
    else:
        data["fee"] = "0.000%"

    # ── 4. PnL ───────────────────────────────────────────────
    if init_capital > 0:
        pnl = round((data["net_return"]) / init_capital * 100, 3)
    else:
        pnl = 0.0
    data["pnl"] = f"{pnl:.3f}%"

    sd_df     = shared_sd_df
    future_df = shared_future_df
    margin_df = shared_margin_df

    # ── 5. 加载 risk_position、clip 和 uplimit 数据 ────────────
    risk_position_map = load_risk_position(market, product, data_date)
    
    # 查询 clip
    db_product = cfg.get("db_product")
    clip = get_product_clip(db_product) if db_product else None
    
    # ⭐ 新逻辑：加载 uplimit_holding_position（仅对商品期货）
    uplimit_holding_position_data = None
    if market == "commodity":
        uplimit_holding_position_data = load_uplimit_holding_position()

    # ── 6. Per-instrument calculations ───────────────────────
    market_value          = 0.0
    instrument_margin_max = 0.0
    detail_rows: list[dict] = []
    has_warning = False
    has_risk = False

    instruments = (
        pd_df["instrument_id"].dropna().unique().tolist()
        if not pd_df.empty else []
    )

    trade_path = get_trade_file_path(path, data_date)
    trade_df, trade_err = safe_read_csv(trade_path)
    if trade_err:
        warnings_list.append(trade_err)
        trade_df = None

    for inst in instruments:
        inst_warnings: list[str] = []

        try:
            long_rows  = pd_df.query(f"instrument_id == '{inst}' and pos_type == 'LONG'")
            short_rows = pd_df.query(f"instrument_id == '{inst}' and pos_type == 'SHORT'")
            long_pos   = int(long_rows["position"].iloc[0])  if not long_rows.empty  else 0.0
            short_pos  = int(short_rows["position"].iloc[0]) if not short_rows.empty else 0.0
        except Exception as e:
            inst_warnings.append(f"position parsing error: {e}")
            long_pos = short_pos = 0
            has_warning = True

        # 获取静态信息
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
        margin_ratio = 0.0
        try:
            if margin_df is not None and not margin_df.empty:
                m_row = margin_df[margin_df["instrument"] == inst]
                if not m_row.empty:
                    margin_ratio = float(m_row["margin_ratio"].iloc[0])
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

        # ⭐ 新逻辑：计算 uplimit = uplimit_holding_position × coef
        uplimit_value = None
        try:
            if market == "commodity" and db_product:
                uplimit_value = calculate_uplimit(inst, db_product, uplimit_holding_position_data)
        except Exception as e:
            inst_warnings.append(f"uplimit calculation error: {e}")
            has_warning = True

        net_pos = long_pos - short_pos
        try:
            risk_pos = risk_position_map.get(inst) if risk_position_map else None
        except Exception as e:
            inst_warnings.append(f"risk_position error: {e}")
            has_warning = True
            risk_pos = None
        
        # ⭐ 一次性检查，结果会被 LONG 行和 SHORT 行共用
        risk_match = _check_risk_position_match(net_pos, risk_pos)
        if risk_match == "red":
            has_risk = True
        elif risk_match == "yellow":
            has_warning = True

        # ── 长仓行 ─────────────────────────────────────────────
        if long_pos > 0 or (long_pos == 0 and short_pos == 0):
            try:
                cp_long = float(long_rows["close_profit"].iloc[0]) if not long_rows.empty else 0.0
                pp_long = float(long_rows["position_profit"].iloc[0]) if not long_rows.empty else 0.0
                total_pnl_long = cp_long + pp_long
                
                inst_margin_long = price * long_pos * multiplier * margin_ratio
                market_value += price * long_pos * multiplier
                instrument_margin_max = max(inst_margin_long, instrument_margin_max)
                
                detail_rows.append({
                    "instrument":        inst,
                    "position":          int(long_pos),
                    "risk_position":     risk_pos,
                    "clip":              clip,
                    "uplimit":           round(uplimit_value, 2) if uplimit_value is not None else None,
                    "position_type":     "LONG",
                    "close_profit":      round(cp_long, 2),
                    "position_profit":   round(pp_long, 2),
                    "total_pnl":         round(total_pnl_long, 2),
                    "instrument_margin": round(inst_margin_long, 2),
                    "exchange":          exchange,
                    "last_trade_time":   last_trade_time,
                    "risk_match":        risk_match,
                    "_warnings":         "; ".join(inst_warnings),
                })
            except Exception as e:
                inst_warnings.append(f"LONG row error: {e}")
                has_warning = True

        # ── 短仓行 ───────────────────────────────────────────
        if short_pos > 0:
            try:
                cp_short = float(short_rows["close_profit"].iloc[0]) if not short_rows.empty else 0.0
                pp_short = float(short_rows["position_profit"].iloc[0]) if not short_rows.empty else 0.0
                total_pnl_short = cp_short + pp_short
                
                inst_margin_short = price * short_pos * multiplier * margin_ratio
                market_value += price * short_pos * multiplier
                
                # 检查 risk_position 匹配（对于 SHORT，传负数）
                # risk_match = _check_risk_position_match(-short_pos, risk_pos)
                # if risk_match == "red":
                #     has_risk = True
                # elif risk_match == "yellow":
                #     has_warning = True
                
                detail_rows.append({
                    "instrument":        inst,
                    "position":          -int(short_pos),
                    "risk_position":     risk_pos,
                    "clip":              clip,
                    "uplimit":           None,
                    "position_type":     "SHORT",
                    "close_profit":      round(cp_short, 2),
                    "position_profit":   round(pp_short, 2),
                    "total_pnl":         round(total_pnl_short, 2),
                    "instrument_margin": 0.0,
                    "exchange":          exchange,
                    "last_trade_time":   last_trade_time,
                    "risk_match":        risk_match,
                    "_warnings":         "; ".join(inst_warnings),
                })
            except Exception as e:
                inst_warnings.append(f"SHORT row error: {e}")
                has_warning = True

    data["market_value"] = market_value
    data["product_low_limit"] = (
        market_value / balance if balance > 0 else 0.0
    )
    data["max_margin"] = (
        instrument_margin_max / balance if balance > 0 else 0.0
    )
    try:
        data["update_time"] = _extract_latest_update_time(ai_df, pd_df, sd_df)
    except Exception as e:
        warnings_list.append(f"update_time error: {e}")

    data["warnings"] = " | ".join(warnings_list)

    detail_df = pd.DataFrame(detail_rows) if detail_rows else None
    
    # 需求5：标题着色规则
    detail_status = {
        "has_warning": has_warning,
        "has_risk": has_risk,
    }
    
    return data, detail_df, detail_status



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
# OVERVIEW TOOLTIP (更新版)
# ─────────────────────────────────────────────

def display_overview_with_tooltips(styled_df):
    # 第一步：显示表格
    st.dataframe(styled_df, width="stretch")

    st.markdown("---")

    with st.expander("Overview 字段完整说明", expanded=False):
        
        # ⭐ 改为 DataFrame 展示，天然对齐
        field_data = {
            "字段名": [
                "market", "product", "broker", "init_capital",
                "balance", "pre_balance", "market_value",
                "cost", "ret", "net_return", "fee",
                "pnl", "max_margin", "product_low_limit",
                "margin", "margin_ratio", "update_time", "time",
                "deposit_withdraw", "warnings",
            ],
            "分类": [
                "市场", "市场", "市场", "资金",
                "资金", "资金", "持仓",
                "资金", "资金", "资金", "资金",
                "资金", "风险", "风险",
                "风险", "风险", "时间", "时间",
                "资金", "系统",
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
                "最后一次数据更新时刻，从数据文件中提取的时间戳",
                "当前仪表板查询时刻（系统时间）",
                "净入出金 = 入金 - 出金",
                "数据加载或计算过程中的警告信息",
            ],
        }

        desc_df = pd.DataFrame(field_data)
        st.dataframe(desc_df, width="stretch", hide_index=True)

        st.markdown("---")
        st.markdown("""
**风险阈值速查：**
- `max_margin` > **25%** → 单合约保证金过高 (红色告警)
- `product_low_limit` < **0.8** → 流动性不足 (红色告警，ly1h 为黄色)
        """)


# ─────────────────────────────────────────────
# BUILD SUMMARY TABLE (更新版)
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
        aum         = subset["init_capital"].sum()
        cost        = subset["cost"].sum()
        net_return  = subset["net_return"].sum()
        pnl_pct     = (net_return / aum * 100) if aum > 0 else 0.0
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

            summary_rows: list[dict]       = []
            detail_map:   dict[str, tuple] = {}
            detail_status_map: dict[str, dict] = {}
            global_file_errors: list[str]  = []
            shared_cache: dict[str, tuple] = {}

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
                        "market":   "cncf" if ft == "commodity" else "cnif",
                        "product":  name,
                        "broker":   cfg["broker"],
                        "init_capital": 0,
                        "time":     now.strftime("%H:%M:%S"),
                        "warnings": f"Calculation error: {calc_err}",
                        "is_market_open": market_open,
                    })
                    detail_df = None
                    detail_status = {"has_warning": True, "has_risk": False}

                summary_rows.append(row)
                if detail_df is not None:
                    detail_map[cfg["path"]] = (cfg, detail_df)
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

            df = pd.DataFrame(summary_rows, columns=SUMMARY_COLS)

            money_cols = [
                "balance", "pre_balance", "market_value",
                "deposit_withdraw", "cost", "net_return", "init_capital", "margin"
            ]


            for col in money_cols:
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
                .apply(style_product_low_limit,  axis=1)
                .map(style_max_margin, subset=["max_margin"])
            )

            with placeholder.container():
                st.markdown(
                    """
                    <div style="text-align:center; font-weight:bold; font-size:28px;
                                margin-bottom:12px;">
                        🚀 Futures Monitor Dashboard
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                st.markdown("---")
                st.subheader("📊 Trading Summary")
                summary_table = build_summary_table(df)
                st.dataframe(summary_table, width="stretch")

                if global_file_errors:
                    st.error(
                        "⚠️ **Missing / unreadable files:**\n\n"
                        + "\n\n".join(f"- {e}" for e in global_file_errors)
                    )

                st.markdown("---")
                st.subheader("📈 Overview")
                display_overview_with_tooltips(styled_df)

                st.markdown("---")
                st.subheader("🔍 Per-Instrument Detail")

                for prod_path, (cfg, ddf) in detail_map.items():
                    market_label = "CNCF" if cfg["market"] == "commodity" else "CNIF"
                    product_label = cfg["product"]
                    broker_label = cfg["broker"]
                    
                    # 需求5：根据状态着色标题
                    status = detail_status_map.get(prod_path, {"has_warning": False, "has_risk": False})
                    has_risk = status.get("has_risk", False)
                    has_warning = status.get("has_warning", False)
                    
                    if has_risk:
                        title_color = "🔴"
                    elif has_warning:
                        title_color = "🟡"
                    else:
                        title_color = ""
                    
                    title = f"{title_color} [{market_label}] {product_label} | {broker_label}"

                    with st.expander(title, expanded=False):
                        # ⭐ 修改列顺序：instrument, position, risk_position, clip, uplimit, 其他...
                        display_cols = [
                            "instrument", "position", "risk_position", "clip", "uplimit",
                            "close_profit", "position_profit", "total_pnl",
                            "instrument_margin", "exchange", "last_trade_time",
                        ]
                        display_ddf = ddf[
                            [c for c in display_cols if c in ddf.columns]
                        ].copy()

                        # ⭐ 新增：格式化为整数（仅保留整数，无小数点）
                        int_cols = ["risk_position", "close_profit", "position_profit", "total_pnl", "instrument_margin"]
                        for col in int_cols:
                            if col in display_ddf.columns:
                                display_ddf[col] = pd.to_numeric(display_ddf[col], errors="coerce").fillna(0).astype(int)

                        if "uplimit" in display_ddf.columns:
                            display_ddf["uplimit"] = display_ddf["uplimit"].apply(
                                lambda x: f"{float(x):.2f}" if pd.notna(x) and x is not None else None
                            )

                        # 重新标记列名
                        col_mapping = {
                            "instrument": "合约名称",
                            "position": "持仓数量",
                            "risk_position": "目标仓位",
                            "clip": "Clip",
                            "uplimit": "Uplimit",
                            "close_profit": "平仓盈亏",
                            "position_profit": "持仓盈亏",
                            "total_pnl": "当日盈亏",
                            "instrument_margin": "保证金",
                            "exchange": "交易所",
                            "last_trade_time": "最后成交时间",
                        }
                        display_ddf = display_ddf.rename(columns=col_mapping)

                        # ⭐ 需求2：红色整行着色（对 risk_match == "red" 的行）
                        def style_risk_match_row(row_idx):
                            """对 risk_match == "red" 的整行着色"""
                            styles = [""] * len(display_ddf.columns)
                            
                            if row_idx < len(ddf) and "risk_match" in ddf.columns:
                                risk_match = ddf.iloc[row_idx].get("risk_match", "matched")
                                
                                if risk_match == "red":
                                    # 整行红色着色
                                    styles = ["background-color: #ff4b4b; color: white; font-weight: bold;"] * len(display_ddf.columns)
                            
                            return styles

                        # 使用 Styler 应用行着色
                        styled_detail = display_ddf.style
                        for row_idx in range(len(display_ddf)):
                            row_styles = style_risk_match_row(row_idx)
                            if any(row_styles):
                                # 对这一行应用样式
                                for col_idx, (col_name, style) in enumerate(zip(display_ddf.columns, row_styles)):
                                    if style:
                                        styled_detail = styled_detail.applymap(
                                            lambda x, s=style: s,
                                            subset=pd.IndexSlice[[row_idx], col_name]
                                        )

                        st.dataframe(styled_detail, width="stretch")

                        # 显示警告信息
                        if "_warnings" in ddf.columns:
                            inst_warns = ddf[ddf["_warnings"].str.len() > 0]
                            if not inst_warns.empty:
                                st.warning("⚠️ **Instrument Warnings:**")
                                for idx, wr in inst_warns.iterrows():
                                    st.markdown(
                                        f"- **{wr['instrument']}**: {wr['_warnings']}"
                                    )

        except Exception as outer_err:
            with placeholder.container():
                st.error(f"❌ Dashboard loop error: {outer_err}")
                import traceback
                st.error(traceback.format_exc())

        time.sleep(10)


if __name__ == "__main__":
    dashboard()
