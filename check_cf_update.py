import os 
import time
import datetime

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import numpy as np

CALENDAR_PATH = "/cpfs/intrastats/calendar"
CHECK_INTERVAL = 6 # minutes

TRADING_SESSIONS = [
    ("00:00", "02:30"),
    ("09:07", "10:15"),
    ("10:37", "11:30"),
    ("13:37", "15:00"),
    ("21:07", "23:59")
]
# 日盘的时间区间
DAY_SESSIONS = [
    ("00:00", "02:30"),
    ("09:07", "10:15"),
    ("10:37", "11:30"),
    ("13:37", "15:00"),
    ("21:07", "23:59")
]
# 夜盘的时间去区间
NIGHT_SESSIONS = [
    ("00:00", "02:30")
]

EMAIL_CONFIG = {
    "SMTP_SERVER": "smtp.exmail.qq.com",
    "SMTP_PORT": 465,
    "EMAIL_USER": "liujz@dunhefund.com",
    "EMAIL_PASS": "cYT6xks26ERPZbcf",
    "EMAIL_TO": [
        "yangjy@dunhefund.com",
        "jiangl@dunhefund.com",
        "zhoujg@dunhefund.com",
        "xuh@dunhefund.com"
    ]
}

def get_date_from_calendar():
    """
        从交易日历获取，今日日期，上个交易日的日期，下个交易日的日期
    """

    date = datetime.datetime.now().date()
    today = int(date.strftime("%Y%m%d"))
    
    date_list = np.loadtxt(CALENDAR_PATH, dtype=np.int64, ndmin=1)

    next_pos = np.searchsorted(date_list, today, side="right")
    next_trade_day = date_list[next_pos]
    
    prev_pos = np.searchsorted(date_list, today, side="left")
    prev_trade_day = date_list[prev_pos]
    
    return prev_trade_day, today,  next_trade_day

def is_in_time_window(time_windows):
    """
    检查当前时间是否处于目标时间区间内
    """
    now = datetime.datetime.now()
    current_time = now.time()
    for start, end in time_windows:
        start_time = datetime.datetime.strptime(start, "%H:%M").time()
        end_time = datetime.datetime.strptime(end, "%H:%M").time()
        
        if start_time <= current_time <= end_time:
            return True
    return False

def is_in_trading_hours():
    
    date_list = np.loadtxt(CALENDAR_PATH, dtype=np.int64, ndmin=1)
    date = datetime.datetime.now().date()
    date_int = int(date.strftime("%Y%m%d"))
    
    prev_today, today, next_day = get_date_from_calendar()
    
    # 如果时间处于日盘内，判断今日日期是否在交易日历中
    if is_in_time_window(DAY_SESSIONS):
        if today in date_list:
            return True
        else:
            return False
    # 如果时间处于夜盘内，判断昨天是否是上一个交易日
    elif is_in_time_window(NIGHT_SESSIONS):
        if (today - 1 == prev_today):
            return True
        else:
            return False
        
    else:
        return False

def prepare_html():

    html = f"{ datetime.datetime.now().strftime('%H:%M:%S')} 商品期货文件超过6min未更新!"
    
    return html

def send_email(subject, html_content,):
    """发送 HTML 邮件"""
    msg = MIMEMultipart()
    msg["From"] = EMAIL_CONFIG["EMAIL_USER"]
    msg["To"] = ", ".join(EMAIL_CONFIG["EMAIL_TO"])
    msg["Subject"] = subject
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL(EMAIL_CONFIG["SMTP_SERVER"], EMAIL_CONFIG["SMTP_PORT"]) as server:
            server.login(EMAIL_CONFIG["EMAIL_USER"], EMAIL_CONFIG["EMAIL_PASS"])
            server.send_message(msg)
        print(f"✅ 邮件发送成功: {subject}")
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")
        
        
if __name__ == '__main__':
    
    
    alert_triggered = False
    while True:
        if is_in_trading_hours():

            prev_today, today, next_day = get_date_from_calendar()
            current_time = datetime.datetime.now().time()
            close_time = datetime.time(15, 30)
            # 由于商品夜盘的缘故，需要改变存储路径的位置
            if current_time > close_time:
                file_path = f"/cpfs/prod/check/{next_day}/merged_commodity.csv"
            else:
                file_path = f"/cpfs/prod/check/{today}/merged_commodity.csv"
            
            if os.path.exists(file_path):
                now = time.time()
                mtime = os.path.getmtime(file_path)
                last_modify_time = datetime.datetime.fromtimestamp(mtime).strftime('%H:%M:%S')
                time_diff = now - mtime
                if time_diff > 60 * CHECK_INTERVAL: # 检查最后一次更新的时间和当前系统时间的差
                    if not alert_triggered:
                        print(f"Now: {datetime.datetime.now().strftime('%H:%M:%S')} - Last Modified: {last_modify_time} 文件超过{CHECK_INTERVAL}分钟没更新")
                        alert_triggered = True
                        html = prepare_html()
                        send_email(subject="商品期货文件超过6min未更新", html_content=html)
                    else: 
                        print(f"{ datetime.datetime.now().strftime('%H:%M:%S')} 已发送邮件报警")
                else:
                    if alert_triggered:
                        print(f"已于6min内更新文件")
                        alert_triggered = False
                    #print(f"Now: {datetime.datetime.now().strftime('%H:%M:%S')} - Last Modified: {last_modify_time} 文件更新无异常")
            else:
                print("File not found")
                
        time.sleep(10)  
    