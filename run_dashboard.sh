
/opt/anaconda3/bin/streamlit run cf_all.py --server.headless true --browser.gatherUsageStats false --server.port 8008 &
/opt/anaconda3/bin/streamlit run if_all.py --server.headless true --browser.gatherUsageStats false --server.port 8009 &
/opt/anaconda3/bin/streamlit run cf_position.py --server.headless true --browser.gatherUsageStats false --server.port 9001 &
/opt/anaconda3/bin/streamlit run if_position.py --server.headless true --browser.gatherUsageStats false --server.port 9002 &
