
import json
import requests
import time
import hmac
import hashlib
import datetime

# BitFlyer class
class FlyLib():
    ########################################
    api_key = '<<ＡＰＩキー>>'
    api_secret = '<<ＡＰＩシークレット>>'
    ########################################
    api_endpoint = 'https://api.bitflyer.jp'
    def __init__(self):
        pass
    # Get DateTime (convert format)
    def get_dt(str):
        if str.find('.') == -1:
            str += '.0'
        return datetime.datetime.strptime(str, "%Y-%m-%dT%H:%M:%S.%f")
    # post API
    def post_api_call(path, body):
        method = 'POST'
        timestamp = str(int(time.time()))
        b = str(body)
        text = timestamp + method + path + b
        sign = hmac.new(FlyLib.api_secret.encode('utf-8'), text.encode('utf-8'), hashlib.sha256).hexdigest()
        request_data = requests.post(
            FlyLib.api_endpoint + path
            ,headers = {
                'ACCESS-KEY': FlyLib.api_key,
                'ACCESS-TIMESTAMP': timestamp,
                'ACCESS-SIGN': sign,
                'Content-Type': 'application/json'
            }
            ,data = b)
        return request_data
    # API CALL
    def get_api_call(path, is_pri = True):
        method = 'GET'
        timestamp = str(time.time())
        if is_pri == True:
            # Private API
            key = FlyLib.api_key
            text = (timestamp + method + path).encode('utf-8')
            sign = hmac.new(FlyLib.api_secret.encode('utf-8'), text, hashlib.sha256).hexdigest()
        else:
            # public API
            key = 'public'
            sign = 'public'
        request_data = requests.get(
            FlyLib.api_endpoint + path
            ,headers = {
                'ACCESS-KEY': key,
                'ACCESS-TIMESTAMP': timestamp,
                'ACCESS-SIGN': sign,
                'Content-Type': 'application/json'
            })
        return request_data
    # JSON
    def get_json(path, is_pri = True):
        return FlyLib.get_api_call(path,is_pri).json()
    # check status (NORMAL, BUSY, VERY BUSY, STOP)
    def check_status():
        print(FlyLib.get_json('/v1/gethealth')['status'])
    # Get balance
    def get_balance():
        return FlyLib.get_json('/v1/me/getbalance', True)
    # Get
    def get_collateral():
        return FlyLib.get_json('/v1/me/getcollateral', True)
    # Get Contract history
    def get_contract_price(id=0, count=500):
        if id == 0:
            str = '/v1/executions?product_code=FX_BTC_JPY&count={}'.format(count)
        else:
            str = '/v1/executions?product_code=FX_BTC_JPY&count={}&before={}'.format(count,id)
        return FlyLib.get_json(str, False)
    # Get Best Bid/Ask/diff
    def get_best_price():
        tmp = FlyLib.get_json('/v1/ticker?product_code=FX_BTC_JPY', False)
        return (tmp['best_bid'], tmp['best_ask'], tmp['best_ask'] - tmp['best_bid'])
    # Get Board info (bid/ask mix)
    def get_board_info():
        return FlyLib.get_json('/v1/board?product_code=FX_BTC_JPY', False)
    # Calc BuyPrice
    def calc_price(isbids, chksize, chkboardrange):
        ba = "bids" if isbids == True else "asks"
        for i, j in enumerate(FlyLib.get_board_info()[ba][0:chkboardrange-1]):
            #print("price={}, size={}".format(j['price'], j['size']))
            if chksize <= j['size']:
                return (j['price'], j['size'])
        return (0, 0)
    # Check price size
    def chk_price_size(isbids, chkprice):
        ba = "bids" if isbids == True else "asks"
        for j in FlyLib.get_board_info()[ba]:
            if chkprice == j['price']:
                return (j['price'], j['size'])
            elif j['price'] < chkprice:
                return (0, 0)
        return (0, 0)
    # Check board price
    def chk_board_price(isbids, chksize, chkprice):
        ba = "bids" if isbids == True else "asks"
        for j in FlyLib.get_board_info()[ba]:
            if chkprice == j['price']:
                return False
            if j['size'] >= chksize:
                return True
        return False
    #get order list
    def get_orders():
        return
    # send new order
    def send_order(isbuy, price, size):
        body = {
            'product_code': 'FX_BTC_JPY',
            'child_order_type': 'LIMIT',
            'side': 'BUY',
            'price': price,
            'size': size,
            'minute_to_expire': 1440,   # 1440 = expire 1 day.
            'time_in_force': 'GTC'
        }
        body['side'] = 'BUY' if isbuy == True else 'SELL'
        return FlyLib.post_api_call('/v1/me/sendchildorder', body)
    # get order list
    def list_order(order_state):
        p = '/v1/me/getchildorders?product_code=FX_BTC_JPY&child_order_state=' + order_state
        return FlyLib.get_api_call(p)
    # reject all arders
    def reject_order():
        return FlyLib.post_api_call('/v1/me/cancelallchildorders', {'product_code': 'FX_BTC_JPY'})
    # get position json
    def get_position():
        return FlyLib.get_json('/v1/me/getpositions?product_code=FX_BTC_JPY', True)
    # get position volume
    def get_allpossize():
        p = FlyLib.get_position()
        buyvol = sellvol = 0
        for obj in p:
            if obj['side'] == 'BUY':
                buyvol += obj['size']
            elif obj['side'] == 'SELL':
                sellvol += obj['size']
        return {'BUY': buyvol, 'SELL': sellvol}
    # Private API Account Access Check
    def check_account_access():
        chkpass = ['/v1/me/sendchildorder', '/v1/me/getcollateral']
        r = FlyLib.get_api_call('/v1/me/getpermissions', True)
        if r.status_code != 200:
            return False
        if sum([i in r.json() for i in chkpass]) == len(chkpass):
            return True
        return False
