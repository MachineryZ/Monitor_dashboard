
/opt/anaconda3/bin/streamlit run cf_all.py --server.headless true --browser.gatherUsageStats false --server.port 1024 &
/opt/anaconda3/bin/streamlit run if_all.py --server.headless true --browser.gatherUsageStats false --server.port 1025 &
/opt/anaconda3/bin/streamlit run cf_position.py --server.headless true --browser.gatherUsageStats false --server.port 2001 &
/opt/anaconda3/bin/streamlit run if_position.py --server.headless true --browser.gatherUsageStats false --server.port 2002 &