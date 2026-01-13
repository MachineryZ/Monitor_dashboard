import pandas as pd 
import numpy as np 
import os 
import time

import datetime

def check_intervals(df, variety_col, time_col):
    
    df = df.copy()
    
    df[time_col] = pd.to_datetime(df[time_col], format='%H:%M:%S', errors='coerce')
    
    latest_two = df.groupby(variety_col).tail(2).copy()
    latest_two['time_diff'] = latest_two.groupby(variety_col)[time_col].diff()
    threshold = datetime.timedelta(minutes=6)
    
    anomalies = latest_two[latest_two['time_diff'] > threshold]
    
    error_list = anomalies[variety_col].unique().tolist()
    
    return error_list