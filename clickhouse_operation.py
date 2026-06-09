# clickhouse_operation.py
from clickhouse_connect.driver import create_client

client = create_client(
    host='10.51.4.21',   # ClickHouse 地址
    port=8123,          # TCP 原生端口
    username='dashboard', 
    password='123456',
    database='cffex_zx'  # 你要操作的数据库
)

def get_product_asset(product_name: str):
    global client
    """
    根据 product_name 查询现金(asset)
    :param client: clickhouse-connect client
    :param product_name: 产品名，如 'melt'
    :return: asset 数值（int），如果不存在返回 None
    """
    query = f"""
        SELECT asset
        FROM commodity_meta.product_asset
        WHERE product_name = '{product_name}'
        LIMIT 1
    """

    try:
        result = client.query_df(query)

        if not result.empty:
            asset = int(result.iloc[0]["asset"])
            return asset
        else:
            return None

    except Exception as e:
        print("Query failed:", e)
        return None



def get_product_clip(product_name: str):
    global client
    """
    根据 product_name 查询clip
    :param client: clickhouse-connect client
    :param product_name: 产品名，如 'melt'
    :return: clip 数值（int），如果不存在返回 None
    """
    query = f"""
        SELECT clip
        FROM commodity_meta.product_clip
        WHERE product_name = '{product_name}'
        LIMIT 1
    """

    try:
        result = client.query_df(query)

        if not result.empty:
            clip = int(result.iloc[0]["clip"])
            return clip
        else:
            return None

    except Exception as e:
        print("Query failed:", e)
        return None


def get_product_uplimit_coef(product_name: str):
    global client
    """
    根据 product_name 查询coef(coef)
    :param client: clickhouse-connect client
    :param product_name: 产品名，如 'melt'
    :return: coef 数值（double），如果不存在返回 None
    """
    query = f"""
        SELECT coef
        FROM commodity_meta.product_uplimit_coef
        WHERE product_name = 'all'
        LIMIT 1
    """
    
    try:
        result = client.query_df(query)

        if not result.empty:
            coef = float(result.iloc[0]["coef"])
            return coef
        else:
            return None

    except Exception as e:
        print("Query failed:", e)
        return None

if __name__ == "__main__":

    # product_asset = get_product_asset()
    uplimit_coef = get_product_uplimit_coef("cncf_melt_gbt")
    print("uplimit_coef = ", uplimit_coef)