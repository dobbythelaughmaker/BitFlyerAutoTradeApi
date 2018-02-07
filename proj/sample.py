import enum
import sys
import datetime
import time
from BitFlyerAccessLib import FlyLib

# パラメータ初期化
##################################################################
# 注文開始判定
p0_spread = 100             # 売買執行条件スプレッド（最良売値　ー　最良買値　＞　１００）
# 買い注文
p1_checkboardrange = 10     # 板範囲（買値の価格が高い方から10枚の買値の中で、）
p1_checksize = 0.2          # 板サイズ（N（変数：初期値0.2））
p1_buypricediff = 2         # 購入金額差分（1円上に「買い指値」を出す）
p1_buyvolume = 0.02         # 購入したいボリューム
p1_volumepercent = 0.8      # 買い完了ボリューム％（買い注文の５０％以上が約定した時点で、売却処理へ移る）
# 売り注文
p2_checkboardrange = 10     # 板範囲（売値の価格が低い方から10枚の売値の中で、）
p2_checksize = 0.2          # 板サイズ（S（変数：初期値0.2））
p2_sellpricediff = 1        # 購入金額差分
p2_high_price_out_range_time = 300  # 直近高値算出用待ち時間(秒)「現在時刻よりm秒過去 ～ 履歴最古」迄の間での高値（300秒以上前の直近高値）
p2_pause_check_price = 300  # 直近高値からＸ円判定（直近高値まで300円に迫ったら、売買を20秒停止する。）
p2_pause_wait_time = 20     # Y秒間売買停止（売買を20秒停止する。）
# 売却終了判定
contracthistory_range = 2   # 過去約定履歴さかのぼり時間（Ｈ）（直近高値を記憶）
loss_border = -5000         # システム停止損失額（損失が5,000円を超えたらストップ）
##################################################################

p1_bordervol = round((p1_buyvolume * p1_volumepercent) * 1000) / 1000
p2_sellvolume = 0
is_halt = False     # 異常停止フラグ
waitflg = False     # 高値に迫った際の売買停止フラグ

# 起点となるＩＤと価格を保持
hist = FlyLib.get_contract_price()
nowrec = hist[0]
nowdt = FlyLib.get_dt(nowrec['exec_date'])
maxhistdate = nowdt - datetime.timedelta(hours=contracthistory_range)

# データ初期化
print("\nsystem init")
print("now-date:{}/{}/{} {}:{}:{}".format(nowdt.year, nowdt.month, nowdt.day, nowdt.hour, nowdt.minute, nowdt.second))
# PrivateAPIアカウントチェック
if FlyLib.check_account_access() == False:
    print("PrivateAPIアクセス異常。api_keyとapi_secretの権限をご確認下さい。")
    sys.exit()

# １時間前までのデータをちゃんとゲットしなければならない。
#最後尾をチェックし、もし足りていなかったら、続きを取得する。
print("loading history", end="")
while True:
    lastdt = FlyLib.get_dt(hist[-1]['exec_date'])
    if lastdt < maxhistdate:
        print("done(", end="")
        print("{:-02d}:{:-02d}:{:-02d}-".format(lastdt.hour, lastdt.minute, lastdt.second), end="")
        print("{:-02d}:{:-02d}:{:-02d}(".format(nowdt.hour, nowdt.minute, nowdt.second), end="")
        oldertimedelta = nowdt - lastdt
        print("{:-.1f}hours))".format(oldertimedelta.seconds/60/60))
        break;
    hist += FlyLib.get_contract_price(hist[-1]['id'])
    print(".", end="", flush=True)

# 開始時証拠金（損益計算用）
start_collateral = FlyLib.get_collateral()['collateral']
cur_collateral = start_collateral
orderprice = 0
watchprice = 0
immediate_high_price = 0

# 履歴データに最新データを追加更新する
def get_new_history_data():
    global hist
    newhist = []
    tmpid = 0
    while True:
        tmphist = FlyLib.get_contract_price(tmpid)
        #print("len={}".format(len(newhist)))
        for i, r in enumerate(tmphist):
            if r['id'] == hist[0]['id']:
                # done
                newhist += tmphist[0:i]     # 'i' mean, target - 1.
                hist = newhist + hist
                if len(hist) > 200000:      # size over check
                    print("over")
                    hist = hist[0:200000]
                return
        newhist += tmphist
        tmpid = tmphist[-1]['id']
        #print(".(tmpid={})".format(tmpid), end="", flush=True)

# 直近高値計算
def calc_immediate_high_price():
    global hist, immediate_high_price
    immediate_high_price = 0
    nowdt = FlyLib.get_dt(hist[0]['exec_date'])
    waitdt = nowdt - datetime.timedelta(seconds=p2_high_price_out_range_time)
    for r in hist:
        # m秒より古いデータのみチェックする（300秒以上前の直近高値…）
        if waitdt < FlyLib.get_dt(r['exec_date']):
            #print("continue...", end="")
            continue
        # 過去履歴から最高値を探す
        if r['price'] > immediate_high_price:
            immediate_high_price = r['price']

# 過去履歴から約定価格を取得する
def get_past_price(nowdt, sec):
    for h in hist:
        curdt = FlyLib.get_dt(h['exec_date'])
        if (nowdt - curdt).seconds > sec:
            return (curdt, h['price'])
            break

# Ｐ０：初期化
def p0_init():
    global cur_collateral
    cur_collateral = FlyLib.get_collateral()['collateral']
    profit = cur_collateral - start_collateral
    nowpossize = FlyLib.get_allpossize()
    print("[Phase-0]：タイミング待ち処理")
    print("証拠金: 開始時={:}JPY / 現在={}JPY (損益={}JPY)  建玉数:{}BTC".format(int(start_collateral), int(cur_collateral), int(profit), nowpossize['BUY']))
    return profit

# Ｐ０：売買執行条件チェック
def p0_exec():
    global cnt, changephase
    isNext = False
    cprice_now = hist[0]['price']
    cdate_now = FlyLib.get_dt(hist[0]['exec_date'])
    (cdate_5m, cprice_5m) = get_past_price(cdate_now, 300)
    (cdate_1h, cprice_1h) = get_past_price(cdate_now, 3600)
    st = "BTC now:{}({:-02d}:{:-02d}:{:-02d})/".format(int(cprice_now), cdate_now.hour, cdate_now.minute, cdate_now.second)
    st += "-5m:{}({:-02d}:{:-02d}:{:-02d})/".format(int(cprice_5m), cdate_5m.hour, cdate_5m.minute, cdate_5m.second)
    st += "-1h:{}({:-02d}:{:-02d}:{:-02d}) ".format(int(cprice_1h), cdate_1h.hour, cdate_1h.minute, cdate_1h.second)
    st += ".  " if cnt == 0 else " .  " if cnt == 1 else "  . "
    cnt = cnt + 1 if cnt < 2 else 0
    if cprice_now > cprice_1h and cprice_now > cprice_5m:
        (best_bid, best_ask, sa) = FlyLib.get_best_price()
        if sa > p0_spread:
            st += "ASK({})-BID({})={}".format(int(best_ask), int(best_bid), int(sa))
            isNext = True
    print(('\r' + st), end="", flush=True)
    if isNext == True:
        print("=>成立")
        changephase = True
    # debug：チェック無しでＰ１へ移行する（For TEST）
    print("=>Ｐ１へ")
    changephase = True

# Ｐ１：初期化
def p1_init():
    global orderprice
    orderprice = 0
    nowpossize = FlyLib.get_allpossize()
    print("[Phase-1]：買い集め処理")
    print("買い注文: 購入予定最大数{:.3f}BTC / 購入完了しきい数量{:.3f}BTC  建玉数:{}BTC".format(p1_buyvolume, p1_bordervol, nowpossize['BUY']))

# Ｐ１：買い処理
def p1_exec():
    global changephase, orderprice, watchprice
    time.sleep(0.2)
    # 建玉チェック
    nowpossize = FlyLib.get_allpossize()
    if nowpossize['BUY'] >= p1_bordervol:
        print("\r\n=>買い完了(建玉予定数{:.3f}BTC->建玉完了{:.3f}BTC)".format(p1_buyvolume, nowpossize['BUY']))
        changephase = True
        return
    # 注文
    lineclear = False
    if orderprice == 0: # 注文実行
        p = FlyLib.calc_price(True, p1_checksize, p1_checkboardrange)
        if p[0] == 0:
            st = "買い注文保留中({}枚の買板に{}以上の板が無い)".format(p1_checkboardrange, p1_checksize)
        else:
            watchprice = p[0]
            watchsize = p[1]
            orderprice = watchprice + p1_buypricediff
            ordervolume = p1_buyvolume - nowpossize['BUY']
            #########################
            # Real Order
            r = FlyLib.send_order(True, orderprice, ordervolume)
            #########################
            # Dummy Order (for TEST)
            """
            class dummyorder:
                status_code = 200
            r = dummyorder
            """
            #########################
            if r.status_code != 200:
                is_halt = True
                return  # 異常系
            st = "(約定{:.3f}/{:.3f})監視{}({:.3f})=>買い[{}({:.3f})]待ち.".format(nowpossize['BUY'], p1_buyvolume, int(watchprice), watchsize, int(orderprice), ordervolume)
            lineclear = True
    else:   # 注文解除判定
        # 「買い指値」より上にNビット以上の大きさの買い板が出されたら、注文取り消し
        # 「買い指値」の直下の買い板がNビット以下に変更されたら、注文取り消し
        if FlyLib.chk_board_price(True, p1_checksize, orderprice) == True:
            st = "取消(注文より上にsize{}以上の板が出現)".format(p1_checksize)
            FlyLib.reject_order()  # 全ての買い注文をキャンセルする
            time.sleep(0.2)
            watchprice = orderprice = 0
        elif FlyLib.chk_price_size(True, watchprice)[1] < p1_checksize:
            st = "取消(監視板{}がsize{}未満に変化)".format(watchprice, p1_checksize)
            FlyLib.reject_order()  # 全ての買い注文をキャンセルする
            time.sleep(0.2)
            watchprice = orderprice = 0
        else:
            st = "."
            #nolf = True
    if lineclear == True:
        print(' '*120 + '\r', end = "", flush=True)
    print(st, end="", flush=True)

# Ｐ２：初期化
def p2_init():
    global orderprice, waitflg, waitstopdate
    orderprice = 0
    waitflg = False
    # test code
    #waitflg = True
    #waitstopdate = datetime.datetime.today() + datetime.timedelta(seconds=p2_pause_wait_time)
    # test code
    FlyLib.reject_order()  # 全ての買い注文をキャンセルする
    print("[Phase-2]：売り抜け処理")

# Ｐ２：売り
def p2_exec():
    global changephase, orderprice, watchprice, waitflg, waitstopdate
    # 建玉チェック
    nowpossize = FlyLib.get_allpossize()
    if nowpossize['BUY'] == 0:
        print("=>売却完了")
        changephase = True
        return
    # 高値売買停止チェック
    #300秒以上前の直近高値（初期値1,000,000）を記憶しておき、
    #直近高値まで300円に迫ったら、売買を20秒停止する。
    if waitflg == False and immediate_high_price <= hist[0]['price'] + p2_pause_check_price:
        print("※現在{}:直近高値({})まで{}円以内に迫りました。売買を{}秒間停止します（売り注文は一旦解除）。".format(int(hist[0]['price']), int(immediate_high_price), p2_pause_check_price, p2_pause_wait_time))
        FlyLib.reject_order()  # 全ての買い注文をキャンセルする
        waitflg = True
        waitstopdate = datetime.datetime.today() + datetime.timedelta(seconds=p2_pause_wait_time)
        return
    # 注文
    lineclear = False
    # 売買20秒停止中処理
    if waitflg == True:
        if datetime.datetime.today() >= waitstopdate:
            waitflg = False
            st = "{}秒経過、再開。".format(p2_pause_wait_time)
        else:
            time.sleep(0.5)
            st = "."
    elif orderprice == 0: # 注文実行
        p = FlyLib.calc_price(False, p2_checksize, p2_checkboardrange)
        if p[0] == 0:
            st = "売り注文保留中({}枚の売板に{}以上の板が無い)".format(p2_checkboardrange, p2_checksize)
        else:
            watchprice = p[0]
            watchsize = p[1]
            orderprice = watchprice - p2_sellpricediff
            ordervolume = nowpossize['BUY']
            #########################
            # Real Order
            r = FlyLib.send_order(False, orderprice, ordervolume)
            #########################
            # Dummy Order (for TEST)
            """
            class dummyorder:
                status_code = 200
            r = dummyorder
            """
            #########################
            if r.status_code != 200:
                is_halt = True
                return  # 異常系
            st = "(買残{:.3f})監視{}({:.3f})=>売り[{}({:.3f})]待ち.".format(nowpossize['BUY'], int(watchprice), watchsize, int(orderprice), ordervolume)
            lineclear = True
    else:   # 注文解除判定
        # 「売り指値」より下にSビット以上の大きさの売り板が出されたら、注文取り消し
        # 「売り指値」の直上の売り板がSビット以下に変更されたら、注文取り消し
        if FlyLib.chk_board_price(False, p2_checksize, orderprice) == True:
            st = "取消(注文より下にsize{}以上の板が出現)".format(p2_checksize)
            FlyLib.reject_order()  # 全ての買い注文をキャンセルする
            time.sleep(0.2)
            watchprice = orderprice = 0
        elif FlyLib.chk_price_size(False, watchprice)[1] < p1_checksize:
            st = "取消(監視板{}がsize{}未満に変化)".format(watchprice, p2_checksize)
            FlyLib.reject_order()  # 全ての買い注文をキャンセルする
            time.sleep(0.2)
            watchprice = orderprice = 0
        else:
            st = "."
    if lineclear == True:
        print(' '*120 + '\r', end = "", flush=True)
    print(st, end="", flush=True)

# main
# 開始時初期化処理
phase = -1
cnt = 0
changephase = True
print("-----------------------------------------------")

while True:
    # 約定履歴を最新データに更新
    get_new_history_data()
    # 直近高値更新
    calc_immediate_high_price()
    # フェーズ変更判定
    if changephase == True:
        if phase == 2 or phase == -1:
            p = p0_init()
            if p < loss_border:
                print("STOP, over loss.")
                break
            phase = 0
        elif phase == 0:
            p1_init()
            phase = 1
        elif phase == 1:
            p2_init()
            phase = 2
        changephase = False
    # 各フェーズ実行
    if phase == 0:
        p0_exec()
        # debug
        changephase == True
    elif phase == 1:
        p1_exec()
    elif phase == 2:
        p2_exec()
    # 異常停止チェック
    if is_halt == True:
        print("異常停止")
        break
print("system stop.")
