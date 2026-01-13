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
    ("09:05", "10:15"),
    ("10:35", "11:30"),
    ("13:35", "15:00"),
    ("21:05", "23:59")
]

EMAIL_CONFIG = {
    "SMTP_SERVER": "smtp.exmail.qq.com",
    "SMTP_PORT": 465,
    "EMAIL_USER": "liujz@dunhefund.com",
    "EMAIL_PASS": "cYT6xks26ERPZbcf",
    "EMAIL_TO": [
        "yangjy@dunhefund.com"
        "jiangl@dunhefund.com",
        "zhoujg@dunhefund.com",
        "xuh@dunhefund.com"
    ]
}

def get_date_from_calendar():
    
    date = datetime.datetime.now().date()
    date_int = int(date.strftime("%Y%m%d"))
    
    date_list = np.loadtxt(CALENDAR_PATH, dtype=np.int64, ndmin=1)

    pos = np.searchsorted(date_list, date_int, side="right")
    
    
    next_trade_day = date_list[pos]
    
    return date_int, next_trade_day

def is_in_trading_hours():
    
    date_list = np.loadtxt(CALENDAR_PATH, dtype=np.int64, ndmin=1)
    date = datetime.datetime.now().date()
    date_int = int(date.strftime("%Y%m%d"))
    
    if date_int in date_list:
        now = datetime.datetime.now()
        current_time = now.time()
        for start, end in TRADING_SESSIONS:
            start_time = datetime.datetime.strptime(start, "%H:%M").time()
            end_time = datetime.datetime.strptime(end, "%H:%M").time()
            
            if start_time <= current_time <= end_time:
                return True
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

            today, next_day = get_date_from_calendar()
            current_time = datetime.datetime.now().time()
            close_time = datetime.time(15, 30)
    
            if current_time > close_time:
                date_int = date_int + 1
                
            if current_time > close_time:
                file_path = f"/cpfs/prod/check/{next_day}/merged_commodity.csv"
            else:
                file_path = f"/cpfs/prod/check/{today}/merged_commodity.csv"
            
            if os.path.exists(file_path):
                now = time.time()
                mtime = os.path.getmtime(file_path)
                last_modify_time = datetime.datetime.fromtimestamp(mtime).strftime('%H:%M:%S')
                time_diff = now - mtime
                if time_diff > 60 * CHECK_INTERVAL:
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
    