import requests
import json
import base64
import time
import os
import logging
import logging.handlers
from typing import Optional, Dict, Any, Union, List

class RWPAPIClient:
    global access_token
    # global last_access_token
    def __init__(self, api_url: str = "http://rwp.dunhefund.com:6680"):
    # def __init__(self, api_url: str = "http://10.1.102.101:8080"):
        self.api_url = api_url
        self._access_token = ""
        self._last_access_token = 0
        self.login_user_name = ""
        self.login_password = ""
        self.token_expiry = 7000  # Token expiry time in seconds
        self.logger = self._setup_logger()

    @property
    def access_token_property(self):
        return self._access_token

    @access_token_property.setter
    def access_token_property(self, value):
        self._access_token = value
        access_token = value

    @property
    def last_access_token(self):
        return self._last_access_token

    @last_access_token.setter
    def last_access_token(self, value):
        self._last_access_token = value

    def _setup_logger(self) -> logging.Logger:
        """设置日志"""
        logger = logging.getLogger('rwp_api_logger')
        
        # 清除已有的处理器，避免重复添加
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        os.makedirs("logs", exist_ok=True)
        # 获取日志配置
        log_file = 'logs/rwp_api.log'
        max_days = 30
        log_level_str = 'INFO'
        log_level = getattr(logging, log_level_str, logging.INFO)
        # 设置日志级别
        logger.setLevel(log_level)
        
        # 创建按天轮转的文件处理器
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=log_file,
            when='midnight',  # 每天午夜轮转
            interval=1,       # 每1天
            backupCount=max_days,  # 保留文件数量
            encoding='utf-8',
            utc=False  # 使用本地时间
        )
        file_handler.setLevel(log_level)
        
        # 创建控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        
        # 创建格式器
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        # 设置文件后缀格式（例如：monitor.log.2024-01-15）
        file_handler.suffix = '%Y-%m-%d'
        
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        return logger

    def _check_token(self) -> None:
        """Check if token needs to be refreshed and refresh if necessary."""
        current_time = time.time()
        if self._access_token == "":
            self._access_token = access_token
        if current_time - self.last_access_token > self.token_expiry and self.login_user_name != "":
            self.login(self.login_user_name, self.login_password)
            self.logger.info("重新登陆")

    def _handle_response(self, response: requests.Response) -> Dict[str, Any]:
        """Handle API response and return parsed JSON."""
        self.logger.info(f"response.status_code={response.status_code}, response.text={response.text}")
        resp_json = response.json()
        if resp_json["code"] == 1:
            self.logger.info("调用成功")
            return resp_json
        else:
            error_msg = ""
            try:
                error_msg = str(base64.b64decode(resp_json["message"]), "utf-8")
            except Exception as e:
                error_msg = resp_json["message"]                
            self.logger.info(f"调用失败[{resp_json['code']}]: {error_msg}")
            return resp_json

    def login(self, user_name: str, password: str) -> int:
        """Login to the API and get access token."""
        self.login_user_name = user_name
        self.login_password = password
        bpass = str(base64.b64encode(password.encode("utf-8")), "utf-8")
        req_text = {"user_name": user_name, "password": bpass, "client_type": 4}
        req_json = json.dumps(req_text)
        
        resp = requests.post(f"{self.api_url}/api/user/login", data=req_json)
        resp_json = resp.json()
        
        if resp_json["code"] == 1:
            self.access_token_property = resp_json["access_token"]
            self.logger.info(f"登陆成功，access_token={self.access_token_property}")
            self.last_access_token = time.time()
        else:
            error_msg = str(base64.b64decode(resp_json["message"]), "utf-8")
            self.logger.info(f"登陆失败[{resp_json['code']}]: {error_msg}")
        
        return resp_json["code"]

    def _make_request(self, method: str, endpoint: str, data: Optional[Union[str, Dict]] = None) -> Dict[str, Any]:
        """Make an API request with automatic token refresh."""
        self._check_token()
        url = f"{self.api_url}{endpoint}?access_token={self.access_token_property}"
        self.logger.info(f'url={url}, data={data}')

        if isinstance(data, dict):
            data = json.dumps(data)
            
        if method.upper() == "GET":
            response = requests.get(url, params=data)
        else:
            response = requests.post(url, data=data)
            
        return self._handle_response(response)

    def get_vir_fund_hold(self, req_json: Union[str, Dict]) -> Dict[str, Any]:
        """Get virtual fund holdings."""
        self._check_token()
        url = f"{self.api_url}/easy_api/customreport/report_qhccsz?access_token={self.access_token_property}"
        response = requests.get(url=url, headers={"User-Agent": "Mozilla/5.0"}, params=req_json)
        return self._handle_response(response)

    def get_fund_nav_share(self, req_json: Union[str, Dict]) -> Dict[str, Any]:
        """get_fund_nav_share."""
        self._check_token()
        url = f"{self.api_url}/easy_api/customreport/report_fjcpjzfe?access_token={self.access_token_property}"
        response = requests.get(url=url, headers={"User-Agent": "Mozilla/5.0"}, params=req_json)
        return self._handle_response(response)

    def get_stock_oi_info_single(self, req_json: Union[str, Dict]) -> Dict[str, Any]:
        """Get stock OI information."""
        return self._make_request("POST", "/api/basicdata/get_stock_oi_info", req_json)

    def update_index_data(self, req_json: Union[str, Dict]) -> int:
        """Update index data."""
        resp = self._make_request("POST", "/api/research_data/update_index_data", req_json)
        return resp["code"]

    def add_index_dc(self, class_path: List[Dict], index_name: str, unit: str, freq: str, 
                    source: str, source_detail: str, remark: str) -> int:
        """Add index data center."""
        # First get class path
        req_text = {"class_list": class_path}
        req_json = json.dumps(req_text, ensure_ascii=False).encode("utf-8")
        resp = self._make_request("POST", "/api/data_research/index_class/get_class_path", req_json)
        
        if resp["code"] == 1 and resp["exist_flag"] == 1:
            if resp["right_level"] >= 40:
                class_id = resp["class_id"]
                req_text = {
                    "location_type": 1,
                    "parent_id": class_id,
                    "index_name": str(base64.b64encode(index_name.encode("utf-8")), "utf-8"),
                    "unit": str(base64.b64encode(unit.encode("utf-8")), "utf-8"),
                    "freq": freq,
                    "source": source,
                    "source_detail": source_detail,
                    "remark": str(base64.b64encode(remark.encode("utf-8")), "utf-8")
                }
                req_json = json.dumps(req_text, ensure_ascii=False).encode("utf-8")
                resp = self._make_request("POST", "/api/data_research/index_manager/add_index", req_json)
                if resp["code"] == 1:
                    print(f"新增指标成功: {index_name}")
                return resp["code"]
            else:
                print("没有此目录的管理权限")
                return -1
        else:
            print("目录不存在")
            return -1

    def get_index_data(self, req_json: Union[str, Dict]) -> Dict[str, Any]:
        """Get index data."""
        return self._make_request("POST", "/api/research_data/get_index_data", req_json)

    def get_future_kind_info(self) -> Dict[str, Any]:
        """Get future kind information."""
        return self._make_request("POST", "/api/basicdata/get_future_kind_info")

    def upload_operation_log(self, req_json: Union[str, Dict]) -> int:
        """Upload operation log."""
        resp = self._make_request("POST", "/api/basic/upload_operation_log", req_json)
        return resp["code"]

    def get_stock_con_forecast(self, req_json: Union[str, Dict]) -> Dict[str, Any]:
        """Get stock consensus forecast."""
        return self._make_request("POST", "/api/basicdata/zyyx/get_stock_con_forecast", req_json)

    def get_virtual_fund_chart(self, req_json: Union[str, Dict]) -> Dict[str, Any]:
        """Get virtual fund chart."""
        return self._make_request("POST", "/api/trade_manager/virtual_fund/get_virtual_fund_chart", req_json)

    def get_unit_asset_chart(self, req_json: Union[str, Dict]) -> Dict[str, Any]:
        """Get unit asset chart."""
        return self._make_request("POST", "/api/trade_manager/fund_unit/get_unit_asset_chart", req_json)

    def query_fund_strategy_profit(self, req_json: Union[str, Dict]) -> Dict[str, Any]:
        """Query fund strategy profit."""
        return self._make_request("POST", "/api/risk_performance/return_flow/query_fund_strategy_profit", req_json)

    def query_researcher_kind_profit(self, req_json: Union[str, Dict]) -> Dict[str, Any]:
        """Query researcher kind profit."""
        return self._make_request("POST", "/api/risk_performance/return_flow/query_researcher_kind_profit", req_json)

    def getUnitHistoryHold(self, fund_id: str) -> Dict[str, Any]:
        """Get unit history holdings."""
        self._check_token()
        url = f"{self.api_url}/realStockTrade/unitInfo/perfomence/getUnitHistoryHold?virtualFundId={fund_id}&access_token={self.access_token_property}"
        response = requests.get(url)
        return self._handle_response(response)

    def get_future_eodprice(self, req_json: Union[str, Dict]) -> Dict[str, Any]:
        """Get future EOD price."""
        return self._make_request("POST", "/api/basicdata/get_future_eodprice", req_json)

    def get_stock_info(self, req_json: Union[str, Dict]) -> Dict[str, Any]:
        """Get stock information."""
        return self._make_request("POST", "/api/basicdata/get_stock_info", req_json)

    def get_futures_info(self, req_json: Union[str, Dict]) -> Dict[str, Any]:
        """Get futures information."""
        return self._make_request("POST", "/api/basicdata/get_futures_info", req_json)

    def get_index_info(self, req_json: Union[str, Dict]) -> Dict[str, Any]:
        """Get index information."""
        return self._make_request("POST", "/api/research_data/get_index_info", req_json)

    def get_risk_stock_list(self, req_json: Union[str, Dict]) -> Dict[str, Any]:
        """Get risk stock list."""
        return self._make_request("POST", "/api/basic/get_risk_stock_list", req_json)

    def getPerfomenceChart(self, fundId: str, startDate: str, endDate: str, indexId: str) -> Dict[str, Any]:
        """Get performance chart."""
        self._check_token()
        url = f"{self.api_url}/tradeRiskPerformance/fundInfo/perfomence/getPerfomenceChart?fundId={fundId}&startDate={startDate}&endDate={endDate}&indexId={indexId}&access_token={self.access_token_property}"
        self.logger.info(f'url={url}')
        response = requests.get(url)
        return self._handle_response(response)

    def get_fund_position_by_label(self, fund_id: str, date: str, holding_source: str, label: str) -> Dict[str, Any]:
        """Get fund position by label."""
        req_text = {
            "fund_id": fund_id,
            "date": date,
            "holding_source": holding_source,
            "label": label
        }
        return self._make_request("POST", "/api/risk_perfomence/position/query_fund_position_by_label", req_text)
    
    def get_fund_asset_contribute_by_lable(self, fundId: str,startDate:str, endDate: str, label: str) -> Dict[str, Any]:
        """get_fund_asset_contribute_by_lable"""        
        return self._make_request("GET", "/tradeRiskPerformance/fundInfo/perfomence/getFundAssetContributeByLable","fundId="+str(fundId)+"&startDate="+str(startDate)+"&endDate="+str(endDate)+"&label="+str(label))

    def get_unit_holding(self, fund_id: str, unit_id: str, busin_date: str) -> Dict[str, Any]:
        """Get unit holdings."""
        req_text = {
            "fund_id": fund_id,
            "unit_id": unit_id,
            "busin_date": busin_date
        }
        return self._make_request("POST", "/api/trade_manager/fund_unit/get_fund_unit_holding", req_text)

    def get_fund_nav(self, req_json: Union[str, Dict]) -> Dict[str, Any]:
        """Get fund NAV."""
        return self._make_request("POST", "/api/basicdata/get_fund_nav", req_json)

    def get_fund_right(self, req_json: Union[str, Dict]) -> Dict[str, Any]:
        """Get fund rights."""
        return self._make_request("POST", "/api/user/get_fund_right", req_json)  
    
    def get_unit_right(self, req_json: Union[str, Dict]) -> Dict[str, Any]:
        """Get unit rights."""
        return self._make_request("POST", "/api/user/get_unit_right", req_json)

    def get_report_TGZBSJ(self, fund_code: str, end_date: str) -> Dict[str, Any]:
        """Get report TGZBSJ."""
        self._check_token()
        url = f"{self.api_url}/easy_api/customreport/report_TGZBSJ?access_token={self.access_token_property}&fund_code={fund_code}&end_date={end_date}"
        response = requests.get(url)
        return self._handle_response(response)

    def get_future_data_analysis(self, fund_code: str, end_date: str) -> Dict[str, Any]:
        """get_future_data_analysis."""
        self._check_token()
        url = f"{self.api_url}/easy_api/customreport/get_future_data_analysis?access_token={self.access_token_property}&fund_code={fund_code}&end_date={end_date}"
        response = requests.get(url)
        return self._handle_response(response)

    def get_future_data_analysis_qy1(self, fund_code: str, end_date: str) -> Dict[str, Any]:
        """get_future_data_analysis."""
        self._check_token()
        url = f"{self.api_url}/easy_api/customreport/get_future_data_analysis_qy1?access_token={self.access_token_property}&fund_code={fund_code}&end_date={end_date}"
        response = requests.get(url)
        return self._handle_response(response)

    def get_unit_list(self, req_json: Union[str, Dict]) -> Dict[str, Any]:
        """Get unit list."""
        return self._make_request("POST", "/api/trade_manager/system_manager/get_fund_unit_list", req_json)

    def get_future_list(self, req_json: Union[str, Dict]) -> Dict[str, Any]:
        """Get future list."""
        return self._make_request("POST", "/api/basic/get_future_list", req_json)

    def get_trade_calender(self, req_json: Union[str, Dict]) -> Dict[str, Any]:
        """Get trade calendar."""
        return self._make_request("POST", "/api/basic/get_trade_calender", req_json)

    def get_sett_stock(self, req_json: Union[str, Dict]) -> Dict[str, Any]:
        """Get unit holdings."""
        return self._make_request("POST", "/api/tradeRiskPerformance/performance/stock_info_qry", req_json)
    
    def get_index_member_weight(self, req_json: Union[str, Dict]) -> Dict[str, Any]:
        """Get index member weight."""
        return self._make_request("POST", "/api/basic/get_index_member_weight", req_json)
    
    def get_unit_trade_entrusts(self, req_json: Union[str, Dict]) -> Dict[str, Any]:
        """Get unit entrust."""
        return self._make_request("POST", "/api/trade_manager/algo_order/query_unit_entrusts", req_json)
    
    def get_unit_trade_deals(self, req_json: Union[str, Dict]) -> Dict[str, Any]:
        """Get unit deal."""
        return self._make_request("POST", "/api/trade_manager/algo_order/query_unit_deals", req_json)
		
    def get_sett_stock_sum(self, req_json: Union[str, Dict]) -> Dict[str, Any]:
        """Get unit holdings."""
        return self._make_request("POST", "/api/tradeRiskPerformance/performance/stock_sum_qry", req_json)

# 为了保持向后兼容性，创建全局客户端实例
_client = RWPAPIClient()

# 为了保持向后兼容性，创建全局变量
access_token = ""
last_access_token = 0

# 返回1为登陆成功
def login(user_name, password):
    # 使用新的客户端类
    result = _client.login(user_name, password)
    
    # 更新全局变量以保持兼容性
    global login_user_name, login_password
    login_user_name = _client.login_user_name
    login_password = _client.login_password
    
    return result

def get_future_kind_info():
    # 使用新的客户端类
    return _client.get_future_kind_info()

def get_vir_fund_hold(req_json):
    return _client.get_vir_fund_hold(req_json)

def get_fund_nav_share(req_json):    
    return _client.get_fund_nav_share(req_json)

def get_stock_oi_info_single(req_json):
    return _client.get_stock_oi_info_single(req_json)

def update_index_data(req_json):
    return _client.update_index_data(req_json)

def add_index_dc(class_path, index_name, unit, freq, source, source_detail, remark):
    return _client.add_index_dc(class_path, index_name, unit, freq, source, source_detail, remark)

def get_index_data(req_json):
    return _client.get_index_data(req_json)

def upload_operation_log(req_json):
    return _client.upload_operation_log(req_json)

def get_stock_con_forecast(req_json):
    return _client.get_stock_con_forecast(req_json)

def get_virtual_fund_chart(req_json):
    resp_json = _client.get_virtual_fund_chart(req_json)
    return resp_json

def get_unit_asset_chart(req_json):
    resp_json = _client.get_unit_asset_chart(req_json)
    return resp_json

def query_fund_strategy_profit(req_json):
    resp_json = _client.query_fund_strategy_profit(req_json)
    return resp_json

def query_researcher_kind_profit(req_json):
    resp_json = _client.query_researcher_kind_profit(req_json)
    return resp_json

def getUnitHistoryHold(fund_id):
    resp_json = _client.getUnitHistoryHold(fund_id)
    return resp_json

def get_future_eodprice(req_json):
    resp_json = _client.get_future_eodprice(req_json)
    return resp_json

def get_stock_info(req_json):
    resp_json = _client.get_stock_info(req_json)
    return resp_json

def get_futures_info(req_json):
    resp_json = _client.get_futures_info(req_json)
    return resp_json

def get_index_info(req_json):
    resp_json = _client.get_index_info(req_json)
    return resp_json

def get_risk_stock_list(req_json):
    resp_json = _client.get_risk_stock_list(req_json)
    return resp_json

def getPerfomenceChart(fundId, startDate, endDate, indexId):
    resp_json = _client.getPerfomenceChart(fundId, startDate, endDate, indexId)
    return resp_json

def get_fund_position_by_label(fund_id, date, holding_source, label):
    resp_json = _client.get_fund_position_by_label(fund_id, date, holding_source, label)
    return resp_json

def get_fund_asset_contribute_by_lable(fundId, startDate,endDate, label):
    resp_json = _client.get_fund_asset_contribute_by_lable(fundId, startDate, endDate, label)
    return resp_json

def get_unit_holding(fund_id, unit_id, busin_date):
    resp_json = _client.get_unit_holding(fund_id, unit_id, busin_date)
    return resp_json

def get_fund_nav(req_json):
    resp_json = _client.get_fund_nav(req_json)
    return resp_json

def get_fund_right(req_json):
    resp_json = _client.get_fund_right(req_json)
    return resp_json

def get_unit_right(req_json):
    resp_json = _client.get_unit_right(req_json)
    return resp_json

def get_report_TGZBSJ(fund_code, end_date):
    resp_text = _client.get_report_TGZBSJ(fund_code, end_date)
    return resp_text

def get_future_data_analysis(fund_code, end_date):
    resp_text = _client.get_future_data_analysis(fund_code, end_date)
    return resp_text

def get_future_data_analysis_qy1(fund_code, end_date):
    resp_text = _client.get_future_data_analysis_qy1(fund_code, end_date)
    return resp_text

def get_unit_list(req_json):
    resp_json = _client.get_unit_list(req_json)
    return resp_json

def get_future_list(req_json):
    resp_json = _client.get_future_list(req_json)
    return resp_json

def get_trade_calender(req_json):
    resp_json = _client.get_trade_calender(req_json)
    return resp_json

def get_sett_stock(req_json):
    resp_json = _client.get_sett_stock(req_json)
    return resp_json

def get_index_member_weight(req_json):
    resp_json = _client.get_index_member_weight(req_json)
    return resp_json

def get_unit_trade_entrusts(req_json):
    resp_json = _client.get_unit_trade_entrusts(req_json)
    return resp_json

def get_unit_trade_deals(req_json):
    resp_json = _client.get_unit_trade_deals(req_json)
    return resp_json

def get_sett_stock_sum(req_json):
    resp_json = _client.get_sett_stock_sum(req_json)
    return resp_json