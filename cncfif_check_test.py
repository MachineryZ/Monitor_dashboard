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

# 账户配置（根据你提供的路径和账户名进行映射）
ACCOUNT_CONFIGS = [
    {"account": "ax1h_ya", "path": "/mnt/nfs_bohr_data1/china/trading_realdata/cncf_trade_data_ax1h_ya", "broker": "ya"},
    {"account": "bgt_ax1h", "path": "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_data_baguatian", "broker": "dz"},
    {"account": "shjq", "path": "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_data_shjq_zx", "broker": "zx"},
    {"account": "shph1h", "path": "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_data_shph1h_zx", "broker": "zx"},
    {"account": "zz1h", "path": "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_date", "broker": "dz"},
    {"account": "jz1h", "path": "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_jz1h", "broker": "dz"},
    {"account": "ly1h", "path": "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_ly1h", "broker": "dz"},
    {"account": "zz1h_zx", "path": "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_zz1h", "broker": "zx"},
    {"account": "zz1h_ya", "path": "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_zz1h_ya", "broker": "ya"},
    {"account": "jx1h_zx", "path": "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_jx1h_zx", "broker": "zx"},
]

# 交易所品种映射（硬编码）
EXCHANGE_MAP = {
    "SHFE": ["CU", "AL", "ZN", "PB", "NI", "SN", "AU", "AG", "RB", "HC", "SS", "BU", "RU", "SP", "FU", "WR", "AO", "BR"],
    "CZCE": ["SR", "CF", "CY", "TA", "MA", "FG", "RM", "OI", "ZC", "SM", "SF", "AP", "CJ", "UR", "SA", "PF", "PK", "SH"],
    "DCE": ["A", "B", "C", "CS", "M", "Y", "P", "V", "I", "J", "JM", "JD", "L", "PP", "EG", "EB", "RR", "PG", "LH", "BB", "FB", "OP"],
    "INE": ["SC", "LU", "NR", "BC", "EC"]
}

# 动态获取预期交易所（处理夜盘逻辑）
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
    """根据合约代码判断交易所"""
    inst_upper = str(instrument).upper()
    for exch, codes in EXCHANGE_MAP.items():
        for code in codes:
            if inst_upper.startswith(code):
                return exch
    return "UNKNOWN"

# ─────────────────────────────────────────────
# 2. 数据加载与处理
# ─────────────────────────────────────────────

def load_signals(account_path, trading_day):
    """加载信号数据"""
    file_path = os.path.join(account_path, f"{trading_day}.csv")
    if not os.path.exists(file_path):
        return None
    try:
        df = pd.read_csv(file_path)
        if df.empty:
            return None
        # 解析时间
        df['store_time_parsed'] = pd.to_datetime(df['store_time'], format='%H:%M:%S.%f', errors='coerce')
        # 解析目标仓位
        df['target_pos'] = df['all_stats'].apply(lambda x: float(str(x).strip('[]')) if pd.notna(x) else 0.0)
        # 映射交易所
        df['exchange'] = df['instrument'].apply(get_exchange)
        return df
    except Exception as e:
        return None

def load_positions(account_path, trading_day, store_time_str):
    """根据信号的 store_time，寻找之后30秒内的最新仓位文件"""
    if not store_time_str:
        return None, None
    
    try:
        target_time = pd.to_datetime(store_time_str, format='%H:%M:%S.%f').time()
        target_dt = datetime.datetime.combine(datetime.date.today(), target_time)
        max_wait_time = target_dt + timedelta(seconds=30)
    except:
        return None, None

    best_file = None
    best_time = None
    min_diff = timedelta.max

    # 遍历目录下的仓位文件
    for f in os.listdir(account_path):
        if not f.startswith(f"position_data_{trading_day}") or not f.endswith(".csv"):
            continue
        
        # 解析文件名中的时间 HH:MM:SS
        match = re.search(r'_(\d{2}:\d{2}:\d{2})\.csv$', f)
        if not match:
            continue
        
        file_time_str = match.group(1)
        try:
            file_time = pd.to_datetime(file_time_str, format='%H:%M:%S').time()
            file_dt = datetime.datetime.combine(datetime.date.today(), file_time)
        except:
            continue

        # 寻找 store_time 之后 30s 内的文件
        if target_dt <= file_dt <= max_wait_time:
            diff = file_dt - target_dt
            if diff < min_diff:
                min_diff = diff
                best_file = f
                best_time = file_time_str

    if best_file:
        try:
            df = pd.read_csv(os.path.join(account_path, best_file))
            if df.empty:
                return None, best_time
            # 计算净仓位
            df['net_pos'] = df.apply(lambda row: row['position'] if row['pos_type'] == 'LONG' else -row['position'], axis=1)
            # 按合约聚合
            df_agg = df.groupby('instrument_id')['net_pos'].sum().reset_index()
            df_agg['exchange'] = df_agg['instrument_id'].apply(get_exchange)
            return df_agg, best_time
        except:
            return None, best_time

    return None, None

def compare_signal_and_position(sig_df, pos_df, exchange):
    """对比信号和仓位，返回不匹配的合约列表"""
    if sig_df is None or pos_df is None:
        return ["数据缺失"]

    # 提取该交易所的信号
    sig_exch = sig_df[sig_df['exchange'] == exchange]
    sig_dict = dict(zip(sig_exch['instrument'], sig_exch['target_pos']))

    # 提取该交易所的仓位
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
    """渲染状态图标"""
    if status == "PASS":
        return "✅"
    elif status == "WARN":
        return "⚠️"
    else:
        return "❌"

def main():
    st.set_page_config(page_title="交易监控面板", layout="wide")
    st.title("📊 交易监控面板 - 实时状态")
    
    # 获取当前交易日
    trading_day = datetime.datetime.now().strftime("%Y%m%d")
    expected_exchanges = get_expected_exchanges()
    
    st.sidebar.header("监控设置")
    st.sidebar.write(f"当前交易日: {trading_day}")
    st.sidebar.write(f"预期活跃交易所: {', '.join(expected_exchanges) if expected_exchanges else '非交易时段'}")

    summary_data = []
    detail_data = []

    # 遍历所有账户
    for cfg in ACCOUNT_CONFIGS:
        account = cfg["account"]
        path = cfg["path"]
        broker = cfg["broker"]

        # 加载信号
        sig_df = load_signals(path, trading_day)
        
        # 初始化账户级别的状态
        account_sig_status = "PASS"
        account_pos_status = "PASS"
        account_step = "-"
        account_store_time = "-"
        account_pos_time = "-"

        if sig_df is None or sig_df.empty:
            account_sig_status = "FAIL"
            summary_data.append({
                "account": account, "broker": broker, "signal": render_status_icon("FAIL"),
                "position": render_status_icon("FAIL"), "step": "-", "store_time": "-", "position_time": "-"
            })
            continue

        # 提取最新的 step 和 store_time
        latest_sig = sig_df.sort_values('store_time_parsed').iloc[-1]
        account_step = latest_sig['step']
        account_store_time = latest_sig['store_time']

        # 判断信号状态
        active_exchanges = [e for e in expected_exchanges if e in sig_df['exchange'].values]
        if len(active_exchanges) == len(expected_exchanges) and len(expected_exchanges) > 0:
            account_sig_status = "PASS"
        elif len(active_exchanges) > 0:
            account_sig_status = "WARN"
        else:
            account_sig_status = "FAIL"

        # 加载对应的仓位文件
        pos_df, pos_time = load_positions(path, trading_day, account_store_time)
        account_pos_time = pos_time if pos_time else "-"

        # 对比每个交易所
        has_pos_mismatch = False
        for exch in expected_exchanges:
            mismatches = compare_signal_and_position(sig_df, pos_df, exch)
            
            # 判断仓位状态
            if pos_df is None:
                pos_status = "FAIL"
                has_pos_mismatch = True
            elif len(mismatches) > 0:
                pos_status = "FAIL"
                has_pos_mismatch = True
            else:
                pos_status = "PASS"

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
                "合约名": ", ".join(mismatches) if mismatches else ""
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
        # 使用颜色标记
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
        # 只展示有问题的账户，或者全部展示
        # 这里为了简洁，按账户分组展示
        for account in detail_df['account'].unique():
            acc_df = detail_df[detail_df['account'] == account]
            broker = acc_df.iloc[0]['broker']
            # 判断该账户是否有异常
            has_error = any(acc_df['仓位'].apply(lambda x: x == "❌")) or any(acc_df['信号'].apply(lambda x: x == "❌"))
            title = f"{'🔴' if has_error else '🟢'} [{account}] | {broker}"
            
            with st.expander(title, expanded=has_error):
                display_cols = ["交易所", "信号", "仓位", "step", "store_time", "position_time", "合约名"]
                st.dataframe(acc_df[display_cols], width="stretch", hide_index=True)
    else:
        st.info("暂无明细数据")

if __name__ == "__main__":
    main()