"""Compose broker observations and the separate crypto ledger without rebasing them."""
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import hashlib
import json

from .core import (_connection, _summary, _convert, _ratio, _serialize,
                   _json, _now, _changes, _missing_official_months, make_payload)
from .prices import parse_time, resolve_btc_price

D = Decimal
ZERO = D(0)
NUMERIC = ("quantity", "price", "book_native", "book_cad", "market_native",
           "unrealized_native", "market_cad", "market_usd", "market_twd",
           "avg_cost", "unrealized_pct", "account_weight", "portfolio_weight")


def _restore_view(view):
    result = deepcopy(view)
    result["totals"] = {k: D(v) if v is not None else None for k,v in result["totals"].items()}
    for record in result.get("accounts", [])+result.get("positions", []):
        for key, value in list(record.items()):
            if key in NUMERIC or key.startswith(("total_", "native_", "cash_", "book_native_", "unrealized_native_")):
                if value is not None:
                    record[key] = D(str(value))
    return result


def _nullable_ratio(numerator, denominator):
    return _ratio(numerator, denominator) if numerator is not None and denominator is not None else None


def _partial_summary(records, fx):
    sanitized = deepcopy(records)
    missing = set()
    for row in sanitized:
        for key, summary_key in [('book_native','book_native_'),('unrealized_native','unrealized_native_')]:
            if row[key] is None:
                missing.add(summary_key+row['currency'].lower())
                row[key] = ZERO
    result = _summary(sanitized, fx)
    for key in missing:
        result[key] = None
    return result


def _views(base, records):
    fx = base["fx"]
    totals = _partial_summary(records, fx)
    lookup = {a["account_id"]: deepcopy(a) for a in base["accounts"]}
    by_account = defaultdict(list)
    for record in records:
        by_account[record["account_id"]].append(record)
    accounts = []
    for aid, group in by_account.items():
        account = lookup.get(aid, {"account_id": aid, "account_type": "Bitcoin 自託管",
                                  "label": "Bitcoin 自託管（Bull 購入紀錄）", "masked_number": "—"})
        if any(r.get("cost_status")=="partial_unknown_opening" for r in group):
            account["label"]="Bitcoin 自託管（期初＋Bull 購入）"
        account.update(_partial_summary(group, fx))
        account["position_count"] = account["security_count"] = sum(r["security_type"] != "CURRENCY" for r in group)
        account["portfolio_weight"] = _ratio(account["total_cad"], totals["total_cad"])
        accounts.append(account)
        lookup[aid] = account
    for record in records:
        for key in NUMERIC:
            if record.get(key) is not None:
                record[key] = D(str(record[key]))
        values = _convert(record["market_native"] if record["currency"] == "CAD" else ZERO,
                          record["market_native"] if record["currency"] == "USD" else ZERO, fx)
        record.update({"market_cad": values["total_cad"], "market_usd": values["total_usd"],
                       "market_twd": values["total_twd"], "avg_cost": _nullable_ratio(record["book_native"],record["quantity"]),
                       "unrealized_pct": _nullable_ratio(record["unrealized_native"],record["book_native"]),
                       "account_label": lookup[record["account_id"]]["label"],
                       "account_weight": _ratio(values["total_cad"],lookup[record["account_id"]]["total_cad"]),
                       "portfolio_weight": _ratio(values["total_cad"],totals["total_cad"])})
    positions = [r for r in records if r["security_type"] != "CURRENCY"]
    cash = [r for r in records if r["security_type"] == "CURRENCY"]
    grouped = defaultdict(list)
    for record in positions:
        grouped[record["security_id"]].append(record)
    securities = []
    for sid, group in grouped.items():
        security = deepcopy(group[0])
        security.update({"account_id": None, "account_type": "ALL", "account_label": "全部帳戶",
                         "account_weight": None, "account_count": len(group),
                         "held_account_ids": [r["account_id"] for r in group]})
        for key in ("quantity", "book_native", "book_cad", "market_native", "unrealized_native", "market_cad", "market_usd", "market_twd"):
            security[key] = sum((r[key] for r in group), ZERO) if all(r[key] is not None for r in group) else None
        security.update({"avg_cost": _nullable_ratio(security["book_native"],security["quantity"]),
                         "price": _ratio(security["market_native"],security["quantity"]),
                         "unrealized_pct": _nullable_ratio(security["unrealized_native"],security["book_native"]),
                         "portfolio_weight": _ratio(security["market_cad"],totals["total_cad"])})
        securities.append(security)
    securities.sort(key=lambda r: -r["market_cad"])
    types = defaultdict(list)
    matrix_groups = defaultdict(list)
    for record in records:
        types[record["security_type"]].append(record)
        matrix_groups[record["security_id"]].append(record)
    labels = {"EQUITY": "直接個股", "EXCHANGE_TRADED_FUND": "ETF", "CURRENCY": "現金", "CRYPTO": "直接持有比特幣（估計）"}
    instruments = [{"security_type":kind,"label":labels.get(kind,kind),
                    "total_cad":sum((r["market_cad"] for r in group),ZERO),
                    "weight":_ratio(sum((r["market_cad"] for r in group),ZERO),totals["total_cad"]),
                    "position_count":len(group),"security_count":len({r["security_id"] for r in group})}
                   for kind,group in sorted(types.items())]
    rows = []
    for sid, group in matrix_groups.items():
        cells = {aid:sum((r["market_cad"] for r in group if r["account_id"]==aid),ZERO) for aid in lookup}
        rows.append({"security_id":sid,"symbol":group[0]["symbol"],"currency":group[0]["currency"],
                     "is_cash":group[0]["security_type"]=="CURRENCY","values":cells,
                     "weights":{a["account_id"]:_ratio(cells[a["account_id"]],a["total_cad"]) for a in accounts},
                     "total_cad":sum(cells.values(),ZERO)})
    rows.sort(key=lambda r:(r["is_cash"],-r["total_cad"]))
    concentration = {"largest":None}
    if securities:
        largest=securities[0]
        concentration["largest"]={"symbol":largest["symbol"],"currency":largest["currency"],
                                  "total_cad":largest["market_cad"],"weight":largest["portfolio_weight"]}
    for count in (3,5):
        value=sum((r["market_cad"] for r in securities[:count]),ZERO)
        concentration[f"top{count}_cad"]=value
        concentration[f"top{count}_weight"]=_ratio(value,totals["total_cad"])
    return {"totals":totals,"positions":positions,"cash_rows":cash,"accounts":accounts,
            "securities":securities,"instrument_types":instruments,"concentration":concentration,
            "matrix":{"accounts":[{"account_id":a["account_id"],"label":a["label"]} for a in accounts],"rows":rows}}


def _record(project, payload):
    view={k:payload[k] for k in ("totals","accounts","positions")}
    record={"as_of":payload["meta"]["as_of"],"kind":payload["meta"]["kind"],
            "is_complete":payload["meta"]["is_complete"],"scope_id":payload["meta"]["scope_id"],
            "wealthsimple_snapshot_id":payload["meta"]["snapshot_id"],"view":view,
            "source_updates":payload["meta"].get("source_updates"),
            "data_status":payload["meta"].get("data_status")}
    signature=hashlib.sha256(_json({"record":record,"crypto":payload["crypto"],"fx":payload["fx"]}).encode()).hexdigest()
    as_of_utc=parse_time(record["as_of"]).isoformat()
    with _connection(project) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS combined_observations(
          id INTEGER PRIMARY KEY, as_of_utc TEXT NOT NULL, revision INTEGER NOT NULL,
          signature TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
          UNIQUE(as_of_utc,revision))""")
        existing=conn.execute("SELECT * FROM combined_observations WHERE as_of_utc=? ORDER BY revision DESC LIMIT 1",(as_of_utc,)).fetchone()
        if not existing or existing["signature"] != signature:
            revision=(existing["revision"]+1) if existing else 1
            cursor=conn.execute("INSERT INTO combined_observations(as_of_utc,revision,signature,payload_json,created_at) VALUES(?,?,?,?,?)",
                                (as_of_utc,revision,signature,_json(record),_now()))
            current_id=cursor.lastrowid
        else:
            revision,current_id=existing["revision"],existing["id"]
        all_rows=conn.execute("""SELECT * FROM combined_observations WHERE id IN
          (SELECT MAX(id) FROM combined_observations WHERE as_of_utc<=? GROUP BY as_of_utc)
          ORDER BY as_of_utc,id""",(as_of_utc,)).fetchall()
    history=[]
    for row in all_rows:
        item=json.loads(row["payload_json"])
        if item["scope_id"] != record["scope_id"]:
            continue
        history.append({"snapshot_id":row["id"],"as_of":item["as_of"],"kind":item["kind"],
                        "revision":row["revision"],"is_complete":item["is_complete"],
                        "data_status":item.get("data_status"),"source_updates":item.get("source_updates"),**item["view"]})
    payload["meta"].update({"combined_observation_id":current_id,"revision":revision,
                           "baseline_as_of":history[0]["as_of"],"history_snapshot_ids":[r["snapshot_id"] for r in history]})
    current_view=_restore_view(view)
    def compare(prior):
        result=_changes(_restore_view(prior) if prior else None,current_view,
                        {"id":prior["snapshot_id"],"as_of":prior["as_of"],"is_complete":prior["is_complete"]} if prior else None,
                        {"as_of":record["as_of"],"is_complete":record["is_complete"]})
        if result["available"]:
            result["reason"]="相同資產範圍的估計市值變化；包含投入、匯率與 BTC 持有量估計，不是投資報酬。"
        return result
    previous=history[-2] if len(history)>1 else None
    official=[r for r in history[:-1] if r["kind"] in ("monthly","baseline") and r["is_complete"] and r["as_of"][:7]<record["as_of"][:7]]
    payload["comparisons"]={"previous":compare(previous),"previous_month":compare(official[-1] if official else None),
                            "baseline":compare(history[0] if len(history)>1 else None)}
    payload["changes"]=payload["comparisons"]["previous"]
    payload["history"]=[{k:v for k,v in item.items() if k != "positions"} for item in history]
    official={}
    for item in history:
        if item["kind"] in ("baseline","monthly") and item["is_complete"]:
            official[item["as_of"][:7]]=item["snapshot_id"]
    payload["meta"]["official_snapshot_ids"]=list(official.values())
    payload["meta"]["missing_official_months"]=_missing_official_months(history)
    return payload


def make_combined_payload(project, snapshot_id=None, *, as_of=None, price_file=None, fx=None, source_updates=None, btc_cost_policy=None):
    from .wallet import make_crypto_view
    with _connection(project) as conn:
        has_broker=bool(conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
    if has_broker or snapshot_id is not None:
        base=make_payload(project,snapshot_id)
    else:
        if as_of is None or fx is None:
            raise ValueError("BTC-only valuation requires an explicit timestamp and reference FX")
        base={"meta":{"snapshot_id":None,"as_of":as_of,"kind":"baseline","revision":1,
                      "is_complete":True,"missing_account_ids":[],"generated_at":_now(),
                      "base_currency":"CAD","display_currencies":["CAD","USD","TWD"]},
              "source":{"filename":"Wealthsimple 尚未提供","row_count":0,"sha256":"—","integrity_ok":None,"is_placeholder":True},
              "fx":fx,"accounts":[],"positions":[],"cash_rows":[],"securities":[],
              "totals":_serialize(_summary([],fx)),"history":[],"periods":[],"cash_flows":[],"issues":[]}
    ws_as_of=base["meta"]["as_of"] if has_broker else None
    target=as_of or ws_as_of
    if ws_as_of and parse_time(target)<parse_time(ws_as_of):
        raise ValueError("Combined valuation cannot predate its Wealthsimple holdings source")
    crypto=make_crypto_view(project,target)
    price=resolve_btc_price(project,target,price_file)
    payload=deepcopy(base)
    payload["wealthsimple_history"]=base["history"]
    payload["wealthsimple_totals"]=base["totals"]
    payload["meta"].update({"as_of":target,"wealthsimple_as_of":ws_as_of,"is_combined":True,
                           "quantity_status":"order_derived_estimate","generated_at":_now()})
    if fx is not None:
        payload["fx"]=fx
    mismatched=bool(ws_as_of and parse_time(target)!=parse_time(ws_as_of))
    if mismatched:
        payload["meta"]["kind"]="interim"
    synchronized=source_updates is None or all(source_updates[p]["status"]=="provided" for p in ("wealthsimple","bullbitcoin"))
    status="btc_only" if not has_broker else "mixed_dates" if mismatched else "sources_updated" if synchronized else "carried_source"
    payload["meta"].update({"is_complete":bool(base["meta"]["is_complete"] and not mismatched and (synchronized or not has_broker)),
                           "account_coverage_complete":base["meta"]["is_complete"],"data_status":status,
                           "source_updates":source_updates})
    quantity=D(crypto["btc_equivalent_qty"])
    unit_usd=D(price["close"])
    unit_cad=unit_usd*D(payload["fx"]["usd_cad"])
    cost=D(crypto["total_buy_cost_cad"])
    unknown_cost=D(crypto["opening_btc_equivalent_qty"])>0 or crypto['meta'].get('cost_unknown',False)
    cost_status="partial_unknown_opening" if D(crypto["opening_btc_equivalent_qty"])>0 else "unknown_wallet_cost" if unknown_cost else "known_purchase_cost"
    value=quantity*unit_cad
    valuation=_convert(value,ZERO,payload["fx"])
    crypto["valuation"]={"market_cad":valuation["total_cad"],"market_usd":valuation["total_usd"],
                         "market_twd":valuation["total_twd"],"unit_price_usd":unit_usd,"unit_price_cad":unit_cad,
                         "unrealized_cad":None if unknown_cost else value-cost,"price":price,
                         "cost_status":cost_status,
                         "known_bull_cost_cad":cost, "opening_market_cad":D(crypto["opening_btc_equivalent_qty"])*unit_cad,
                         "bull_purchase_market_cad":D(crypto["purchased_btc_equivalent_qty"])*unit_cad}
    payload["crypto"]=crypto
    aid=crypto["meta"]["account_id"]
    records=deepcopy(base["positions"]+base["cash_rows"])
    if quantity>=0:
        records.append({"account_id":aid,"account_type":"Bitcoin 自託管","account_label":"Bitcoin 自託管（Bull 購入紀錄）",
                        "security_id":"crypto:BTC-equivalent","symbol":"BTC 等值","name":"BTC + Liquid L-BTC（期初＋購入推算；未扣後續錢包費用）" if crypto.get("opening") else "BTC + Liquid L-BTC（購入推算；未扣後續錢包費用）",
                        "security_type":"CRYPTO","mic":"CRYPTO","exchange":"自託管","currency":"CAD",
                        "quantity":quantity,"price":unit_cad,"book_native":None if unknown_cost else cost,"book_cad":None if unknown_cost else cost,
                        "market_native":value,"unrealized_native":None if unknown_cost else value-cost,"valuation_currency":"CAD","asset_unit":"BTC",
                        "quantity_status":crypto['meta']['quantity_status'],
                        "cost_status":cost_status})
        if crypto.get('wallet'):
            records[-1]['name']='BTC + Liquid L-BTC（餘額觀測與已知異動；使用者回報）'
    cad_cash=D(crypto["cash_cad"])
    if cad_cash < ZERO:
        raise ValueError("Bull cash ledger is negative; supply missing funding before publishing a combined total")
    if cad_cash>0:
        records.append({"account_id":aid,"account_type":"Bitcoin 自託管","account_label":"Bitcoin 自託管（Bull 購入紀錄）",
                        "security_id":"cash:bull:CAD","symbol":"CAD","name":"Bull CAD balance（訂單推算）",
                        "security_type":"CURRENCY","mic":"","exchange":"Bull CAD balance","currency":"CAD",
                        "quantity":cad_cash,"price":"1","book_native":cad_cash,"book_cad":cad_cash,
                        "market_native":cad_cash,"unrealized_native":ZERO})
    payload.update(_views(payload,records))
    broker_ids={a["account_id"] for a in base["accounts"]}
    for account in payload["accounts"]:
        account["source_provider"]="wealthsimple" if account["account_id"] in broker_ids else "bullbitcoin"
        account["observed_as_of"]=ws_as_of if account["account_id"] in broker_ids else target
    payload["totals"]["broker_native_cad"]=D(base["totals"]["native_cad"])
    payload["totals"]["crypto_valuation_cad"]=value
    ids=sorted(a["account_id"] for a in payload["accounts"])
    scope={"accounts":ids,"crypto_account":aid}
    if crypto.get('opening'):
        scope['opening_revision_id']=crypto['opening']['id']
        payload['meta']['quantity_status']='opening_plus_orders_estimate'
    if crypto.get('wallet'):
        payload['meta']['quantity_status']=crypto['meta']['quantity_status']
    payload["meta"]["scope_id"]=hashlib.sha256(_json(scope).encode()).hexdigest()
    payload["meta"].update({"account_count":len(payload["accounts"]),"security_count":len(payload["securities"]),
                           "position_count":len(payload["positions"]),"cash_row_count":len(payload["cash_rows"])})
    # Existing brokerage returns remain brokerage-only. Funding provenance and
    # wallet balance/fee coverage cannot silently become complete global flows.
    payload["periods"]=[p for p in base["periods"] if p["scope"]!="portfolio"] if not mismatched else []
    payload["issues"].extend(crypto.get("issues",[]))
    payload["issues"].append({"code":"combined_return_coverage","severity":"info",
                              "message":"Bull 入金來源尚未分類為外部投入或已追蹤帳戶轉移；錢包費用及餘額尚未核對。暫不計算合併組合的期間報酬。"})
    if mismatched:
        payload["issues"].append({"code":"mixed_source_dates","severity":"warning",
                                  "message":f"Wealthsimple 持倉／市價仍是 {base['meta']['as_of']}；BTC 採 {target}。合計為不同日期資料，未將舊股票市價當成新觀測。"})
    if source_updates and not synchronized:
        payload["issues"].append({"code":"carried_source","severity":"info",
                                  "message":"部分來源沿用已保存資料；未提供新 CSV 不代表期間沒有交易。合計為估計總覽，不標成兩來源均已更新。"})
    if not has_broker:
        payload["issues"].append({"code":"btc_only_scope","severity":"info",
                                  "message":"Wealthsimple 尚未提供；本期僅涵蓋 BTC 與 Bull 現金紀錄，不代表全部個人資產。日後加入股票將另立組合範圍基準。"})
    payload["findings"]=[f"{'合併 Wealthsimple 與 Bull 購入紀錄' if has_broker else '本期範圍僅為 Bull 購入及現金紀錄'}；BTC + LBTC 合計 {quantity} BTC 等值，為未扣後續錢包費用的估計持有量。",
                         "CAD 計價的 BTC 是估值代理，不代表以 CAD 持有現金或 BTC 的原始交易幣別。",
                         "Funding CAD 入金與 Buy Bitcoin 購入使用同一筆資金，不相加為兩次供款。",
                         "新增資產範圍另建立合併追蹤基準；原 Wealthsimple 基準與報告保留。",
                         "ETF 與直接持有的 BTC 分開分類；未實現損益不是期間或年化報酬。"]
    if crypto.get('opening'):
        payload['findings'].insert(1,f"另含使用者補登的期初 {crypto['opening_btc_equivalent_qty']} BTC 等值；期初成本及歷史投入金額未知，不計完整 BTC 未實現損益。")
        payload['issues'].append({'code':'opening_scope_revision','severity':'info',
                                 'message':'補登先前未追蹤 BTC 後另立含期初持倉的比較範圍；舊估值與原 Bull 零期初聲明保留，新增資產不算投資增值。'})
    if crypto.get('wallet'):
        wallet=crypto['wallet']
        anchor=wallet['anchor']
        description=(f"採用使用者回報 {anchor['record_id']}（{anchor['as_of']}）及其後已知淨異動" if anchor else '採用固定期初、購入與已補登異動')
        payload['findings'][0]=f"BTC + LBTC 合計 {quantity} BTC 等值；{description}。尚未獨立核驗，舊差額不因新餘額消失。"
        payload['findings'].append(f"BTC 對帳共有 {wallet['unresolved_count']} 次觀測仍待釐清；未知數量差額不當作供款、費用或投資增值。")
    # Cost proxy selection is report metadata, not a new financial observation.
    from .settings import btc_cost_policy as resolve_policy
    selected_policy = resolve_policy(project, btc_cost_policy)
    result = _serialize(_record(project,payload))
    result["crypto"]["cost_estimate_policy"] = selected_policy
    return result
