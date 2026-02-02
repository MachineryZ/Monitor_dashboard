#!/bin/bash

# Setup cron jobs for automatic stop and restart
# This script adds cron jobs to stop at 15:10 and restart at 15:20 daily

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Get the full paths
STOP_SCRIPT="$SCRIPT_DIR/stop_all.sh"
RESTART_SCRIPT="$SCRIPT_DIR/restart_all.sh"

# Create temporary file for new crontab
TMP_CRON=$(mktemp)

# Get existing crontab (if any) and remove old entries for these scripts
crontab -l 2>/dev/null | grep -v "stop_all.sh\|restart_all.sh" > "$TMP_CRON" || true

# Add new cron jobs
echo "# Auto stop dashboard and monitoring scripts at 15:10 daily" >> "$TMP_CRON"
echo "10 15 * * * bash $STOP_SCRIPT >> $SCRIPT_DIR/cron.log 2>&1" >> "$TMP_CRON"
echo "" >> "$TMP_CRON"
echo "# Auto restart dashboard and monitoring scripts at 15:20 daily" >> "$TMP_CRON"
echo "20 15 * * * bash $RESTART_SCRIPT >> $SCRIPT_DIR/cron.log 2>&1" >> "$TMP_CRON"

# Install the new crontab
crontab "$TMP_CRON"

# Clean up
rm "$TMP_CRON"

echo "Cron jobs installed successfully!"
echo ""
echo "Current crontab:"
crontab -l | grep -A 2 "stop_all.sh\|restart_all.sh"
echo ""
echo "The scripts will:"
echo " - Stop all processes at 15:10 daily"
echo " - Restart all processes at 15:20 daily"
echo ""
echo "Logs will be written to :$SCRIPT_DIR/cron.log"

