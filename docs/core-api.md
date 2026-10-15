# 核心 API 與資料規則

開發前先讀 [專案指引](../AGENTS.md)及 [開發文件](development.md)；後續功能以 [TODO.md](../TODO.md)為準。以下描述目前已實作的介面，不代表待辦功能已可使用。

核心僅使用 Python 標準函式庫。`Decimal` 精度為 60 位；輸出 payload 的金額、數量與比例均序列化為字串，比例為小數分數。未定義的比例為 `null`，不以零替代。

## 離線預檢 API

`preflight.preview_update(project, request, now=None)` 只讀正式專案，在系統私有暫存目錄建立 SQLite 備份副本及必要來源／快取副本，重用正式匯入器與對帳。回傳 schema_version、status、sources、checks、pending_checks、blockers、預計截止及 BTC 數量；不提交正式資料、operation 或報告，不呼叫公開下載。`render_preview(result, locale="zh-TW")` 產生所選語言摘要；CLI 的 `--json` 輸出相同結果。

`core.inspect_holdings(project, csv_path, kind)` 唯讀使用與 import_holdings 共用的 `_holdings_plan`，檢查格式、去重、基準／修訂及帳戶，無 FX 也可檢查；不初始化正式庫。缺 FX 的新快照僅用已解析日期作暫存 base_override，沒有假 FX 或假持倉估值，simulation_complete 為 false。`workflow.select_context(..., base_override=None)` 是共用時間選擇；正常流程不傳 override。

`fx.read_saved_rates` 與 `prices.read_saved_quote` 為共用的離線參考讀取器。沒有精確快取回傳 None，有卻不合法則拒絕；正常 resolve 函式仍可在缺快取時下載。預檢只能呼叫離線讀取器。支援 verified JSON 的同一有效性／證據規則，不生成新行情。

預檢不暴露新暫存 ID，JSON issues 只列 code／severity／message；不輸出完整訂單、錢包地址、交易 reference 或帳號。blocked 為退出碼 2，其餘為 0，但 pending_checks 仍可包含行情、最新 ETF 或報告發布。正式更新必須重新驗證；preview 不是可提交作業，輸入或資料並行改變時拒絕當作有效預覽。詳見手冊第 20 節。

## BTC 報告成本推估

`btc_performance.btc_cost_estimate(crypto)` 是無 I/O 共用純函式，使用 80 位 Decimal，讀取 `crypto.cost_estimate_policy`。正常新 payload 明確設定公開預設 `actual_only`；舊已保存 payload 沒有該欄位時保留舊版重播語意，不代表新專案預設代理。

`actual_only` 回傳 `method=actual_costs_only`、`status=proxy_disabled`，保留已知購入量／支出／參考均價／市值資訊，但 `estimated_cost_cad`、`estimated_gain_cad`、`estimated_return` 為 None。`bull_average_proxy` 以已完成 Bull CAD 支出／購入 BTC＋LBTC 等值計算參考均價，再套用目前全部量，回傳 `method=bull_average_applied_to_all_btc` 及估算成本／損益／比例。兩者都不修改輸入或資料庫。

代理包含期初及未解釋差額，對帳仍獨立。無購入時沒有均價、估算成本／損益；有均價但零持倉時估算成本／損益為零、比例 None。只有新已完成購入改均價，餘額／事件只改適用量。實際 book／avg_cost／unrealized、供款及期間報酬不以代理回填。`btc-cost-estimate.json` 記錄所選政策及結果，發布檢查依該政策核對三格式、公式與附件。

`wallet_reports.quantity_basis_label(crypto)` 共用數量來源標籤，不修改核心 quantity_status 或觀測。期初聲明的 reference_as_of 與估值時間相同且 reported_total 與目前量相符時，可顯示當時回報基準；之後推估不得冒充新回報。正式 wallet anchor 分別顯示同時間回報及其後推估；無 anchor 的已知事件仍用帳本推算。異動／費用涵蓋與成本推估、數量來源分開。

```python
from pathlib import Path
from wealth_ledger.core import (
    initialize, import_holdings, make_payload,
    import_cash_flows, mark_flow_period,
)

initialize(project)
result = import_holdings(project, csv_path, kind="baseline", fx=fx)
payload = make_payload(project, snapshot_id=result["snapshot_id"])
```

`project`、`csv_path` 使用 `Path`。資料庫路徑固定為 `data/db/portfolio.sqlite3`，檔案權限為 `600`。一般 SQLite 沒有密碼或檔案加密；權限不等同加密。

## 匯入持倉

`kind` 接受 `baseline`、`monthly`、`interim`。首期自動成為基準；拒絕早於追蹤起點的回填，以及另指定較晚日期為新基準。CSV 必須有帳戶、證券、數量、價格、成本、市值、幣別欄位及 `As of YYYY-MM-DD HH:MM GMT±HH:MM` 檔尾。時間轉為含時區 ISO 字串，另外保存 UTC 供排序及相同時間辨識。

`fx` 必須含：

```python
fx = {
    "usd_cad": "1.4", "usd_twd": "30",
    "usd_cad_date": "2024-06-28", "usd_twd_date": "2024-06-28",
    "usd_cad_source": "https://example.test/cad",
    "usd_twd_source": "https://example.test/twd",
}
```

上述是合成 API 範例，不是可用於真實交易的匯率。核心要求匯率為正、有效日期不晚於快照、來源非空；官方來源查詢與過期政策由 FX 模組負責。匯率隨快照保存，不因後續重複匯入傳入新值而更改。

- 原檔 SHA-256 相同即去重；正常化數字、資料排序及 UTC 日期後內容相同也去重。
- 同一資料時間的不同內容建立新修訂；舊快照及來源保留。修訂繼承同一期的快照類型。
- 原始 CSV 封存於 `data/raw/holdings/YYYY/MM/`，權限為 `400`。相同檔名、不同內容加雜湊後綴，不覆寫。
- 帳戶 ID 為帳號的 SHA-256 前 16 位；公開資料僅有遮蔽帳號。來源原檔仍保留完整資料。
- 證券鍵為 `MIC:Symbol:Currency`；現金鍵為 `cash:Currency`。相同帳戶與證券重複列會拒絕。
- 僅支援 LONG、CAD／USD 市值；其他方向／幣別會拒絕，以免漏算。
- 核對數量乘市價及原幣成本／損益，容許差額為 0.01。超過差額標記問題，保留來源數值。
- 現金 CAD 帳面成本不參與市值換算；異常成本保留並標記，不修補。
- 首期以來源帳戶作為預期範圍；之後缺少已知帳戶則不完整。帳戶退出／關閉尚未自動推定。新帳戶可匯入，但不同帳戶範圍的總組合比較會暫停。

回傳 `status` 為 `imported`、`revision` 或 `duplicate`，並含 `snapshot_id`。新增／修訂另含 `revision`、`is_complete`、`issues`、`source_path`；重複回傳既有 `fx_preserved`。

## 報告 payload

`make_payload(project)` 預設最新資料時間、最新修訂；指定 `snapshot_id` 可以讀取保存的舊修訂。來源雜湊不符或檔案遺失會在問題清單顯示；資料庫保存值不被改寫。

| 鍵 | 內容 |
|---|---|
| `meta` | 快照 ID、時間、種類、修訂、完整性、缺漏帳戶、帳戶／證券／持倉／現金列數、起始時間、使用幣別、正式及歷史快照 IDs |
| `fx` | 六個 FX 輸入鍵及 `cad_twd` |
| `source` | 原始檔名、相對封存路徑、檔案與語意雜湊、列數、匯入時間、`integrity_ok` |
| `accounts` | 帳戶原幣小計、三幣等值、已列現金、現金比例、持倉數與組合權重 |
| `positions` | 分帳戶證券持倉；不含現金 |
| `securities` | 跨帳戶同證券合併；數量、成本及損益相加，平均成本／損益率重新計算，合併市價為市值除數量 |
| `cash_rows` | 已列現金，與持倉相同基本欄位；保留來源成本 |
| `totals` | `native_cad/native_usd/total_cad/total_usd/total_twd`、現金小計、分原幣非現金成本及未實現損益 |
| `instrument_types` | 個股、ETF、現金等來源工具類型的市值與組合權重 |
| `matrix` | 帳戶欄位及每證券的 CAD 等值／帳戶內權重；現金另列並有 `is_cash` |
| `concentration` | `largest`、`top3_cad/top5_cad/top3_weight/top5_weight`；分母含現金 |
| `history` | 每個實際觀測時間最新修訂的總值及帳戶值；保留完整性旗標，不每日補值 |
| `changes` | 與上一實際觀測的比較，包含前／後時間、三幣值變化、帳戶與持倉數量／市值／市價／權重差異 |
| `comparisons` | `previous`、`previous_month`、`baseline`；均使用 `changes` 的結構 |
| `cash_flows` | 真實已匯入資金流，含帳戶名稱與來源檔名／路徑／雜湊 |
| `periods` | 前期及基準至本期的 CAD 資金流調整分析，個別帳戶及總組合分開 |
| `issues/findings` | 結構化問題清單／繁體中文摘要字串 |

前一正式月度點為早於本期月份、最近的 `baseline/monthly` 快照。`official_snapshot_ids` 每個月份選最後一個正式點。報表必須保留／檢查 `is_complete`，不能把部分資料當成完整總資產。沒有適用前期或帳戶範圍不同時，比較有 `available=False` 與原因。

## 資金流與完整性

CSV 必要欄位：`date,account_id,flow_type,currency,amount`。金額為正數，方向由類型決定。建議提供穩定 `flow_id`；省略則由正常化內容產生。類型為 `deposit,withdrawal,transfer_in,transfer_out,income,fee,internal`。

- USD 流量需有正的 `usd_cad`、`fx_date`、`fx_source`，或提供正的 `amount_cad` 及其 `fx_source`。每筆換算值凍結，不能使用本期匯率取代。
- 轉移需要 `transfer_id`。相同日期、不同帳戶、相同 CAD 等值的一進一出才配對；缺腿、重複腿或差額會暫停期間績效。
- 同一 ID 同內容去重；同一 ID 不同內容拒絕。第一版尚未提供資金流修訂／作廢 API，不能以另一 ID 直接加入更正後的同一筆流量，否則會重複計入。
- `income/fee/internal` 不算外部投入。帳內保留股息及費用已反映於估值，不再加減一次。轉移於個別帳戶為流量，在組合層抵銷。

```python
import_cash_flows(project, activity_csv)
mark_flow_period(project, "2024-05-31", "2024-06-30", "complete")
mark_flow_period(project, "2024-06-30", "2024-07-31", "no_external")
# A specific account declaration can be provided using account_id.
```

期間狀態為 `partial/complete/no_external`；未標記時為 `not_provided`。標記是使用者對期間涵蓋的明確聲明，不從沒有檔案推定零資金流。相鄰月度聲明可合併支持從基準起算的期間；任何未涵蓋日期區段或明示部分資料會阻止績效計算。同範圍較新聲明優先，帳戶專屬聲明優先於組合聲明。組合的零外部流量聲明容許帳戶間轉移，個別帳戶的零外部流量聲明則不容許該帳戶的轉移。

期間必須有兩個不同日期估值；目前使用日期及期末日流量慣例，首日流量不包含，末日流量包含。應確認日期涵蓋與快照時點一致；只有日期的紀錄不能精確描述日內流量。

只有完整估值、相同組合範圍、完整 ledger、有效轉移配對時才產生：

```text
Investment gain = Closing value - Opening value - Net external contributions
Modified Dietz = Investment gain / (Opening value + Weighted flows)
Flow weight = Calendar days from flow date to period end / Period calendar days
```

XIRR 使用期初值作一次負值、投入為負、提領為正、期末值為正，365 日年化；未把追蹤開始前的投入重複計入。數值解有範圍檢查；多次符號變化的流量序列保守地不回報 XIRR，顯示 `ambiguous_cash_flow_signs`。Modified Dietz 是近似值，並非有每筆外部流量估值的精確 TWR。USD／TWD 僅顯示等值歷史，沒有直接借用 CAD 的報酬率。

## 測試

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

測試只使用模擬 CSV，臨時專案建立於 `work/`；不讀取使用者資料或寫入正式資料庫。涵蓋原幣／現金／FX 合計、去重、修訂、缺帳戶、月度／基準比較、資金流日期權重、轉移、來源完整性與未定義比例。

## Bull Bitcoin 與合併估值

`crypto.import_bull_orders(project, csv_path, source_account='bullbitcoin-main', opening_assumption=metadata)` 新增 `crypto_accounts`、`crypto_sources`、`crypto_order_revisions`，保留原始 CSV。首次必須明示零期初；已完成訂單的經濟數值及時間不允許無聲改寫。只支援 CAD Funding／Buy Bitcoin，三個狀態均 Completed 且完成時間在截止內才計入。

`crypto.make_crypto_view(project, as_ofISOtimestamp)` 回傳 Decimal 字串的入金、買入成本、BTC／LBTC 原始交付量、合計 BTC 等值、CAD 差額、實際事件月份及遮罩訂單。`Funding` 來源未分類，不自動成為全組合外部資金流；沒有生成缺月持倉。ADDRESS、TRANSACTION_ID、MESSAGE、完整訂單 ID 不出現在展示資料。

`combined.make_combined_payload(project, snapshot_id=None, *, as_of=None, price_file=None, fx=None, source_updates=None, btc_cost_policy=None)` 另建 `combined_observations`。組合範圍不同另立基準；原 Wealthsimple snapshots／positions 保留。BTC 以 CAD 估值代理加入總額與分類，從券商原幣持倉表排除。相同內容重產不新增觀測，修正同一時間資料保存新修訂。

`prices.resolve_btc_price(project, as_of, override=None)` 使用 Coinbase BTC-USD 最後完整一分鐘的 close，快取原始證據與 SHA-256，重產時不再下載。沒有可用完整價格／證據時停止，不以最後買入價或零代替估值。

不同截止與 Wealthsimple 原始時間會明示舊市價並標示不完整。合併期間報酬須先補齊 Bull 資金來源分類、轉移及錢包費用／餘額資料與完整性；餘額／異動介面已實作，目前僅保留已確認的 Wealthsimple 帳戶期間績效。`meta.missing_official_months` 標示觀測範圍內欠缺完整正式快照的月份。


## 自動來源更新 API

```python
from wealth_ledger.workflow import identify_inputs, prepare_update

sources = identify_inputs([Path("any.csv")])
payload, result = prepare_update(project, [Path("holdings.csv"), Path("orders.csv")])
```

`identify_inputs` 依必要欄位辨識，拒絕未知／模稜兩可格式及同來源多檔。`prepare_update` 負責匯入與自動估值時間：股票採 `As of`，Bull 單獨更新採執行時間，兩者含較晚 Bull 訂單時採執行時間。沒有輸入檔則沿用最近保存合併估值。`now` 可注入含時區的時間供離線測試；正式 CLI 使用系統時間。

合併 `meta.source_updates` 保存來源更新狀態及實際日期；`meta.data_status` 為 `sources_updated`、`carried_source`、`mixed_dates` 或 `btc_only`。`account_coverage_complete` 與 `is_complete` 分開：前者為來源帳戶涵蓋，後者另要求同步更新及估值時間一致。BTC 未有觀測時按固定期初、完成購入及已知淨異動推估；有觀測時按適用回報量加其後已知淨異動，獨立核驗狀態仍另列。合併歷史保存此狀態，沿用來源以虛線顯示，股票曲線使用獨立 `wealthsimple_history`。

首次只有 Bull 可產生限定資產範圍的報告；股票尚未提供時 `snapshot_id=None`，新增股票後另立 scope，不把範圍擴增當成投資增值。`as_of` 可進階覆寫，但 `snapshot_id` 不能搭配新輸入檔。


## 官方 ETF 成分與公司分析 API

`fund_sources.fetch_fund(fund_id, directory, today=None)` 使用基金市場識別（例如 XTSE:FBTC），回傳持倉日期、最新查詢狀態、全部成分權重和不可覆寫原始證據。日期、基金識別、分頁數量與權重型別嚴格檢查；BMO 原始 allocation 是小數，其餘目前來源是百分數。Vanguard 使用官方 delayeredHoldings 並完成分頁。只取得公開發行商資料。

`lookthrough.calculate(payload, funds, aliases)` 是無網路／資料庫副作用的 Decimal 計算核心：識別公司、遞迴穿透、循環偵測、合併曝險、已知非公司／未知／四捨五入對帳；保留 top20、完整公司、計算來源、未解析項目及 `classification`；計算版本為 `company-exposure-2`。證券身分與公司別名明確分開。

`lookthrough.attach_analysis(project, payload, run_id=None, fetcher=fetch_fund)` 正常查詢所有根／子基金，獨立保存 fund_sources、lookthrough_runs 與來源關聯，附到 payload.lookthrough。失敗不復用舊快取；可注入 fetcher 離線測試。指定 run_id 時驗證資產估值指紋一致並離線重播，不觸碰資產歷史或資金流。

`lookthrough_reports` 將共同計算結果轉換為 PDF／Markdown section、ODS 公式附表、完整公司與未解析 CSV、來源 JSON。CLI publish 在所有報告生成前附加分析；manifest 記錄 run_id。離線官方格式樣本僅供測試，不當作最新行情。

## 官方分類 API

`fund_sources.holding(..., gics_sector=None, icb_sector=None, issuer_sector=None)` 分別保存明確 GICS、ICB 及未確認體系的發行商產業；`country` 保留官方國別。Vanguard 查詢兩種分類欄位，先讀公開基金頁面設定 cookie 再呼叫官方分頁介面；不需要帳戶登入或 LLM。解析版本為 `issuer-holdings-2`。未知欄位保持空字串，不能用 generic sector 自動補成 GICS。

`classification.calculate_classification(analysis, components, funds, identities, securities)` 是無 I/O 的 Decimal 計算，版本 `official-classification-1`；由 `lookthrough.calculate()` 調用。`components` 包含 `source_fund`、原始 `gics_sector/icb_sector/issuer_sector/official_country`。先採 own_official_row，再按同公司最新有效日轉用；同日衝突為 `conflicting_latest_official_classification`，未找到為 `no_official_classification`。國別代碼與地理對照表在同模組，未知代碼不推測。

`payload.lookthrough.classification` 保存三維度 `dimensions`（完整 rows、兩種 coverage、日期範圍）、逐公司 `components`（原始分類及 assignments/evidence）、凝縮 `root_groups` 係數、`root_coverage`、分母與 policy/version/status。每維度合計必須等於 investment_total_cad；已解析股份、未知股份、非公司及調整分開，不正規化公開權重。相同根持倉跨幣別先合併，避免係數重複。

`classification_reports.report_section()`、`workbook_tables()` 及 `write_exports()` 共用該結果；前兩者由既有報告層調用，後者被 `lookthrough_reports.write_exports()` 連動。輸出新增 `allocation-exposure.csv` 與 `classification-detail.csv`，後者 assignments JSON 包含日期、官方網址、來源基金、狀態與方法。完整 CSV 為 UTF-8 BOM、比例為小數分數。三張 PNG 由 `reporting._charts()` 生成，ODS 與 MD／PDF 共用。

分類隨既有 `lookthrough_runs.payload_json` 保存，沒有 schema 遷移。`attach_analysis(..., run_id=...)` 保留同估值指紋檢查：舊保存分析缺 classification 時仍可重播原報告，新版直接離線重播已凍結分類，不重新套今日資料。manifest 的可選 `classification` 含版本、狀態、各維度覆蓋／日期與新增匯出檔名。正式金融歷史及資金流不因分析刷新而新增。


## 使用 Bull 前的期初量與未知實際成本

`crypto_opening.import_opening(project, json_path, source_account='bullbitcoin-main')` 讀取明示的全部錢包 BTC＋LBTC 總量，按 `reference_as_of` 計算已完成 Bull 購入，將差額固定保存為使用者指定的 pre-Bull 量。有限、非負、satoshi 精度、時區及範圍必須有效；低於購入量拒絕。同 source_account／來源 SHA-256 重交為 duplicate，不隨新訂單重算。需要已匯入且來源完整性通過的 Bull 帳本。

原始 JSON 按聲明日期及雜湊唯讀封存。新增 `crypto_opening_revisions(id, source_account, revision, payload_json, source_path, source_sha256, created_at)`，每個來源／revision 唯一，追加而不改原 `crypto_accounts.opening_json`。CLI 匯入前自動 SQLite 備份。`latest_opening(..., cutoff=None)` 唯讀取得最新修訂並核對原始來源 SHA-256。`applies_from` 為已提供 Bull 訂單的追蹤邊界，不是推定取得日期；更早截止不套此筆期初。此介面不回建歷史買入或市值。

payload 記錄 reported_total_btc_equivalent、reference_purchased_btc_equivalent、opening_btc_equivalent_qty、declared_on、reference_as_of、applies_from、basis、confirmed_by 及參照原始 CSV。cost_cad、historical_contribution_cad 均為 null，network_distribution 為 unknown；wallet_fees_accounted 為 false。

`make_crypto_view()` 新增 opening、purchased_btc_equivalent_qty、opening_btc_equivalent_qty；btc_equivalent_qty 為固定期初加完成購入。qty_btc／qty_lbtc、monthly 與原始 orders 仍只描述 Bull 購入。期初沒有新增 Funding、Buy、cash_flows 或偽造交易月份。

`combined.py` 保留市值及三幣換算，但未知期初成本時完整 CRYPTO 的 book_native／book_cad／avg_cost／unrealized_native／unrealized_pct，以及受影響原幣成本／損益合計均為 null。valuation 額外保存 known_bull_cost_cad、opening_market_cad、bull_purchase_market_cad 及 cost_status。`_partial_summary` 僅用於合併視圖，不改券商成本邏輯。ODS 持倉資料及組合分析必須以未知文字呈現相關實際欄位，不用 SUMIFS 的零值表示已知完整成本。選用 `bull_average_proxy` 時，BTC 主表另用上節 btc_cost_estimate 的全持倉推估，不覆寫實際 payload。

組合 scope_id 納入 opening_revision_id；補登及更正另立比較基準，舊 combined_observations 與舊報告保存。沒有新 CSV 的重產沿用最後估值時間、凍結價格與匯率；新增資產改變估值指紋，須重新取得官方 ETF 分析，不能套用舊指紋的 frozen replay。

## BTC 餘額／異動與操作 API

`wallet.add_balance(project, amount, as_of, source=..., time_basis=..., replaces=..., now=...)` 保存全部錢包 BTC＋LBTC 等值；同時刻去重，數量衝突須明確修訂。`wallet.add_event` 需 type、quantity_btc、occurred_at、source、reference，可選 balance_id；零淨量 own_transfer／conversion 不扣持倉。

`wallet.revise(... expected_revision, reason, action)` 追加修訂；kind 的身分欄位不可改，錯誤身分作廢後替代。records／get_record／balance_detail／revision_history 為唯讀。`wallet.make_crypto_view(project, cutoff, strict=True)` 包裝原 Bull 帳本；回傳 anchor、reconciliations、events、完整帳本預期及待釐清狀態，觀測後事件才加到回報量。未知歷史／負持倉／封存完整性矛盾可停止估值。

`operations.atomic_data` 以隔離暫存庫驗證既有匯入器，再用單一 SQLite 交易安裝資料；來源檔案保持原樣，資料失敗不留下部分正式紀錄。`execute_update` 分資料提交與報告發布兩階段；request、result、固定截止、輸入指紋及發布結果在 update_operations。resume 使用保存 inputs，不重讀原 CSV；參考覆寫 JSON 另封存。輸入修訂使未發布作業過期；published 作業重試直接回傳結果。

唯資料 API 本身不發布報告；CLI 使用 project_lock、事前備份及 operation 記錄。直接使用 mutating API 的呼叫端須自行安排備份／互斥及整批操作。prepare_update 可接 accepted 已提交輸入；正式 update CLI 不以它直接逐筆提交外部輸入。API／CLI 全部不用 LLM。

新錢包表第一次寫入時建立：wallet_records 保存穩定身分與來源唯一鍵，wallet_revisions 保存追加來源聲明，wallet_links 以外鍵保存異動修訂與指定／前一餘額關聯，wallet_balance_slots 限制同範圍、同 UTC 時刻只有一筆有效觀測。顯示層按 America/Toronto 呈現，SQLite 及原始聲明仍保留 UTC／原始時間，時間依據 explicit／execution_time 另列。

`crypto.monthly_purchase_price(row)` 以 Decimal 計算 buy_cost_cad／buy_btc_equivalent_qty，數量為零回傳 None。make_crypto_view 的 monthly 列保存 average_purchase_price_cad_per_btc（Decimal 字串／null），報告層沿用同一計算口徑；不改原始交易或建立新資料庫欄位。


## 報告呈現發布檢查

`report_checks.validate_report_presentation(payload, output)` 使用既有 pypdf、標準函式庫 XML／JSON／Decimal，核對 ODS／MD／PDF 的有效期初、總量、已知 Bull 成本、未知實際完整成本／損益、依成本政策適用的 Bull 均價推估數字／公式／附件、數量來源及費用涵蓋、錢包差額可用性。未知成本的持倉資料及組合分析列不得有數值或公式；有效零數量／零差額保持數字。原假設不得出現在已有後補期初的日常報告；另存 btc-opening-audit.json 並核對原假設和有效聲明與 payload 完全一致。無 crypto 回傳 not_applicable，成功回傳 passed／checks／policy，失敗拋出 ValueError。

`reporting.generate_reports()` 額外回傳 supplements 檔名清單，存在獨立期初時產生 btc-opening-audit.json；包含 report_as_of、原始假設、有效聲明、數量／現金假設狀態及成本政策，不更改 payload／SQLite。publish 在既有公式檢查後、移動 bundle 或更新 latest 前呼叫發布檢查；manifest 記錄 presentation_validation 與 reporting.supplements；presentation_validation.btc_cost_policy 記錄本次實際選用政策，policy 區分實際成本限定與 Bull 均價代理檢查。失敗沿用 operation 固定截止重試政策。

## 本機成本政策與未來來源介接

`settings.btc_cost_policy(project, override=None)` 依明確 override、本機設定、公開預設 `actual_only` 的順序解析；未知政策及非法 TOML 拒絕。忽略的 `config/local.toml` 可用 `[reporting] btc_cost_policy` 選擇 `bull_average_proxy`；`scripts/update.py --btc-cost-policy` 明確覆寫。此設定只控制報告展示，不改原始金融資料、歷史實際成本或供款。`combined.make_combined_payload` 在金融觀測保存後附加 `crypto.cost_estimate_policy`；切換展示政策不新增資產觀測。`workflow.prepare_update(..., btc_cost_policy=None)` 傳遞選項，CLI 在 request 保存解析後政策供 operation 重試，不因其後本機設定變動改寫該作業口徑。參考例在 `config/local.example.toml`。

目前股票／Bull CSV 辨識仍是已知兩種格式的流程；ETF 官方資料則有 `fund_sources.REGISTRY`。它們不是通用任意來源 plugin 系統。未來來源 adapter registry／protocol 的資料種類、偵測衝突、命名空間與 canonical records 契約尚待實作，見 [來源介接規劃](source-adapters.md)及 TODO；目前不能以任意銀行或交易所 CSV 取代支援來源。


## 語系呈現 API

`settings.report_locale(project, override=None)` 純讀取 CLI／本機設定／新舊專案預設；`ensure_report_locale_setting(project)` 僅用於正常加鎖作業保存預設。無效語系在金融提交前拒絕，舊專案保留 zh-TW，新專案 en-CA。

`i18n.presentation_context(locale)` 用 ContextVar 隔離語言；`tr(key, **parameters)` 驗證具名參數。`display_payload(payload)` 深拷貝呈現欄位，不修改 financial payload。`SourceText` 保留來源原文。`validate_catalogs()` 驗證所有 key／參數一致。字型與 catalog SHA、格式／渲染版本由 context.metadata() 提供。

`generate_reports(..., locale=...)`、`build_workbook(..., locale=...)`、`render_preview(..., locale=...)` 使用相同資源；Python 直接呼叫未傳 locale 時保留既有 zh-TW 相容預設。CLI 入口另按專案設定解決預設。`verify_workbook`／`validate_report_presentation` 未指定 locale 時讀取 ODS metadata；舊 ODS 缺 metadata 時維持繁中。公式用穩定 sheet ID 轉為實際表名。

`editions.render_language_edition(source, output, locale)` 僅讀保存 bundle，輸出新版本；data.json 原位元不變，不存取帳本／網路／latest。manifest 記錄原 checksum／金融指紋與新呈現版本；舊 manifest 缺 checksum 時明列較弱的 metadata consistency。詳見 [語系契約](i18n-plan.md)。
