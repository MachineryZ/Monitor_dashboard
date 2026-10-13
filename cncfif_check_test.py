import os
import re
import time
import datetime
import pandas as pd
import numpy as np
import streamlit as st

# ── 配置 ──────────────────────────────────────────────
CALENDAR_PATH = "/cpfs/intrastats/calendar"
REFRESH_INTERVAL_SECONDS = 300  # 自动刷新间隔（秒）

# 交易所映射（品种前缀 → 交易所代码）
VARIETY_EXCHANGE = {}
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

EXCHANGE_CN = {
    "SHFE": "上期所",
    "DCE": "大商所",
    "CZCE": "郑商所",
    "CFFEX": "中金所",
    "INE": "上期能源",
    "GFEX": "广期所",
}

def extract_variety(inst):
    m = re.match(r"^([A-Za-z]+)", str(inst))
    return m.group(1) if m else str(inst)

def lookup_exchange(variety):
    if variety in VARIETY_EXCHANGE:
        return VARIETY_EXCHANGE[variety]
    vl = variety.lower()
    for k, v in VARIETY_EXCHANGE.items():
        if k.lower() == vl:
            return v
    return "其他"

# 账户配置（含信号目录与仓位路径）
ACCOUNT_CONFIGS = [
    {
        "account": "ax1h_ya",
        "broker": "ya",
        "market": "commodity",
        "signal_dir": "cncf_melt_ax1h_ya_bohr",
        "position_path": "/mnt/nfs_bohr_data1/china/trading_realdata/cncf_trade_data_ax1h_ya",
    },
    {
        "account": "bgt_ax1h",
        "broker": "dz",
        "market": "commodity",
        "signal_dir": "cncf_melt_bgt_dz_bohr",
        "position_path": "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_data_baguatian",
    },
    {
        "account": "shjq",
        "broker": "zx",
        "market": "commodity",
        "signal_dir": "cncf_melt_shjq_zx_bohr",
        "position_path": "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_data_shjq_zx",
    },
    {
        "account": "shph1h",
        "broker": "zx",
        "market": "commodity",
        "signal_dir": "cncf_melt_shph1h_zx_bohr",
        "position_path": "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_data_shph1h_zx",
    },
    {
        "account": "zz1h",
        "broker": "dz",
        "market": "commodity",
        "signal_dir": "cncf_melt_zhizeng_dz_bohr",
        "position_path": "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_date",
    },
    {
        "account": "jz1h",
        "broker": "dz",
        "market": "futures",
        "signal_dir": "cnif_short_jz1h_dz_dashboard_bohr",
        "position_path": "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_jz1h",
    },
    {
        "account": "ly1h",
        "broker": "dz",
        "market": "futures",
        "signal_dir": "cnif_position_melt_ly1h_dz_dashboard_bohr",
        "position_path": "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_ly1h",
    },
    {
        "account": "zz1h_zx",
        "broker": "zx",
        "market": "futures",
        "signal_dir": "cnif_short_zz1h_zx_dashboard_bohr",
        "position_path": "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_zz1h",
    },
    {
        "account": "zz1h_ya",
        "broker": "ya",
        "market": "futures",
        "signal_dir": None,   # 暂无对应信号目录
        "position_path": "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_zz1h_ya",
    },
    {
        "account": "jx1h_zx",
        "broker": "zx",
        "market": "futures",
        "signal_dir": "cnif_melt_ls_jx1h_zx_dashboard_bohr",
        "position_path": "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_jx1h_zx",
    },
]

# ── 日历 ──────────────────────────────────────────────
def get_date_from_calendar():
    date = datetime.datetime.now().date()
    date_int = int(date.strftime("%Y%m%d"))
    try:
        date_list = np.loadtxt(CALENDAR_PATH, dtype=np.int64, ndmin=1)
        pos = np.searchsorted(date_list, date_int, side="right")
        date_int = int(date_list[pos - 1])
        next_trade_day = int(date_list[pos]) if pos < len(date_list) else date_int
    except Exception:
        next_trade_day = date_int
    return date_int, next_trade_day

# ── 信号文件读取（已修复列名问题） ──────────────────────
def load_signal_file(market, signal_dir, trade_date):
    if signal_dir is None:
        return None
    if market == "commodity":
        base = "/cpfs/prod/prod_log/china_future/cncf"
    else:
        base = "/cpfs/prod/prod_log/china_future/cnif"
    path = os.path.join(base, signal_dir, f"{trade_date}.csv")
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        # 去除列名前后空格，统一转小写，防止 KeyError
        df.columns = [str(c).strip().lower() for c in df.columns]
        return df
    except Exception:
        return None

def parse_all_stats(s):
    """安全解析 all_stats 字段，仅用于内部对比，不再展示具体值"""
    if pd.isna(s) or s is None:
        return 0.0
    s = str(s).strip()
    if s.startswith('[') and s.endswith(']'):
        s = s[1:-1]
    try:
        return float(s)
    except Exception:
        return 0.0

# ── 信号覆盖检查 ──────────────────────────────────────
def check_signal_coverage(signal_df):
    if signal_df is None or signal_df.empty:
        return "❌", None, None, None

    if 'step' not in signal_df.columns:
        return "❌", None, None, None

    signal_df['step'] = pd.to_numeric(signal_df['step'], errors='coerce').fillna(-1)
    max_step = signal_df['step'].max()
    latest = signal_df[signal_df['step'] == max_step].copy()

    if latest.empty:
        return "❌", None, None, None

    if 'store_time' not in latest.columns:
        return "❌", max_step, None, None

    latest['store_time_str'] = latest['store_time'].astype(str)
    latest_store_time = latest['store_time_str'].max()

    latest['variety'] = latest['instrument'].apply(extract_variety)
    latest['exchange'] = latest['variety'].apply(lookup_exchange)

    try:
        t = datetime.datetime.strptime(latest_store_time.split('.')[0], "%H:%M:%S").time()
    except Exception:
        t = datetime.datetime.now().time()

    # 夜盘/日盘预期交易所逻辑
    if t >= datetime.time(21, 0) or t <= datetime.time(2, 30):
        if t >= datetime.time(23, 0) or t <= datetime.time(2, 30):
            expected = {"SHFE"}
        else:
            expected = {"SHFE", "DCE", "CZCE"}
    else:
        expected = {"SHFE", "DCE", "CZCE", "CFFEX"}

    actual = set(latest['exchange'].unique())

    if not actual:
        return "❌", max_step, latest_store_time, None

    if expected.issubset(actual):
        status = "✅"
    elif actual & expected:
        status = "⚠️"
    else:
        status = "❌"

    return status, max_step, latest_store_time, latest

# ── 仓位文件查找 ──────────────────────────────────────
def find_position_file(position_path, store_time_str):
    if not os.path.exists(position_path):
        return None, None
    try:
        store_time = datetime.datetime.strptime(store_time_str.split('.')[0], "%H:%M:%S").time()
    except Exception:
        return None, None

    store_sec = store_time.hour * 3600 + store_time.minute * 60 + store_time.second
    best_file = None
    best_sec = None

    for fname in os.listdir(position_path):
        m = re.match(r'position_data_(\d{8})_(\d{8})_(\d{2}:\d{2}:\d{2})\.csv', fname)
        if not m:
            continue
        time_str = m.group(3)
        try:
            file_time = datetime.datetime.strptime(time_str, "%H:%M:%S").time()
        except Exception:
            continue
        file_sec = file_time.hour * 3600 + file_time.minute * 60 + file_time.second

        diff = file_sec - store_sec
        # 处理跨日时间差
        if diff < -43200:
            diff += 86400
        elif diff > 43200:
            diff -= 86400

        if 0 <= diff <= 30:
            if best_sec is None or file_sec < best_sec:
                best_file = fname
                best_sec = file_sec

    if best_file:
        return best_file, best_sec
    return None, None

# ── 仓位汇总（仅返回是否有差异，不展示具体数值） ────────
def load_and_aggregate_position(position_path, fname):
    path = os.path.join(position_path, fname)
    try:
        df = pd.read_csv(path)
    except Exception:
        return {}

    df.columns = [str(c).strip().lower() for c in df.columns]

    if 'instrument_id' not in df.columns or 'pos_type' not in df.columns or 'position' not in df.columns:
        return {}

    df['position'] = pd.to_numeric(df['position'], errors='coerce').fillna(0)

    long_pos = df[df['pos_type'] == 'LONG'].groupby('instrument_id')['position'].sum()
    short_pos = df[df['pos_type'] == 'SHORT'].groupby('instrument_id')['position'].sum()

    all_inst = set(long_pos.index) | set(short_pos.index)
    result = {}
    for inst in all_inst:
        l = long_pos.get(inst, 0)
        s = short_pos.get(inst, 0)
        result[inst] = l - s
    return result

# ── 对比（仅返回不一致的合约列表） ──────────────────────
def compare_signal_position(signal_df, position_dict):
    if signal_df is None or signal_df.empty or 'all_stats' not in signal_df.columns:
        return False, []

    mismatches = []
    for _, row in signal_df.iterrows():
        inst = row.get('instrument', '')
        if not inst:
            continue
        target = parse_all_stats(row.get('all_stats', 0.0))
        actual = position_dict.get(inst, 0)
        if abs(target - actual) > 1e-6:
            mismatches.append(inst)

    return len(mismatches) == 0, mismatches

# ── 页面渲染 ──────────────────────────────────────────
def main():
    st.set_page_config(page_title="交易信号与仓位检查", layout="wide")
    st.title("📊 交易信号与仓位检查")

    trade_date, _ = get_date_from_calendar()
    st.caption(f"交易日：{trade_date}")

    summary_rows = []
    detail_rows = []  # 每个账户一行
    alert_messages = []

    for cfg in ACCOUNT_CONFIGS:
        account = cfg['account']
        broker = cfg['broker']
        market = cfg['market']
        signal_dir = cfg.get('signal_dir')
        position_path = cfg['position_path']

        # 1. 加载信号文件
        signal_df = load_signal_file(market, signal_dir, trade_date)

        # 2. 信号覆盖检查
        signal_status, max_step, store_time, latest_signals = check_signal_coverage(signal_df)

        # 3. 查找对应的仓位文件
        position_file = None
        position_time = None
        position_dict = {}
        if store_time:
            position_file, _ = find_position_file(position_path, store_time)
            if position_file:
                m = re.search(r'(\d{2}:\d{2}:\d{2})', position_file)
                position_time = m.group(1) if m else None
                position_dict = load_and_aggregate_position(position_path, position_file)

        # 4. 仓位与信号对比
        position_status = "❌"
        mismatched_contracts = []
        if latest_signals is not None and not latest_signals.empty and position_file:
            matched, mismatches = compare_signal_position(latest_signals, position_dict)
            position_status = "✅" if matched else "❌"
            mismatched_contracts = mismatches

        # 5. 获取涉及到的交易所
        exchange_set = set()
        if latest_signals is not None and not latest_signals.empty:
            exchange_set = set(latest_signals['exchange'].unique())
        exchange_str = ", ".join(sorted(exchange_set)) if exchange_set else "无"

        # 6. 写入 Summary 行（保持原有逻辑）
        summary_rows.append({
            "account": account,
            "brokers": broker,
            "signal": signal_status,
            "position": position_status,
            "step": max_step,
            "store_time": store_time,
            "position_time": position_time,
        })

        # 7. 写入 Detail 行（每个账户一行）
        # 把不一致的合约拼接成字符串
        if mismatched_contracts:
            contracts_str = ", ".join(mismatched_contracts)
        elif position_file is None:
            contracts_str = "未找到仓位文件"
        else:
            contracts_str = "-"

        detail_rows.append({
            "account": account,
            "broker": broker,
            "exchange": exchange_str,
            "signal": signal_status,
            "position": position_status,
            "step": max_step if max_step is not None else "-",
            "store_time": store_time if store_time else "-",
            "position_time": position_time if position_time else "无",
            "contracts": contracts_str,
        })

        # 8. 收集异常通知
        if signal_status != "✅" or position_status != "✅":
            alert_messages.append(f"账户 {account} ({broker}): 信号={signal_status}, 仓位={position_status}")
            if mismatched_contracts:
                alert_messages.append(f"  不一致合约: {', '.join(mismatched_contracts)}")
            if position_file is None and store_time:
                alert_messages.append(f"  30秒内未找到仓位文件更新")

    # ── 渲染 Summary 表 ──
    st.subheader("Summary 总览")
    if summary_rows:
        summary_df = pd.DataFrame(summary_rows)
        summary_df = summary_df.rename(columns={
            "account": "Account", "brokers": "Brokers",
            "signal": "Signal(信号)", "position": "Position(仓位)",
            "step": "Step", "store_time": "Signal Time", "position_time": "Position Time"
        })
        st.dataframe(summary_df, use_container_width=True)
    else:
        st.info("暂无 Summary 数据")

    # ── 渲染 Detail 表 ──
    st.subheader("Detail 明细")
    if detail_rows:
        detail_df = pd.DataFrame(detail_rows)
        # 重命名列名，保持与需求一致
        detail_df = detail_df.rename(columns={
            "account": "Account",
            "broker": "Broker",
            "exchange": "交易所",
            "signal": "信号",
            "position": "仓位",
            "step": "Step",
            "store_time": "Signal Time",
            "position_time": "Position Time",
            "contracts": "异常合约"
        })
        # 确保列顺序
        cols = ["Account", "Broker", "交易所", "信号", "仓位", "Step", "Signal Time", "Position Time", "异常合约"]
        detail_df = detail_df[[c for c in cols if c in detail_df.columns]]
        st.dataframe(detail_df, use_container_width=True)
    else:
        st.info("暂无 Detail 数据")

    # ── 异常通知 ──
    st.markdown("---")
    st.subheader("🚨 异常通知")
    if alert_messages:
        for msg in alert_messages:
            st.error(msg)
    else:
        st.success("所有账户信号覆盖和仓位对比均正常")

if __name__ == "__main__":
    main()
    time.sleep(REFRESH_INTERVAL_SECONDS)
    st.rerun()