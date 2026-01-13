# MONITOR_DASHBOARD
本仓库代码包含两个功能：
- 使用python库streamlit，读取jason存储的交易日志dataframe，生成商品和股指的监控看板；共计四个看板，分别显示不同信息。
- 通过检查jason存储文件的最后更新时间与当前系统时间的差，来判断是否漏更新。

## 文件构成

- `cf_all.py` 商品期货全部信息dashboard的python启动脚本
- `cf_position.py` 商品期货仓位信息dashboard的python启动脚本
- `if_all.py` 股指期货全部信息dashboard的python启动脚本
- `if_position.py` 股指期货仓位信息dashboard的python启动脚本
- `cf_info.csv` 商品交易所、品种、代码等信息
- `run_dashboard.sh` 四个dashboard启动的shell脚本
- `check_cf_update.py` 四个dashboard启动的shell脚本
- `check_if_update.py` 四个dashboard启动的shell脚本
- `run_update_check.sh` 监控文件是否正常更新的shell脚本

## 使用方法
配置相关python环境，在`run_dashboard.sh`中配置想要运行的端口，运行：
```
bash run_dashboard.sh
bash run_update_check.sh
```

## 依赖
```
pandas
numpy
streamlit
```

