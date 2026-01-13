import pandas as pd 
import numpy as np 
import os 
import time
import streamlit as st

from datetime import datetime


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
    
    while True:
        if os.path.exists(file_path):
            try:
                df = pd.read_csv(file_path, usecols=all_cols)
                df = df[all_cols]
                
                steps = df['step'].unique()
                steps = sorted(steps)
                
                select_steps = steps[-n_step:]
                
                select_df = df[ df['step'].isin(select_steps)]
                
                select_df = select_df.sort_values(by=["instrument","step"], ascending=False).reset_index(drop=True)
                
                select_df = select_df.style.map(red_cells, subset=["cnif_melt_position_diff"])
                
                with placeholder.container():
                    
                    st.markdown(
                        """
                        <div style="
                            text-align: center;
                            font-weight: bold;
                            font-size: 32px;
                        ">
                            cnif position update monitor
                        </div>
                        """,
                        unsafe_allow_html=True
                        
                    )
                    
                    st.dataframe(select_df, width='stretch')
                    
            except Exception as e:
                placeholder.error(f"Read Error: {e}")
                
        else:
            placeholder.warning("File not Found!")
            
        time.sleep(1)
        
if __name__ == '__main__':
    
    date = datetime.now().date()
    date_int = int(date.strftime("%Y%m%d"))

    file_path = f"/cpfs/prod/check/{date_int}/merged_futures_with_diff.csv"
    all_cols = ["trade_date","step","update_time","instrument",
                "cnif_melt_position","cnif_melt_position_diff"]
    
    dashboard(
        file_path=file_path,
        all_cols=all_cols,
        n_step=2
    )