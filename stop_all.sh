#!/bin/bash

# Stop all dashboard and monitoring scripts
# This script kills all streamlit processes and monitoring python scripts

echo "Stopping all dashboard and monitoring processes..."

# Stop streamlit processes (dashboards)
# Find process by port numbers
for port in 1024 1025 2001 2002; do
    pid=$(lsof -ti:$port 2>/dev/null)
    if [ ! -z "$pid" ]; then
        echo "Stopping streamlit process on port $port (PID: $pid)"
        kill -9 $pid 2>/dev/null
    fi
done

# Stop Monitoring python scripts
# Find processes by script name
for script in "check_cf_update.py" "check_if_update.py"; do
    pids=$(ps aux |grep "[p]ython.*script" | awk '{print $2}')
    if [ ! -z "$pids" ]; then
        echo "Stopping $script processes (PIDs: $pids)"
        echo "$pids" | xargs kill -9 2>/dev/null
    fi
done

# Also try to find streamlit processes by name (backup method)
streamlit_pids=$(ps aux | grep "[s]treamlit run" | awk '{print $2}')
if [ ! -z "$streamlit_pids" ]; then
    echo "Stopping remaining streamlit processes (PIDs: $streamlit_pids)"
    echo "$streamlit_pids" |xargs kill -9 2>/dev/null
fi

echo "All processes stopped."