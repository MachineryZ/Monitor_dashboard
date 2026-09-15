
/opt/anaconda3/bin/streamlit run cf_all.py --server.headless true --browser.gatherUsageStats false --server.port 1024 &
/opt/anaconda3/bin/streamlit run if_all.py --server.headless true --browser.gatherUsageStats false --server.port 1025 &
/opt/anaconda3/bin/streamlit run cf_position.py --server.headless true --browser.gatherUsageStats false --server.port 2001 &
/opt/anaconda3/bin/streamlit run if_position.py --server.headless true --browser.gatherUsageStats false --server.port 2002 &


/opt/anaconda3/bin/streamlit run /home/jason/monitor_dashboard/cncfif_overall.py --server.headless true --browser.gatherUsageStats false --server.port 2222

/opt/anaconda3/bin/streamlit run /home/jason/monitor_dashboard/cncfif_overall_test.py --server.headless true --browser.gatherUsageStats false --server.port 2224


/opt/anaconda3/bin/streamlit run /home/jason/monitor_dashboard/cncf_contract_summary_plot_test.py --server.headless true --browser.gatherUsageStats false --server.port 1116
/opt/anaconda3/bin/streamlit run /home/jason/monitor_dashboard/cncf_contract_summary_plot.py --server.headless true --browser.gatherUsageStats false --server.port 2226


/opt/anaconda3/bin/streamlit run /home/jason/monitor_dashboard/cncfif_overall_mix_plot_test.py --server.headless true --browser.gatherUsageStats false --server.port 1115
/opt/anaconda3/bin/streamlit run /home/jason/monitor_dashboard/cncfif_overall_mix_plot.py --server.headless true --browser.gatherUsageStats false --server.port 2225

