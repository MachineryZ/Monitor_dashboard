#!/bin/bash

# Restart all dashbarod and monitoring scripts
# This script stops all processes first, then restarts them

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Restarting all dashboard and monitoring processes ..."

bash "SCRIPT_DIR/stop_all.sh"

sleep 2

cd "$SCRIPT_DIR"

echo "Starting dashboard scripts..."
bash "$SCRIPT_DIR/run_dashboard.sh"

sleep 1

echo "Starting monitoring scripts..."
bash "$SCRIPT_DIR/run_update_check.sh"

echo "All processes restarted successfully"