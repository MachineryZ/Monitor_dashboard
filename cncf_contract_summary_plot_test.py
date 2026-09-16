import os
import time
import datetime
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
from datetime import timedelta
import re

# ── 配置与常量 ──────────────────────────────────────
CALENDAR_PATH = "/cpfs/intrastats/calendar"
_price_cache: dict[str, float] = {}

DEFAULT_INIT_CAP = 100_000_000.0

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
    {
        "path":         "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_jx1h_zx",
        "broker":       "zx",
        "product":      "jx1h_zx",
        "market":       "futures",
        "init_capital": 0,
        "aum_mul":      4.7858,
        "db_product":   None,
    },
]

# ── 交易所映射 ──────────────────────────────────────
EXCHANGE_CN = {
    "SHFE":  "上期所",
    "DCE":   "大商所",
    "CZCE":  "郑商所",
    "CFFEX": "中金所",
    "INE":   "上期能源",
    "GFEX":  "广期所",
}

VARIETY_EXCHANGE: dict[str, str] = {}
for _v in ["cu", "al", "zn", "pb", "ni", "sn", "au", "ag", "rb", "hc",
           "ss", "bu", "ru", "sp", "fu", "wr", "ao", "br"]:
    VARIETY_EXCHANGE[_v] = "SHFE"
for _v in ["a", "b", "c", "cs", "i", "j", "jd", "jm", "l", "m", "p",
           "pp", "v", "y", "eg", "eb", "rr", "pg", "lh", "bb", "fb", "LG"]:
    VARIETY_EXCHANGE[_v] = "DCE"
for _v in ["SR", "CF", "TA", "MA", "FG", "RM", "OI", "ZC", "AP", "CJ",
           "UR", "SA", "PF", "PK", "SF", "SM", "WH", "PM", "RI", "LR",
           "JR", "CY", "RS", "SH", "PX", "PR"]:
    VARIETY_EXCHANGE[_v] = "CZCE"
for _v in ["IF", "IC", "IH", "IM", "T", "TF", "TS", "TL"]:
    VARIETY_EXCHANGE[_v] = "CFFEX"
for _v in ["sc", "lu", "nr", "bc", "ec"]:
    VARIETY_EXCHANGE[_v] = "INE"
for _v in ["si", "lc", "ps"]:
    VARIETY_EXCHANGE[_v] = "GFEX"


def _match_variety_key(mapping: dict, variety: str):
    if variety in mapping:
        return mapping[variety]
    vl = variety.lower()
    for k, v in mapping.items():
        if k.lower() == vl:
            return v
    return None


def lookup_exchange(variety: str) -> str:
    code = _match_variety_key(VARIETY_EXCHANGE, variety)
    if code is None:
        return "其他"
    return EXCHANGE_CN.get(code, code)


def extract_variety(inst: str) -> str:
    m = re.match(r"^([A-Za-z]+)", str(inst))
    return m.group(1) if m else str(inst)


# ── 品种中文名 / 板块 ────────────────────────────────
VARIETY_CN: dict[str, str] = {
    "AP": "苹果", "CJ": "红枣", "CS": "玉米淀粉", "JD": "鸡蛋", "LG": "原木", "LH": "生猪",
    "BR": "合成橡胶", "BU": "沥青", "EB": "苯乙烯", "EG": "乙二醇", "L": "塑料",
    "MA": "甲醇", "NR": "20号胶", "PF": "短纤", "PP": "聚丙烯", "PR": "瓶片",
    "PX": "对二甲苯", "RU": "橡胶", "SA": "纯碱", "SH": "烧碱", "SP": "纸浆",
    "TA": "精对苯二甲酸", "UR": "尿素",
    "AL": "沪铝", "AO": "氧化铝", "BC": "国际铜", "CU": "沪铜", "LC": "碳酸锂",
    "NI": "沪镍", "PB": "沪铅", "SI": "工业硅", "SN": "沪锡", "ZN": "沪锌",
    "A": "豆一", "B": "豆二", "M": "豆粕", "OI": "菜油", "P": "棕榈油",
    "PK": "花生", "RM": "菜粕", "RS": "菜籽", "Y": "豆油",
    "HC": "热卷", "I": "铁矿石", "J": "焦炭", "JM": "焦煤", "RB": "螺纹钢",
    "SF": "硅铁", "SM": "锰硅", "SS": "不锈钢", "WR": "线材",
    "FU": "燃油", "LU": "低硫燃油", "PG": "液化石油气", "SC": "原油", "ZC": "动力煤",
    "C": "玉米", "JR": "粳稻", "LR": "晚籼稻", "PM": "普麦", "RI": "早籼稻",
    "RR": "粳米", "WH": "强麦",
    "AG": "沪银", "AU": "沪金",
    "CF": "棉花", "CY": "棉纱", "SR": "白糖",
    "FG": "玻璃", "BB": "胶合板", "FB": "纤维板", "V": "聚氯乙烯",
    "PS": "多晶硅",
    "IC": "中证500股指", "IF": "沪深300股指", "IH": "上证50股指", "IM": "中证1000股指",
    "T": "十年期国债", "TF": "五年期国债", "TS": "二年期国债", "TL": "三十年期国债",
    "EC": "欧线集运",
}

SECTOR_ORDER = [
    "农副产品", "化工", "有色", "油脂油料", "煤焦钢矿", "能源",
    "谷物", "贵金属", "软商品", "非金属建材", "其他-多晶硅", "股指", "其他",
]
VARIETY_SECTOR: dict[str, str] = {}
for _v in ["AP", "CJ", "CS", "JD", "LG", "LH"]:
    VARIETY_SECTOR[_v] = "农副产品"
for _v in ["BR", "BU", "EB", "EG", "L", "MA", "NR", "PF", "PP", "PR",
           "PX", "RU", "SA", "SH", "SP", "TA", "UR"]:
    VARIETY_SECTOR[_v] = "化工"
for _v in ["AL", "AO", "BC", "CU", "LC", "NI", "PB", "SI", "SN", "ZN"]:
    VARIETY_SECTOR[_v] = "有色"
for _v in ["A", "B", "M", "OI", "P", "PK", "RM", "RS", "Y"]:
    VARIETY_SECTOR[_v] = "油脂油料"
for _v in ["HC", "I", "J", "JM", "RB", "SF", "SM", "SS", "WR"]:
    VARIETY_SECTOR[_v] = "煤焦钢矿"
for _v in ["FU", "LU", "PG", "SC", "ZC"]:
    VARIETY_SECTOR[_v] = "能源"
for _v in ["C", "JR", "LR", "PM", "RI", "RR", "WH"]:
    VARIETY_SECTOR[_v] = "谷物"
for _v in ["AG", "AU"]:
    VARIETY_SECTOR[_v] = "贵金属"
for _v in ["CF", "CY", "SR"]:
    VARIETY_SECTOR[_v] = "软商品"
for _v in ["FG", "BB", "FB", "V"]:
    VARIETY_SECTOR[_v] = "非金属建材"
for _v in ["PS"]:
    VARIETY_SECTOR[_v] = "其他-多晶硅"
for _v in ["IC", "IF", "IH", "IM"]:
    VARIETY_SECTOR[_v] = "股指"

EXCHANGE_NAMES = set(EXCHANGE_CN.values()) | {"其他"}
SECTOR_NAMES = set(SECTOR_ORDER)


def lookup_variety_cn(variety: str) -> str:
    name = _match_variety_key(VARIETY_CN, variety)
    return name if name else variety


def lookup_sector(variety: str) -> str:
    sector = _match_variety_key(VARIETY_SECTOR, variety)
    return sector if sector else "其他"


def instrument_title(inst: str, variety: str | None = None) -> str:
    if variety is None:
        variety = extract_variety(inst)
    cn = lookup_variety_cn(variety)
    if cn and cn.lower() != variety.lower():
        return f"{inst} {cn}"
    return str(inst)


# ── 辅助函数 ──────────────────────────────────────
def get_date_from_calendar() -> tuple[int, int]:
    date = datetime.datetime.now().date()
    date_int = int(date.strftime("%Y%m%d"))
    date_list = np.loadtxt(CALENDAR_PATH, dtype=np.int64, ndmin=1)
    pos = np.searchsorted(date_list, date_int, side="right")
    date_int = int(date_list[pos - 1])
    next_trade_day = int(date_list[pos])
    return date_int, next_trade_day


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


def get_static_info_path(market: str) -> list[str]:
    return ["/cpfs/rawdata/cncf_all_nedd_before_open/ins_static_info.csv",
            "/cpfs/rawdata/cnif_all_need_before_open/ins_static_info.csv"]


def get_market_data_path(market: str, data_date: int) -> list[str]:
    kinds = ["commodity", "futures"]
    if datetime.datetime.now().hour >= 20 or datetime.datetime.now().hour < 9 or (
            datetime.datetime.now().hour == 9 and datetime.datetime.now().minute < 30):
        kinds.remove("futures")
    return [f"/mnt/nfs_bohr_data1/china/trading_realdata/partial_market_data_realtime/{kind}/{data_date}.csv"
            for kind in kinds]


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


def is_commodity_night_session_pre_midnight(t: datetime.time) -> bool:
    return t >= datetime.time(21, 0)


def get_data_date(market: str, path: str, current_date: int, market_open: bool) -> tuple[int, str]:
    now = datetime.datetime.now()
    t = now.time()
    if market_open:
        if market == "commodity" and is_commodity_night_session_pre_midnight(t):
            next_td = get_next_trade_date(current_date)
            return next_td, f" (night→{next_td})"
        return current_date, ""
    return current_date, ""


def is_market_open(market: str) -> bool:
    t = datetime.datetime.now().time()
    sessions = [
        (datetime.time(9, 0), datetime.time(10, 15), False),
        (datetime.time(10, 30), datetime.time(11, 30), False),
        (datetime.time(13, 30), datetime.time(15, 0), False),
        (datetime.time(21, 0), datetime.time(2, 30), True),
    ] if market == "commodity" else [
        (datetime.time(9, 30), datetime.time(11, 30), False),
        (datetime.time(13, 0), datetime.time(15, 0), False),
    ]
    for s_start, s_end, cross in sessions:
        if cross:
            if t >= s_start or t <= s_end:
                return True
        elif s_start <= t <= s_end:
            return True
    return False


# ── 价格缓存 ──
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
                inst = row["instrument_id"]
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
        ask = row.get("ask_price1", 0)
        bid = row.get("bid_price1", 0)
        if pd.notna(ask) and pd.notna(bid) and (ask + bid) > 0:
            _price_cache[inst] = float((ask + bid) / 2)


def get_price(instrument: str) -> float | None:
    return _price_cache.get(instrument)


# ── 图表构建函数 ─────────────────────────────────────
CHART_SESSIONS = [
    (datetime.time(21, 0), datetime.time(2, 30), True),
    (datetime.time(9, 0), datetime.time(10, 15), False),
    (datetime.time(10, 30), datetime.time(11, 30), False),
    (datetime.time(13, 30), datetime.time(15, 0), False),
]

_CHART_MAX_GAP = 15
_POS_SNAP_COLS = [
    "instrument_id", "pos_type", "position",
    "close_profit", "position_profit", "pre_settlement_price",
]


def _in_chart_session(t: datetime.time) -> bool:
    for s_start, s_end, cross in CHART_SESSIONS:
        if cross:
            if t >= s_start or t <= s_end:
                return True
        elif s_start <= t <= s_end:
            return True
    return False


def _chart_session_base(current_date: int) -> datetime.datetime:
    d = datetime.datetime.strptime(str(current_date), "%Y%m%d")
    return datetime.datetime.combine((d - timedelta(days=1)).date(), datetime.time(21, 0))


def _chart_session_end(current_date: int) -> datetime.datetime:
    d = datetime.datetime.strptime(str(current_date), "%Y%m%d")
    return datetime.datetime.combine(d.date(), datetime.time(15, 0))


def build_chart_time_maps(current_date: int, tick_step: int = 5, label_interval: int = 6):
    base = _chart_session_base(current_date)
    end = _chart_session_end(current_date)
    dt_to_idx: dict[datetime.datetime, int] = {}
    idx_to_label: dict[int, str] = {}
    all_tick_vals: list[int] = []
    ticktext: list[str] = []
    cur = base
    idx = 0
    label_every = tick_step * label_interval
    while cur <= end:
        if _in_chart_session(cur.time()):
            key = cur.replace(second=0, microsecond=0)
            dt_to_idx[key] = idx
            label = cur.strftime("%H:%M")
            idx_to_label[idx] = label
            if idx % tick_step == 0:
                all_tick_vals.append(idx)
                ticktext.append(label if idx % label_every == 0 else "")
            idx += 1
        cur += timedelta(minutes=1)
    return dt_to_idx, idx_to_label, all_tick_vals, ticktext


def get_trade_minute_index(dt: datetime.datetime, base: datetime.datetime,
                           dt_to_idx: dict | None = None) -> int:
    if dt_to_idx is not None:
        key = dt.replace(second=0, microsecond=0)
        if key in dt_to_idx:
            return dt_to_idx[key]
        best = None
        for k, v in dt_to_idx.items():
            if k <= key and (best is None or k > best):
                best = k
        if best is not None:
            return dt_to_idx[best]
        return 0
    minutes = 0
    cur = base
    while cur < dt:
        if _in_chart_session(cur.time()):
            minutes += 1
        cur += timedelta(minutes=1)
    return minutes


def _break_gaps(df: pd.DataFrame, ycol: str, max_gap: int = _CHART_MAX_GAP) -> pd.DataFrame:
    if df is None or df.empty or ycol not in df.columns:
        return df
    df = df.sort_values("time_idx").copy()
    xs = df["time_idx"].to_numpy()
    if len(xs) <= 1:
        return df
    rows = []
    last_x = None
    for rec in df.to_dict("records"):
        x = rec.get("time_idx")
        if last_x is not None and pd.notna(x) and (x - last_x) > max_gap:
            gap = dict(rec)
            gap[ycol] = None
            if "time_label" in gap:
                gap["time_label"] = ""
            rows.append(gap)
        rows.append(rec)
        last_x = x
    return pd.DataFrame(rows)


def _read_position_snapshot(fpath: str) -> pd.DataFrame | None:
    try:
        df = pd.read_csv(fpath, usecols=lambda c: c in _POS_SNAP_COLS)
        return df
    except Exception:
        df, err = safe_read_csv(fpath)
        if err or df is None or df.empty:
            return None
        cols = [c for c in _POS_SNAP_COLS if c in df.columns]
        return df[cols] if cols else df


def _agg_snapshot(df: pd.DataFrame | None) -> pd.DataFrame:
    empty = pd.DataFrame(columns=["instrument", "net_pos", "cum_pnl", "price"])
    if df is None or df.empty or "instrument_id" not in df.columns:
        return empty
    work = df.copy()
    work["instrument_id"] = work["instrument_id"].astype(str)
    for col in ("position", "close_profit", "position_profit", "pre_settlement_price"):
        if col not in work.columns:
            work[col] = 0.0
        work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0.0)
    if "pos_type" not in work.columns:
        work["pos_type"] = "LONG"
    long = work[work["pos_type"] == "LONG"].groupby("instrument_id", as_index=False).agg(
        long_pos=("position", "sum"),
        cp_l=("close_profit", "sum"),
        pp_l=("position_profit", "sum"),
        px_l=("pre_settlement_price", "first"),
    )
    short = work[work["pos_type"] == "SHORT"].groupby("instrument_id", as_index=False).agg(
        short_pos=("position", "sum"),
        cp_s=("close_profit", "sum"),
        pp_s=("position_profit", "sum"),
        px_s=("pre_settlement_price", "first"),
    )
    out = pd.merge(long, short, on="instrument_id", how="outer")
    for c in ("long_pos", "short_pos", "cp_l", "pp_l", "cp_s", "pp_s", "px_l", "px_s"):
        if c not in out.columns:
            out[c] = 0.0
        out[c] = out[c].fillna(0.0)
    out["net_pos"] = out["long_pos"] - out["short_pos"]
    out["cum_pnl"] = out["cp_l"] + out["pp_l"] + out["cp_s"] + out["pp_s"]
    out["price"] = np.where(out["px_l"] != 0, out["px_l"], out["px_s"])
    out = out.rename(columns={"instrument_id": "instrument"})
    return out[["instrument", "net_pos", "cum_pnl", "price"]]


def build_intraday_series(
    cfg: dict,
    current_date: int,
    static_df: pd.DataFrame | None,
    init_capital: float,
    dt_to_idx: dict | None = None,
    idx_to_label: dict | None = None,
) -> dict | None:
    path = cfg["path"]
    try:
        files = [f for f in os.listdir(path) if f.startswith("position_data_") and f.endswith(".csv")]
    except Exception:
        return None
    if not files:
        return None

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

    base = _chart_session_base(current_date)
    end = _chart_session_end(current_date)

    timed_files = []
    for f in files:
        dt = parse_time_from_filename(f)
        if dt is None:
            continue
        if dt < base - timedelta(minutes=5) or dt > end + timedelta(minutes=5):
            continue
        timed_files.append((dt, os.path.join(path, f)))
    timed_files.sort(key=lambda x: x[0])

    if not timed_files:
        return None

    mult_map = {}
    if static_df is not None and not static_df.empty and "instrument" in static_df.columns:
        tmp = static_df[["instrument", "multiplier"]].dropna(subset=["instrument"]).copy()
        tmp["multiplier"] = pd.to_numeric(tmp["multiplier"], errors="coerce").fillna(1.0)
        mult_map = dict(zip(tmp["instrument"].astype(str), tmp["multiplier"]))

    frames = []
    for dt, fpath in timed_files:
        time_idx = get_trade_minute_index(dt, base, dt_to_idx)
        if idx_to_label is not None and time_idx in idx_to_label:
            time_label = idx_to_label[time_idx]
        else:
            time_label = dt.strftime("%H:%M")
        snap = _agg_snapshot(_read_position_snapshot(fpath))
        if snap.empty:
            continue
        snap = snap.copy()
        snap["time_idx"] = time_idx
        snap["time_label"] = time_label
        frames.append(snap)

    if not frames:
        return None

    all_df = pd.concat(frames, ignore_index=True)
    all_df = all_df.sort_values(["instrument", "time_idx"]).drop_duplicates(
        subset=["instrument", "time_idx"], keep="last"
    )

    px = all_df["instrument"].map(lambda inst: get_price(inst) if get_price(inst) is not None else np.nan)
    all_df["price"] = px.fillna(all_df["price"])
    all_df["mult"] = all_df["instrument"].map(mult_map).fillna(1.0)
    all_df["market_value"] = (all_df["net_pos"].abs() * all_df["price"] * all_df["mult"]).astype(float)

    first_net = all_df.sort_values("time_idx").groupby("instrument", as_index=True)["net_pos"].first()
    all_df["open_net"] = all_df["instrument"].map(first_net).fillna(0.0)

    result = {}
    for inst, g in all_df.groupby("instrument", sort=False):
        g = g.sort_values("time_idx")
        if (g["net_pos"].abs().sum() == 0) and (g["cum_pnl"].abs().sum() == 0) and (g["market_value"].sum() == 0):
            continue
        result[inst] = g[["time_idx", "time_label", "net_pos", "market_value", "cum_pnl", "open_net", "price"]].reset_index(drop=True)

    return result if result else None


# ── 页面渲染 ─────────────────────────────────────────────
def _render_page():
    st.title("📊 All Contracts: Position & PnL (Intraday)")

    current_date, _ = get_date_from_calendar()

    # ── 缓存数据 ──
    cache_key = f"all_contract_data_{current_date}"
    if cache_key not in st.session_state:
        static_paths = []
        for market in ["commodity", "futures"]:
            paths = get_static_info_path(market)
            if isinstance(paths, list):
                static_paths.extend(paths)
            else:
                static_paths.append(paths)
        static_df, _ = safe_read_csv(static_paths)

        init_price_cache("commodity", current_date)
        init_price_cache("futures", current_date)

        all_product_data = {}
        for cfg in PRODUCT_CONFIGS:
            key = f"{cfg['market']}_{cfg['product']}"
            data = build_intraday_series(
                cfg, current_date, static_df, 1.0,
                dt_to_idx=None, idx_to_label=None,
            )
            if data:
                all_product_data[key] = (data, cfg["broker"], cfg["product"])
        st.session_state[cache_key] = all_product_data
    else:
        all_product_data = st.session_state[cache_key]

    if not all_product_data:
        st.error("⚠️ 没有可用的日内数据，请检查快照文件是否包含非零持仓。")
        return

    # ── 统一时间刻度 ──
    dt_to_idx, idx_to_label, all_tick_vals, ticktext = build_chart_time_maps(current_date)
    if not all_tick_vals:
        st.error("⚠️ 无法生成交易时段刻度，请检查系统日期。")
        return

    xaxis_range = [min(all_tick_vals), max(all_tick_vals)]
    xaxis_dict = dict(
        title="Time",
        tickmode='array',
        tickvals=all_tick_vals,
        ticktext=ticktext,
        tickangle=-45,
        range=xaxis_range,
        showgrid=True,
        gridcolor='lightgray',
        gridwidth=0.5,
        zeroline=False,
    )

    # ── 筛选控件 ──
    st.markdown("### 🔍 筛选条件")
    col1, col2, col3 = st.columns([1, 1, 2])

    available_products = sorted({pname for _, (_, _, pname) in all_product_data.items()})
    product_options = ["all"] + available_products
    default_product_idx = product_options.index("shjq") if "shjq" in product_options else 0

    with col1:
        selected_product = st.selectbox("产品", product_options, index=default_product_idx)

    filtered_by_product = []
    for product_key, (instrument_data, broker, product_name) in all_product_data.items():
        if selected_product != "all" and product_name != selected_product:
            continue
        for inst, df in instrument_data.items():
            variety = extract_variety(inst)
            exch = lookup_exchange(variety)
            sector = lookup_sector(variety)
            filtered_by_product.append({
                "product_key": product_key,
                "product_name": product_name,
                "broker": broker,
                "instrument": inst,
                "variety": variety,
                "exchange": exch,
                "sector": sector,
                "cn_name": lookup_variety_cn(variety),
                "df": df,
            })

    available_exchanges = sorted({d["exchange"] for d in filtered_by_product})
    available_sectors = [s for s in SECTOR_ORDER if any(d["sector"] == s for d in filtered_by_product)]
    group_options = ["all"] + available_exchanges + available_sectors

    with col2:
        selected_group = st.selectbox(
            "交易所/板块", group_options, index=0,
            key=f"group_select_{selected_product}",
        )

    if selected_group == "all":
        filtered_data = filtered_by_product
    elif selected_group in EXCHANGE_NAMES:
        filtered_data = [d for d in filtered_by_product if d["exchange"] == selected_group]
    else:
        filtered_data = [d for d in filtered_by_product if d["sector"] == selected_group]

    with col3:
        st.markdown(
            f"<div style='padding-top: 28px; color: #666;'>"
            f"筛选到 <b>{len(filtered_data)}</b> 个合约"
            f"</div>",
            unsafe_allow_html=True,
        )

    if not filtered_data:
        st.info("没有符合筛选条件的合约数据。")
        return

    filtered_data.sort(key=lambda d: (d["product_key"], d["exchange"], d["sector"], d["instrument"]))

    # ─────────────────────────────────────────────────
    # Contract Profit / Init Capital (bps) 折线图
    # ─────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("📈 Contract Profit / Init Capital (bps)")

    fig_bps = go.Figure()
    has_bps = False
    for d in filtered_data:
        inst = d["instrument"]
        df = d["df"]
        if df is None or df.empty:
            continue
        init_cap = DEFAULT_INIT_CAP
        for _c in PRODUCT_CONFIGS:
            if _c.get("product") == d["product_name"] and _c.get("init_capital", 0) > 0:
                init_cap = float(_c["init_capital"])
                break

        group = df[["time_idx", "time_label", "cum_pnl"]].copy()
        group["pnl_ratio"] = (group["cum_pnl"] / init_cap * 10000) if init_cap != 0 else 0.0
        group = group.sort_values("time_idx")
        group = _break_gaps(group, "pnl_ratio")
        customdata = np.column_stack((
            [d["product_key"]] * len(group),
            [inst] * len(group),
            group["cum_pnl"],
            [init_cap] * len(group),
        ))
        fig_bps.add_trace(go.Scatter(
            x=group["time_idx"],
            y=group["pnl_ratio"],
            mode="lines",
            name=f"{d['product_key']}_{inst}",
            line=dict(shape="hv", width=1),
            connectgaps=False,
            customdata=customdata,
            hovertemplate=(
                "时间: %{text}<br>"
                "盈亏/初始资金: %{y:.2f} bps<br>"
                "盈亏: %{customdata[2]:,.2f} / %{customdata[3]:,.2f}<br>"
                "产品: %{customdata[0]}<br>"
                "合约: %{customdata[1]}<extra></extra>"
            ),
            text=group["time_label"],
        ))
        has_bps = True

    if has_bps:
        fig_bps.update_layout(
            title=(
                f"Contract Profit / Init Capital (Selected Contracts, "
                f"product={selected_product}, group={selected_group}, "
                f"init_cap default={DEFAULT_INIT_CAP:,.0f})"
            ),
            xaxis=xaxis_dict,
            yaxis=dict(
                title="Profit / Init Capital (bps)",
                autorange=True,
                exponentformat="none",
                showexponent="none",
                tickformat=",.0f",
            ),
            legend_title="Contracts (Product_Instrument)",
            hovermode="x unified",
            height=450,
            margin=dict(l=60, r=40, t=60, b=40),
        )
        st.plotly_chart(fig_bps, width="stretch", key="bps_chart")
    else:
        st.info("没有可用于绘制 盈亏/初始资金 曲线的合约数据。")

    # ─────────────────────────────────────────────────
    # 每个合约的小图
    # ─────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("📊 Per-Contract Position & PnL")

    chart_list = []
    for d in filtered_data:
        df_sorted = d["df"].sort_values("time_idx").copy()
        df_pos = _break_gaps(df_sorted, "net_pos")
        df_pnl = _break_gaps(df_sorted, "cum_pnl")

        inst = d["instrument"]
        inst_label = instrument_title(inst, d.get("variety"))

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_pos["time_idx"],
            y=df_pos["net_pos"],
            mode="lines+markers",
            name=f"{inst_label} 持仓 (手)",
            line=dict(shape="hv", width=2, color="blue"),
            connectgaps=False,
            marker=dict(size=3),
            yaxis="y",
            hovertemplate="时间: %{text}<br>持仓: %{y:,.0f} 手<extra></extra>",
            text=df_pos["time_label"],
        ))
        fig.add_trace(go.Scatter(
            x=df_pnl["time_idx"],
            y=df_pnl["cum_pnl"],
            mode="lines+markers",
            name=f"{inst_label} 盈亏 (元)",
            line=dict(shape="hv", width=2, color="red", dash="dot"),
            connectgaps=False,
            marker=dict(size=3),
            yaxis="y2",
            hovertemplate="时间: %{text}<br>盈亏: %{y:,.2f} 元<extra></extra>",
            text=df_pnl["time_label"],
        ))

        fig.update_layout(
            title=f"【{d['product_key']}】{inst_label}  ({d['exchange']} · {d['sector']} · broker: {d['broker']})",
            xaxis=xaxis_dict,
            yaxis=dict(
                title="持仓 (手)",
                autorange=True,
                side="left",
                showgrid=True,
                gridcolor='lightgray',
                zeroline=True,
                exponentformat="none",
                showexponent="none",
                tickformat=",.0f",
            ),
            yaxis2=dict(
                title="盈亏 (元)",
                autorange=True,
                side="right",
                overlaying="y",
                showgrid=False,
                zeroline=True,
                exponentformat="none",
                showexponent="none",
                tickformat=",.0f",
            ),
            legend=dict(x=0.02, y=0.98, font=dict(size=9)),
            hovermode="x unified",
            height=300,
            margin=dict(l=40, r=40, t=50, b=40),
        )
        chart_list.append(fig)

    # ── 每行3个图布局 ──
    cols_per_row = 3
    for i in range(0, len(chart_list), cols_per_row):
        cols = st.columns(cols_per_row)
        for j in range(cols_per_row):
            idx = i + j
            if idx < len(chart_list):
                with cols[j]:
                    st.plotly_chart(chart_list[idx], width="stretch",
                                    key=f"chart_{selected_product}_{selected_group}_{idx}")

    st.caption(
        f"产品：{selected_product} | 交易所/板块：{selected_group} | "
        f"共展示 {len(chart_list)} 个合约图表"
    )


# ── 自动刷新包装 ─────────────────────────────────────────
def main():
    st.set_page_config(page_title="All Contracts Summary", layout="wide")

    # ── 自动刷新控件 ──
    with st.container():
        c1, c2, c3 = st.columns([1, 1, 3])
        with c1:
            enable_auto_refresh = st.checkbox(
                "自动刷新", value=True, key="enable_auto_refresh"
            )
        with c2:
            refresh_interval = st.number_input(
                "刷新间隔 (秒)",
                min_value=30, max_value=3600,
                value=300, step=30,
                key="refresh_interval",
            )
        with c3:
            last_updated = st.session_state.get("last_refresh_time", "—")
            st.caption(
                f"自动刷新：{'开启' if enable_auto_refresh else '关闭'} | "
                f"间隔：{refresh_interval} 秒 | "
                f"上次刷新：{last_updated}"
            )

    # ── 页面渲染（内部出错也不影响自动刷新） ──
    try:
        _render_page()
    except Exception as e:
        import traceback
        st.error(f"页面渲染出错：{e}")
        st.code(traceback.format_exc())

    st.session_state["last_refresh_time"] = datetime.datetime.now().strftime("%H:%M:%S")

    if enable_auto_refresh:
        time.sleep(int(refresh_interval))
        st.rerun()


if __name__ == "__main__":
    main()