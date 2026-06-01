import os
import sys
import copy
import time
import bisect
import requests
import json
import datetime
import pandas

import streamlit as st
import numpy as np

calendar_path = "/cpfs/intrastats/calendar"

def get_date_from_calendar():
    date = datetime.datetime.now().date()
    date_int = int(date.strftime("%Y%m%d"))
    date_list = np.loadtxt(calendar_path, dtype=np.int64, ndmin=1)
    pos = np.searchsorted(date_list, date_int, side="right")
    next_trade_day = date_list[pos]
    return date_int, next_trade_day


def product_low_limit_red_cells(val):
    if float(val) < 0.8:
        return 'background-color: #ff4b4b; color: white'
    return ''

def instrument_margin_uplimit_red_cells(val):
    if float(val) > 0.25:
        return 'background-color: #ff4b4b; color: white'
    return ''

def yellow_cells(val):
    if abs(val) > 1e-6:
        return 'background-color: #ffd700; color: black'
    return ''


def send_alert(message):
    webhook_url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=1f5ccb85-9f37-46a5-b5a7-d5e0a7cc9b3c"
    msg = {
        "msgtype": "text",
        "text": {"content": message}
    }
    response = requests.post(webhook_url, data=json.dumps(msg))
    return

def calculate_product(
    path = None,
    broker = None,
    futures_type = "commodity",
):
    current_date, _ = get_date_from_calendar()
    current_hour = datetime.datetime.now().hour
    current_minute = datetime.datetime.now().minute
    
    # # Opening check logic
    # if futures_type == "commodity":
    #     if current_hour >= 0 and current_hour <= 9:
    #         continue
         
    ai_df = pandas.read_csv(os.path.join(path, f"account_info_{current_date}.csv"))
    pd_df = pandas.read_csv(os.path.join(path, f"position_data_{current_date}.csv"))
    if futures_type == "commodity":
        sd_df = pandas.read_csv(os.path.join("/cpfs/rawdata/cncf_all_nedd_before_open", "ins_static_info.csv"))
        future_df = pandas.read_csv(f"/mnt/nfs_bohr_data1/china/trading_realdata/partial_market_data_realtime/commodity/{current_date}.csv")
        margin_df = pandas.read_csv(f"/cpfs/rawdata/cncf_all_nedd_before_open/margin_uplimit.csv")
    elif futures_type == "futures":
        sd_df = pandas.read_csv(os.path.join("/cpfs/rawdata/cnif_all_need_before_open", "ins_static_info.csv"))
        future_df = pandas.read_csv(f"/mnt/nfs_bohr_data1/china/trading_realdata/partial_market_data_realtime/futures/{current_date}.csv")
        if path == "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_jz1h":
            margin_df = pandas.read_csv(f"/cpfs/rawdata/cnif_all_need_before_open/margin_uplimit_jz1h_{current_date}.csv")
        if path == "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_ly1h":
            margin_df = pandas.read_csv(f"/cpfs/rawdata/cnif_all_need_before_open/margin_uplimit_ly1h_{current_date}.csv")
        if path == "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_zz1h":
            margin_df = pandas.read_csv(f"/cpfs/rawdata/cnif_all_need_before_open/margin_uplimit_zz1h_{current_date}.csv")
    data = pandas.DataFrame()
    data["futures_type"] = pd_df["instrument_id"].apply(lambda x: "cncf" if futures_type == "commodity" else "cnif")
    data = data.iloc[0]
    data["product_name"] = ""
    data["broker"] = ""
    data["balance"] = ai_df["balance"].iloc[0]
    data["pre_balance"] = ai_df["pre_balance"].iloc[0]
    data["market_value"] = 0
    for ii in pd_df["instrument_id"].unique().tolist():
        long_position = pd_df.query(f"instrument_id == '{ii}' and pos_type == 'LONG'")["position"].iloc[0]
        short_position = pd_df.query(f"instrument_id == '{ii}' and pos_type == 'SHORT'")["position"].iloc[0]
        data["market_value"] += (long_position + short_position) * (future_df[future_df["instrument"] == ii]["ask_price1"].iloc[0] + future_df[future_df["instrument"] == ii]["bid_price1"].iloc[0]) / 2 * sd_df[sd_df["instrument"] == ii]["multiplier"].iloc[0]
    data["product_low_limit"] = data["market_value"] / data["balance"]
    data["deposit_withdraw"] = ai_df["deposit"].iloc[0] - ai_df["withdraw"].iloc[0]
    data["cost"] = ai_df["fee"].iloc[0]
    data["abs_return"] = (pd_df["position_profit"] + pd_df["close_profit"]).sum()
    pnl = round(float(data["abs_return"] - data["cost"]) / data["balance"] * 100, 3)
    data["pnl"] = str(pnl) + '%'
    data["instrument_margin_uplimit"] = 0.0
    for ii in pd_df["instrument_id"].unique().tolist():
        price = (future_df[future_df["instrument"] == ii]["ask_price1"].iloc[0] + future_df[future_df["instrument"] == ii]["bid_price1"].iloc[0]) / 2
        position = pd_df[pd_df["instrument_id"] == ii]["position"].iloc[0]
        margin_ratio = margin_df[margin_df["instrument"] == ii]["margin_ratio"].iloc[0]
        multiplier = sd_df[sd_df["instrument"] == ii]["multiplier"].iloc[0]
        data["instrument_margin_uplimit"] = max(price * position * margin_ratio * multiplier, data["instrument_margin_uplimit"])
    data["instrument_margin_uplimit"] = data["instrument_margin_uplimit"] /data["balance"]
    data["time"] =  datetime.datetime.now().strftime("%H:%M:%S")
    
    # 字段说明
    # user_id 用户编码
    # investor_id 投资者代码
    # security_id 合约代码
    # instrument_id 合约代码
    # pos_direction 持仓多空方向
    # hedge_flag 投机套保标志
    # yd_position 昨日仓位
    # yd_position_frozen 昨日仓位冻结
    # today_position 今仓
    # today_position_frozen 今日仓位冻结
    # position 总仓位
    # position_frozen 总仓位冻结
    # yd_position_cost 昨仓持仓成本 不带合约乘数
    # today_position_cost 今仓持仓成本 不带合约乘数
    # is_pos_last
    # use_margin 占用的保证金
    # fee 手续费
    # close_profit 平仓盈亏
    # position_profit 持仓盈亏
    # pre_settlement_price 上次结算价
    # trade_date 交易日
    # update_time 更新时间
    # trade_token 策略端报单引用
    # yd_position_available 
    # total_position_available
    # open_active_cnt
    # direction
    # position_avg_price
    return data

def dashboard(
):
    st.set_page_config(
        page_title="dashboard",
        layout="wide",
    )
    placeholder = st.empty()
    while True:
        try: 
            cols = ["futures_type", "product_name", "broker", "balance", "pre_balance", "market_value", "cost", "abs_return", "pnl", "instrument_margin_uplimit", "product_low_limit", "deposit_withdraw", "time",]
            df = pandas.DataFrame(columns=cols)
            
            # baguatian
            baguatian_path = "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_data_baguatian"
            data = calculate_product(baguatian_path, "Dongzheng", "commodity")
            data["broker"] = "Dongzheng"
            data["product_name"] = "Baguatian (AnXin 1Hao)"
            df.loc[0] = data
            
            # # ShanHai JinQu
            shjq_zx_path = "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_data_shjq_zx"
            data = calculate_product(shjq_zx_path, "ZhongXin", "commodity")
            data["broker"] = "Zhongxin"
            data["product_name"] = "Shanhai Jinqu"
            df.loc[len(df)] = data
            
            # ShanHai 1 Hao
            shph1h_zx_path = "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_data_shph1h_zx"
            data = calculate_product(shph1h_zx_path, "ZhongXin", "commodity")
            data["broker"] = "Zhongxin"
            data["product_name"] = "Shanhai Pingheng 1Hao"
            df.loc[len(df)] = data
            
            # Index Enhancement
            indexenhancement_1hao_path = "/mnt/nfs_bohr_data1/china/trading_realdata/commodity_trade_date"
            data = calculate_product(indexenhancement_1hao_path, "ZhongXin", "commodity")
            data["broker"] = "Zhongxin"
            data["product_name"] = "Zhizeng 1Hao"
            df.loc[len(df)] = data
            
            jz1h_path = "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_jz1h"
            data = calculate_product(jz1h_path, "Unkonwn", "futures")
            data["broker"] = "Dongzheng"
            data["product_name"] = "jz1h"
            df.loc[len(df)] = data
            
            jz1h_path = "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_ly1h"
            data = calculate_product(jz1h_path, "Unkonwn", "futures")
            data["broker"] = "Dongzheng"
            data["product_name"] = "ly1h"
            df.loc[len(df)] = data
            
            jz1h_path = "/mnt/nfs_bohr_data1/china/trading_realdata/cnif_trade_data_zz1h"
            data = calculate_product(jz1h_path, "Unkonwn", "futures")
            data["broker"] = "Zhongxin"
            data["product_name"] = "zz1h"
            df.loc[len(df)] = data

            if data["product_low_limit"] < 0.8:
                send_alert(f"product_low_limit is less than 0.8 in broker = {data['broker']} and product_name = {data['product_name'] } at time = {data['time']}")
            if data["instrument_margin_uplimit"] > 0.25:
                send_alert(f"product_low_limit is larger than 0.8 in broker = {data['broker']} and product_name = {data['product_name'] } at time = {data['time']}")
            
            
            money_cols = ["balance", "pre_balance", "market_value", "deposit_withdraw", "cost", "abs_return"]
            for cols in money_cols:
                df[cols] = df[cols].fillna(0).round(0).astype(int)
                df[cols] = df[cols].apply(lambda x: f"{x:,}")
            
            df["instrument_margin_uplimit"] = df["instrument_margin_uplimit"].apply(lambda x: f"{x:.4f}")
            df["product_low_limit"] = df["product_low_limit"].apply(lambda x: f"{x:.4f}")
            
            df = df.style.map(product_low_limit_red_cells, subset=["product_low_limit"])
            with placeholder.container():
                st.markdown(
                    """
                    <div style="
                        text-align: center;
                        cont-weight: bold;
                        font-size: 32px;
                    ">
                        cnif update overall monitor
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                st.dataframe(df, width="stretch")
        except Exception as e:
            placeholder.warning(f"Error! {e}")
        
        time.sleep(1)


if __name__ == "__main__":
    date = datetime.datetime.now().date()
    date_int = int(date.strftime("%Y%m%d"))
    
    current_time = datetime.datetime.now().time()
    
    today, next_day = get_date_from_calendar()
        
    dashboard()