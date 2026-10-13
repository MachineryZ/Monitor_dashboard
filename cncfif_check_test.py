import os
import datetime
import re
import pandas as pd
import numpy as np
import streamlit as st
from datetime import timedelta

# ─────────────────────────────────────────────
# 1. 配置与常量
# ─────────────────────────────────────────────

# 账户配置（完全匹配你提供的信号目录和仓位目录）
ACCOUNT_CONFIGS = [
    # CNCF (商品期货)
    {"account": "ax1h_ya", "broker": "ya", "market": "cncf", "signal_dir": "cncf_melt_ax1h_ya_bohr", "position_dir": "/mnt/nfs_bohr_data1/china/trading_realdata/cncf_trade_data_ax1h_ya"},
    {"account": "bgt_ax1h", "broker": "dz", "market": "cncf", "signal_dir": "cncf_melt_bgt_dz_bohr", "position_dir": "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_data_baguatian"},
    {"account": "shjq", "broker": "zx", "market": "cncf", "signal_dir": "cncf_melt_shjq_zx_bohr", "position_dir": "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_data_shjq_zx"},
    {"account": "shph1h", "broker": "zx", "market": "cncf", "signal_dir": "cncf_melt_shph1h_zx_bohr", "position_dir": "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_data_shph1h_zx"},
    {"account": "zz1h", "broker": "dz", "market": "cncf", "signal_dir": "cncf_melt_zhizeng_dz_bohr", "position_dir": "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_date"},
    # CNIF (股指期货)
    {"account": "jz1h", "broker": "dz", "market": "cnif", "signal_dir": "cnif_short_jz1h_dz_dashboard_bohr", "position_dir": "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_jz1h"},
    {"account": "ly1h", "broker": "dz", "market": "cnif", "signal_dir": "cnif_position_melt_ly1h_dz_dashboard_bohr", "position_dir": "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_ly1h"},
    {"account": "zz1h_zx", "broker": "zx", "market": "cnif", "signal_dir": "cnif_short_zz1h_zx_dashboard_bohr", "position_dir": "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_zz1h"},
    {"account": "zz1h_ya", "broker": "ya", "market": "cnif", "signal_dir": "cnif_short_zz1h_zx_dashboard_bohr", "position_dir": "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_zz1h_ya"},
    {"account": "jx1h_zx", "broker": "zx", "market": "cnif", "signal_dir": "cnif_melt_ls_jx1h_zx_dashboard_bohr", "position_dir": "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_jx1h_zx"},
]

# 交易所品种映射（硬编码）
EXCHANGE_MAP = {
    "SHFE": ["CU", "AL", "ZN", "PB", "NI", "SN", "AU", "AG", "RB", "HC", "SS", "BU", "RU", "SP", "FU", "WR", "AO", "BR"],
    "CZCE": ["SR", "CF", "CY", "TA", "MA", "FG", "RM", "OI", "ZC", "SM", "SF", "AP", "CJ", "UR", "SA", "PF", "PK", "SH"],
    "DCE": ["A", "B", "C", "CS", "M", "Y", "P", "V", "I", "J", "JM", "JD", "L", "PP", "EG", "EB", "RR", "PG", "LH", "BB", "FB", "OP"],
    "INE": ["SC", "LU", "NR", "BC", "EC"]
}

def get_expected_exchanges():
    now = datetime.datetime.now().time()
    # 夜盘 21:00 - 02:30
    if datetime.time(21, 0) <= now or now <= datetime.time(2, 30):
        if now >= datetime.time(23, 0) or now <= datetime.time(2, 30):
            return ["SHFE"]  # 11点后只有上期所
        return ["SHFE", "CZCE", "DCE"]  # 夜盘三个所
    # 日盘 09:00 - 15:00
    elif datetime.time(9, 0) <= now <= datetime.time(15, 0):
        return ["SHFE", "CZCE", "DCE", "INE"]
    return []  # 非交易时段

def get_exchange(instrument):
    inst_upper = str(instrument).upper()
    for exch, codes in EXCHANGE_MAP.items():
        for code in codes:
            if inst_upper.startswith(code):
                return exch
    return "UNKNOWN"

def parse_stats(x):
    """安全解析 all_stats 字段，例如 '[0.0]' -> 0.0, '[-75.0]' -> -75.0"""
    try:
        return float(str(x).strip('[]'))
    except:
        return 0.0

# ─────────────────────────────────────────────
# 2. 数据加载与处理
# ─────────────────────────────────────────────

def load_signals(signal_dir, trading_day):
    """加载信号数据"""
    file_path = f"/cpfs/prod/prod_log/china_future/{signal_dir}/{trading_day}.csv"
    if not os.path.exists(file_path):
        return None, f"信号文件不存在: {file_path}"
    try:
        df = pd.read_csv(file_path)
        if df.empty:
            return None, f"信号文件为空: {file_path}"
        
        # 解析时间，处理可能缺失的情况
        df['store_time_parsed'] = pd.to_datetime(df['store_time'], format='%H:%M:%S.%f', errors='coerce')
        if df['store_time_parsed'].isna().all():
            return None, f"store_time 解析失败: {file_path}"
            
        df['target_pos'] = df['all_stats'].apply(parse_stats)
        df['exchange'] = df['instrument'].apply(get_exchange)
        return df, None
    except Exception as e:
        return None, f"读取信号文件异常: {str(e)}"

def load_positions(position_dir, trading_day, store_time_str):
    """根据信号的 store_time，寻找之后30秒内的最新仓位文件"""
    if not store_time_str or store_time_str == "-":
        return None, None, "无 store_time"
    
    try:
        target_time = pd.to_datetime(store_time_str, format='%H:%M:%S.%f').time()
    except:
        return None, None, "store_time 格式错误"

    # 使用 datetime 对象进行比较，处理跨日情况
    today = datetime.date.today()
    target_dt = datetime.datetime.combine(today, target_time)

    best_file = None
    best_time = None
    min_diff = timedelta.max

    if not os.path.exists(position_dir):
        return None, None, f"仓位目录不存在: {position_dir}"

    for f in os.listdir(position_dir):
        if not f.startswith(f"position_data_{trading_day}") or not f.endswith(".csv"):
            continue
        
        match = re.search(r'_(\d{2}:\d{2}:\d{2})\.csv$', f)
        if not match:
            continue
        
        file_time_str = match.group(1)
        try:
            file_time = pd.to_datetime(file_time_str, format='%H:%M:%S').time()
            file_dt = datetime.datetime.combine(today, file_time)
        except:
            continue

        # 处理跨日情况 (例如 store_time 是 23:59:59，file_time 是 00:00:10)
        if file_dt < target_dt - timedelta(hours=12):
            file_dt += timedelta(days=1)
        elif file_dt > target_dt + timedelta(hours=12):
            file_dt -= timedelta(days=1)

        # 寻找 store_time 之后 30s 内的文件
        if target_dt <= file_dt <= target_dt + timedelta(seconds=30):
            diff = file_dt - target_dt
            if diff < min_diff:
                min_diff = diff
                best_file = f
                best_time = file_time_str

    if best_file:
        try:
            df = pd.read_csv(os.path.join(position_dir, best_file))
            if df.empty:
                return None, best_time, "仓位文件为空"
            # 计算净仓位
            df['net_pos'] = df.apply(lambda row: row['position'] if row['pos_type'] == 'LONG' else -row['position'], axis=1)
            df_agg = df.groupby('instrument_id')['net_pos'].sum().reset_index()
            df_agg['exchange'] = df_agg['instrument_id'].apply(get_exchange)
            return df_agg, best_time, None
        except Exception as e:
            return None, best_time, f"解析仓位文件异常: {str(e)}"

    return None, None, "30秒内无仓位文件更新"

def compare_signal_and_position(sig_df, pos_df, exchange):
    """对比信号和仓位，返回不匹配的合约列表"""
    if sig_df is None:
        return ["信号数据缺失"]
    
    sig_exch = sig_df[sig_df['exchange'] == exchange]
    sig_dict = dict(zip(sig_exch['instrument'], sig_exch['target_pos']))

    if pos_df is None:
        return list(sig_dict.keys()) # 如果没有仓位数据，所有有信号的合约都不匹配

    pos_exch = pos_df[pos_df['exchange'] == exchange]
    pos_dict = dict(zip(pos_exch['instrument_id'], pos_exch['net_pos']))

    mismatches = []
    all_insts = set(sig_dict.keys()) | set(pos_dict.keys())

    for inst in all_insts:
        target = sig_dict.get(inst, 0)
        actual = pos_dict.get(inst, 0)
        if target != actual:
            mismatches.append(inst)

    return mismatches

# ─────────────────────────────────────────────
# 3. Dashboard 界面渲染
# ─────────────────────────────────────────────

def render_status_icon(status):
    if status == "PASS": return "✅"
    elif status == "WARN": return "⚠️"
    else: return "❌"

def main():
    st.set_page_config(page_title="交易监控面板", layout="wide")
    st.title("📊 交易监控面板 - 实时状态")
    
    # 侧边栏：日期选择器（方便测试，默认 2026-10-12）
    st.sidebar.header("监控设置")
    default_date = datetime.date(2026, 10, 12)
    selected_date = st.sidebar.date_input("选择交易日", default_date)
    trading_day = selected_date.strftime("%Y%m%d")
    
    expected_exchanges = get_expected_exchanges()
    st.sidebar.write(f"当前交易日: {trading_day}")
    st.sidebar.write(f"预期活跃交易所: {', '.join(expected_exchanges) if expected_exchanges else '非交易时段'}")

    summary_data = []
    detail_data = []

    for cfg in ACCOUNT_CONFIGS:
        account = cfg["account"]
        broker = cfg["broker"]
        signal_dir = cfg["signal_dir"]
        position_dir = cfg["position_dir"]

        # 1. 加载信号
        sig_df, sig_err = load_signals(signal_dir, trading_day)
        
        account_sig_status = "PASS"
        account_pos_status = "PASS"
        account_step = "-"
        account_store_time = "-"
        account_pos_time = "-"

        if sig_df is None or sig_err:
            account_sig_status = "FAIL"
            summary_data.append({
                "account": account, "broker": broker, "signal": render_status_icon("FAIL"),
                "position": render_status_icon("FAIL"), "step": "-", "store_time": sig_err, "position_time": "-"
            })
            continue

        # 提取最新的 step 和 store_time
        latest_sig = sig_df.sort_values('store_time_parsed').iloc[-1]
        account_step = latest_sig['step']
        account_store_time = latest_sig['store_time']

        # 判断信号状态
        active_exchanges = [e for e in expected_exchanges if e in sig_df['exchange'].values]
        if len(expected_exchanges) > 0:
            if len(active_exchanges) == len(expected_exchanges):
                account_sig_status = "PASS"
            elif len(active_exchanges) > 0:
                account_sig_status = "WARN"
            else:
                account_sig_status = "FAIL"
        else:
            account_sig_status = "PASS" # 非交易时段，不报错

        # 2. 加载仓位
        pos_df, pos_time, pos_err = load_positions(position_dir, trading_day, account_store_time)
        account_pos_time = pos_time if pos_time else "-"

        # 3. 对比每个交易所
        has_pos_mismatch = False
        for exch in expected_exchanges:
            mismatches = compare_signal_and_position(sig_df, pos_df, exch)
            
            if pos_df is None:
                pos_status = "FAIL"
                has_pos_mismatch = True
                mismatch_str = pos_err if pos_err else "无仓位数据"
            elif len(mismatches) > 0:
                pos_status = "FAIL"
                has_pos_mismatch = True
                mismatch_str = ", ".join(mismatches)
            else:
                pos_status = "PASS"
                mismatch_str = ""

            # 记录明细数据
            detail_data.append({
                "account": account,
                "broker": broker,
                "交易所": exch,
                "信号": render_status_icon(account_sig_status if exch in active_exchanges else "FAIL"),
                "仓位": render_status_icon(pos_status),
                "step": account_step,
                "store_time": account_store_time,
                "position_time": account_pos_time,
                "合约名": mismatch_str
            })

        if has_pos_mismatch:
            account_pos_status = "FAIL"

        # 记录总览数据
        summary_data.append({
            "account": account,
            "broker": broker,
            "signal": render_status_icon(account_sig_status),
            "position": render_status_icon(account_pos_status),
            "step": account_step,
            "store_time": account_store_time,
            "position_time": account_pos_time
        })

    # ── 渲染 Summary ──
    st.subheader("Summary 总览")
    if summary_data:
        summary_df = pd.DataFrame(summary_data)
        def highlight_status(val):
            if val == "✅": return "color: green; font-weight: bold; font-size: 20px;"
            elif val == "⚠️": return "color: orange; font-weight: bold; font-size: 20px;"
            elif val == "❌": return "color: red; font-weight: bold; font-size: 20px;"
            return ""
        
        styled_summary = summary_df.style.map(highlight_status, subset=["signal", "position"])
        st.dataframe(styled_summary, width="stretch", hide_index=True)
    else:
        st.info("暂无数据")

    # ── 渲染 Detail ──
    st.subheader("Detail 明细")
    if detail_data:
        detail_df = pd.DataFrame(detail_data)
        for account in detail_df['account'].unique():
            acc_df = detail_df[detail_df['account'] == account]
            broker = acc_df.iloc[0]['broker']
            has_error = any(acc_df['仓位'].apply(lambda x: x == "❌")) or any(acc_df['信号'].apply(lambda x: x == "❌"))
            title = f"{'🔴' if has_error else '🟢'} [{account}] | {broker}"
            
            with st.expander(title, expanded=has_error):
                display_cols = ["交易所", "信号", "仓位", "step", "store_time", "position_time", "合约名"]
                st.dataframe(acc_df[display_cols], width="stretch", hide_index=True)
    else:
        st.info("暂无明细数据")

if __name__ == "__main__":
    main()