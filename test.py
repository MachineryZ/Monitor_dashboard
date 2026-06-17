import rwp_api
import json

username = "jiangl"
password = "666666@dunhe"

fund_id = 568
unit_id = 9122

# fund_id = 569
# unit_id = 9118

res = rwp_api.login(username, password)
if res == 1:
    req_text = {"fund_id": fund_id, "unit_id": unit_id, "start_date": 20260617}
    req_json = json.dumps(req_text)
    resp = rwp_api.get_unit_asset_chart(req_json)
    bank_account = resp["unit_list"][0]["nav_list"][0]["total_asset"]

print(bank_account)