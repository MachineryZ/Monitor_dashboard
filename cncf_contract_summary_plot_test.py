import os
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

# ── 辅助函数（从原脚本复制，精简）────────────────────

def get_date_from_calendar() -> tuple[int, int]:
    date = datetime.datetime.now().date()
    date_int = int(date.strftime("%Y%m%d"))
    date_list = np.loadtxt(CALENDAR_PATH, dtype=np.int64, ndmin=1)
    pos = np.searchsorted(date_list, date_int, side="right")
    date_int = int(date_list[pos-1])
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
    if datetime.datetime.now().hour >= 20 or datetime.datetime.now().hour < 9 or (datetime.datetime.now().hour == 9 and datetime.datetime.now().minute < 30):
        kinds.remove("futures")
    return [f"/mnt/nfs_bohr_data1/china/trading_realdata/partial_market_data_realtime/{kind}/{data_date}.csv" for kind in kinds]

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
    t   = now.time()
    if market_open:
        if market == "commodity" and is_commodity_night_session_pre_midnight(t):
            next_td = get_next_trade_date(current_date)
            return next_td, f" (night→{next_td})"
        return current_date, ""
    return current_date, ""

def is_market_open(market: str) -> bool:
    t = datetime.datetime.now().time()
    sessions = [
        (datetime.time(9,  0),  datetime.time(10, 15), False),
        (datetime.time(10, 30), datetime.time(11, 30), False),
        (datetime.time(13, 30), datetime.time(15,  0), False),
        (datetime.time(21,  0), datetime.time(2,  30), True ),
    ] if market == "commodity" else [
        (datetime.time(9,  30), datetime.time(11, 30), False),
        (datetime.time(13,  0), datetime.time(15,  0), False),
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

# ── 图表构建函数（来自原脚本）────────────────────────

CHART_SESSIONS = [
    (datetime.time(21, 0), datetime.time(2, 30), True),
    (datetime.time(9, 0),  datetime.time(10, 15), False),
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

# ── 主页面 ─────────────────────────────────────────────

def main():
    st.set_page_config(page_title="All Contracts Summary", layout="wide")
    st.title("📊 All Contracts: Position & PnL (Intraday)")

    # ── 侧边栏产品选择 ──
    with st.sidebar:
        st.header("Product Filter")
        product_checks = {}
        for cfg in PRODUCT_CONFIGS:
            label = f"{cfg['market']}_{cfg['product']}"
            product_checks[label] = st.checkbox(label, value=True)

    current_date, _ = get_date_from_calendar()

    # ── 缓存数据 ──
    cache_key = f"all_contract_data_{current_date}"
    if cache_key not in st.session_state:
        # 加载静态信息
        static_paths = []
        for market in ["commodity", "futures"]:
            paths = get_static_info_path(market)
            if isinstance(paths, list):
                static_paths.extend(paths)
            else:
                static_paths.append(paths)
        static_df, _ = safe_read_csv(static_paths)

        # 初始化价格缓存
        init_price_cache("commodity", current_date)
        init_price_cache("futures",   current_date)

        # 构建所有产品的日内数据
        all_product_data = {}
        for cfg in PRODUCT_CONFIGS:
            key = f"{cfg['market']}_{cfg['product']}"
            init_cap = 1.0
            data = build_intraday_series(
                cfg, current_date, static_df, init_cap,
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

    # 构建统一的时间刻度（所有图表共用）
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

    # ── 筛选需要显示的产品 ──
    filtered_product_data = {}
    for product_key, (instrument_data, broker, product_name) in all_product_data.items():
        if product_checks.get(product_key, True):
            filtered_product_data[product_key] = (instrument_data, broker, product_name)

    if not filtered_product_data:
        st.info("请至少选择一个产品。")
        return

    # ── 按品种合并（同一品种不同月份合约合并为一条曲线） ──
    def extract_variety(inst: str) -> str:
        match = re.match(r'^([A-Za-z]+)', inst)
        if match:
            return match.group(1)
        return inst

    merged_product_data = {}
    for product_key, (instrument_data, broker, product_name) in filtered_product_data.items():
        variety_dict = {}
        for inst, df in instrument_data.items():
            variety = extract_variety(inst)
            if variety not in variety_dict:
                variety_dict[variety] = []
            variety_dict[variety].append(df)
        # 合并每个品种
        merged_instrument_data = {}
        for variety, dfs in variety_dict.items():
            # 合并所有合约数据，按time_idx聚合求和
            combined = pd.concat(dfs, ignore_index=True)
            grouped = combined.groupby('time_idx', as_index=False).agg({
                'net_pos': 'sum',
                'cum_pnl': 'sum',
                'time_label': 'first',  # 时间标签取第一个
            })
            merged_df = grouped[['time_idx', 'time_label', 'net_pos', 'cum_pnl']].sort_values('time_idx').reset_index(drop=True)
            merged_instrument_data[variety] = merged_df
        merged_product_data[product_key] = (merged_instrument_data, broker, product_name)

    # ── 收集所有合并后的品种图表 ──
    chart_list = []
    for product_key, (instrument_data, broker, product_name) in merged_product_data.items():
        for variety, df in instrument_data.items():
            df_sorted = df.sort_values("time_idx").copy()
            df_pos = _break_gaps(df_sorted, "net_pos")
            df_pnl = _break_gaps(df_sorted, "cum_pnl")

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_pos["time_idx"],
                y=df_pos["net_pos"],
                mode="lines+markers",
                name=f"{variety} 持仓 (手)",
                line=dict(shape="hv", width=2, color="blue"),
                connectgaps=False,
                marker=dict(size=3),
                yaxis="y",
                hovertemplate="时间: %{text}<br>持仓: %{y:.0f} 手<extra></extra>",
                text=df_pos["time_label"],
            ))
            fig.add_trace(go.Scatter(
                x=df_pnl["time_idx"],
                y=df_pnl["cum_pnl"],
                mode="lines+markers",
                name=f"{variety} 盈亏 (元)",
                line=dict(shape="hv", width=2, color="red", dash="dot"),
                connectgaps=False,
                marker=dict(size=3),
                yaxis="y2",
                hovertemplate="时间: %{text}<br>盈亏: %{y:,.2f} 元<extra></extra>",
                text=df_pnl["time_label"],
            ))

            fig.update_layout(
                title=f"【{product_key}】{variety}  (broker: {broker})",
                xaxis=xaxis_dict,
                yaxis=dict(
                    title="持仓 (手)",
                    autorange=True,
                    side="left",
                    showgrid=True,
                    gridcolor='lightgray',
                    zeroline=True,
                ),
                yaxis2=dict(
                    title="盈亏 (元)",
                    autorange=True,
                    side="right",
                    overlaying="y",
                    showgrid=False,
                    zeroline=True,
                ),
                legend=dict(x=0.02, y=0.98, font=dict(size=9)),
                hovermode="x unified",
                height=300,
                margin=dict(l=40, r=40, t=50, b=40),
            )
            chart_list.append((fig, f"{product_key} | {variety}"))

    # ── 每行3个图布局 ──
    cols_per_row = 3
    for i in range(0, len(chart_list), cols_per_row):
        cols = st.columns(cols_per_row)
        for j in range(cols_per_row):
            idx = i + j
            if idx < len(chart_list):
                fig, title = chart_list[idx]
                with cols[j]:
                    st.plotly_chart(fig, width="stretch", key=f"fig_{idx}")

    st.caption(f"共展示 {len(chart_list)} 个品种图表（按品种合并）")


if __name__ == "__main__":
    main()