import pandas as pd 
import numpy as np 
import os, sys
import time
import streamlit as st

import datetime
import bisect

calendar_path = "/cpfs/intrastats/calendar"

def get_date_from_calendar():
    
    date = datetime.datetime.now().date()
    date_int = int(date.strftime("%Y%m%d"))
    
    date_list = np.loadtxt(calendar_path, dtype=np.int64, ndmin=1)

    pos = np.searchsorted(date_list, date_int, side="right")
    
    
    next_trade_day = date_list[pos]
    
    return date_int, next_trade_day

def red_cells(val):
    if abs(val) > 1e-6:
        return 'background-color: #ff4b4b; color: white'
    return ''

def yellow_cells(val):
    if abs(val) > 1e-6:
        return 'background-color: #ffd700; color: black'
    return ''
    
def dashboard(
    file_path,
    all_cols,
    n_step,
):
    st.set_page_config(
    page_title = "dashboard",
    layout = "wide"
    )
    placeholder = st.empty()
    
    info_df = pd.read_csv("./cf_info.csv")
    
    final_cols_to_display = ["trade_date","step","update_time",
                            "exchange", "code", "symbol","main_contract",
                            "cncf_melt_position","cncf_melt_position_diff",
                            "signal_melt","signal_melt_diff",
                            "signal_5m","signal_5m_diff",
                            "signal_30m","signal_30m_diff",
                            "signal_1d","signal_1d_diff",
                            "night_trading_hours"]
    
    while True:
        if os.path.exists(file_path):
            try:
                df = pd.read_csv(file_path, usecols=all_cols)
                df = df[all_cols]
                
                steps = df['step'].unique()
                steps = sorted(steps)
                
                select_steps = steps[-n_step:]
                
                select_df = df[ df['step'].isin(select_steps)].copy()
                
                select_df['code'] = select_df['instrument'].str.extract(r'(^[a-zA-Z]+)')
                
                select_df = select_df.merge(info_df, how='left', on = 'code')
                
                select_df = select_df.sort_values(by=["instrument", "step"], ascending=False).reset_index(drop=True)
                select_df = select_df.rename(columns={"instrument": "main_contract"})
                
                select_df = select_df[final_cols_to_display]

                select_df = select_df.style.map(red_cells, subset=["cncf_melt_position_diff"]).map(yellow_cells, subset=["signal_5m_diff","signal_30m_diff","signal_1d_diff"])
                
                with placeholder.container():
                    
                    st.markdown(
                        """
                        <div style="
                            text-align: center;
                            font-weight: bold;
                            font-size: 32px;
                        ">
                            cncf update monitor
                        </div>
                        """,
                        unsafe_allow_html=True
                        
                    )
                    
                    st.dataframe(select_df, width='stretch', height=5000)
                    
            except Exception as e:
                placeholder.error(f"Read Error: {e}")
                
        else:
            placeholder.warning("File not Found!")
            
        time.sleep(1)
        
if __name__ == '__main__':
    
    date = datetime.datetime.now().date()
    date_int = int(date.strftime("%Y%m%d"))
    
    current_time = datetime.datetime.now().time()
    close_time = datetime.time(15, 30)
    
    today, next_day = get_date_from_calendar()
    
    if current_time > close_time:
        file_path = f"/cpfs/prod/check/{next_day}/merged_commodity.csv"
    else:
        file_path = f"/cpfs/prod/check/{today}/merged_commodity.csv"
    
    all_cols = ["trade_date","step","update_time","instrument",
                "cncf_melt_position","cncf_melt_position_diff",
                "signal_melt","signal_melt_diff",
                "signal_5m","signal_5m_diff",
                "signal_30m","signal_30m_diff",
                "signal_1d","signal_1d_diff"]
    
    dashboard(
        file_path=file_path,
        all_cols=all_cols,
        n_step=2
    )
    