# BTC 餘額與異動對帳：設計契約

狀態：BTC 餘額、異動、修訂及作業重試已實作。本文件是通用資料契約，不包含任何使用者的餘額、基準或驗收歷史。操作命令見 [使用手冊第 19 節](user-manual.md#19-btc-餘額異動與差額對帳)。

實際歷史成本／供款未知時不能推定；公開預設 `actual_only`。明確選用 `bull_average_proxy` 才另外提供全持倉代理估算，差額仍保留對帳。數量來源、費用涵蓋與成本政策獨立，詳見 [手冊第 13 節](user-manual.md#13-bull-bitcoin購入與供款追蹤)。

命令中的數量、過去日期、B000001／E000001 均為合成示例，須替換為真實資料。舊期初聲明不得轉成新的查看紀錄。

## 1. 範圍與既有資料

- 正式執行全由 Python 處理；不使用 LLM、錢包自動登入或 LibreOffice。
- 回報的是全部納入追蹤錢包的 BTC＋LBTC，按 1:1 BTC 等值；不接受 CAD／USD 市值代替數量。交易 CSV 的原始網路／交付種類繼續保存。
- 輸入總量、Wealthsimple CSV、Bull CSV 各自可選；總量不要求同時提供 CSV。
- 固定期初、Bull 訂單、錢包餘額觀測及錢包異動為不同紀錄，不互相覆寫。新餘額不能再次當成期初。
- 既有聲明與固定期初保留；不能把舊聲明轉成今天的餘額，也不假設它有精確查看時間。
- 未知的實際成本與歷史供款仍未知；選用 `bull_average_proxy` 時全持倉均價推估另行展示，不回填實際成本。BTC 數量對帳完成不會自動啟用合併組合報酬、Modified Dietz 或 XIRR。
- 第一期支援一個固定的全部錢包範圍；更換涵蓋範圍須另立範圍基準，不以新總量悄悄加入／移除錢包。
- 新專案只有餘額也可開始數量及估值追蹤：建立獨立錢包範圍，沒有 Bull 帳本時不捏造零期初、購入史或 Bull 現金。首次餘額以前的帳本預期量／供款／成本未知；日後加入 Bull 須明確處理歷史重疊，不能直接把全部累積購入加到首次餘額。

## 2. 日常輸入與時間選擇

| 本次輸入 | 行為 |
|---|---|
| 任一 CSV／兩份 CSV，沒有新餘額 | 沿用既有來源辨識、交易去重及估值時間政策；已有餘額錨點時，BTC 由錨點加後續已知淨異動推估 |
| 只有 BTC 總量 | 保存新的餘額觀測；股票／Bull 沿用已保存資料，保留原來源日期 |
| BTC 總量＋任一 CSV／兩份 CSV | 先納入同批有效資料，再按同截止對帳；每份來源各自保留時間 |
| 沒有任何新輸入 | 重產最近保存估值時間的報告，不假造今天的餘額或歷史點 |

新增選項：`--btc-balance`、`--btc-balance-as-of`、`--btc-balance-source`。最後一項預設 `user_reported_total`，可補人類可讀的來源說明。

- 數量使用整數 satoshi／Decimal，最多八位小數；零合法，負數、NaN、Infinity 及超精度不合法。異動數量規則另見第 5 節。
- 有總量、沒有觀測時間：使用本次執行開始時捕捉的同一時間，顯示為「未另指定，採執行時間」，不宣稱曾讀取錢包。請提供真正查看時間以提高品質。
- 觀測時間與異動時間均須含 UTC offset；儲存 UTC 及原始輸入，顯示 America/Toronto。相同 UTC 時刻視為同一時刻。拒絕未帶時區或未來觀測／異動時間。
- 沒有新總量時，既有 CSV 工作流的預設估值政策不變。
- 有新總量、沒有明確估值時間時：預設取「既有工作流候選估值時間、最新保存估值時間、新餘額觀測時間」中的最晚時間。新觀測一般會新增估值點；回補較舊餘額只修訂適用的保存估值，不讓最新時間倒退。
- `--valuation-as-of` 若明確提供，控制報告時間，不修改觀測時間。不得用該報告時間以後的餘額、已完成訂單或異動來推算當時資產。
- 舊餘額可以先保存；不自動補所有舊月末報告。明確要求歷史估值時，只選不晚於截止的已保存 Wealthsimple 快照；若沒有適用股票快照，停止該合併報告並說明原因，不把較新股票倒灌至過去。
- 不允許 `--btc-balance-as-of`／`--btc-balance-source` 單獨出現；不能把新餘額與 `--wealthsimple-only`、`--snapshot-id` 或 `--lookthrough-run-id` 混用。後兩者用於已保存資料的重播。
- 餘額單獨更新不宣稱為股票／Bull 同步的完整月度快照；正式／臨時分類繼續保留來源完整度與沿用狀態。
- 新估值須有適用的價格／匯率；舊股票仍按原快照金額顯示沿用。正常 ETF 更新仍查詢最新官方公布資料，只有相同估值指紋才可離線重播保存分析。

## 3. ID、查詢與修訂

| 紀錄 | 穩定 ID | 修訂 |
|---|---|---|
| 餘額觀測 | `balance_id`，例如 B000001 | `balance_revision`，原始內容永遠保留 |
| 經濟異動 | `event_id`，例如 E000001 | `event_revision`，更正／作廢均追加修訂 |
| 對帳結果 | 餘額 ID＋相關觀測／帳本修訂版本 | 區分當時記錄值與目前重算值 |
| 匯入／報告作業 | `operation_id` | 保存接受資料、截止時間及發布狀態，供重試 |

ID 不隨更正、報告版號或後補 CSV 改變；永不重新使用。CLI 回傳 ID、修訂、觀測時間、預期量、差額及對帳狀態；報告也顯示餘額 ID。

已實作命令：

```bash
.venv-portable/bin/python scripts/btc_balances.py list
.venv-portable/bin/python scripts/btc_balances.py show B000001
.venv-portable/bin/python scripts/btc_events.py list --balance-id B000001
.venv-portable/bin/python scripts/btc_events.py show E000001
```

- 相同範圍、UTC 時刻及相同數量：重交為重複，不新增觀測；來源說明不同時須明確補充／修訂，不能假裝是第二個同時刻餘額。
- 相同時刻卻不同數量：拒絕悄悄覆寫，要求 `btc_balances.py revise` 明確指定原 ID。
- 同數量、不同查看時間：合法的新觀測。省略時間再次執行會是新的查看聲明；要重試同一次作業，使用 operation ID，不能靠再次省略時間去重。
- 餘額數量／來源更正用 `revise`；時間／範圍是觀測身分的一部分，誤填時先 `void` 再新增正確觀測，保留兩者關聯。
- 異動更正用 `revise`、取消用 `void`，不新增反向假交易。修訂要求 `--expected-revision` 及 `--reason`，避免以舊資料覆寫較新修訂。
- 異動的來源＋reference 是身分，`revise` 不改身分；來源 reference 錯誤時作廢原紀錄，再建立明確替代紀錄。數量、類型、時間及關聯修訂須重新驗證所有受影響區間。
- 同一餘額數量改正後，連到該穩定 ID 的異動不用換 ID，系統重算。新增較早觀測或作廢造成區間變動時，原連結若不再適用，明示「關聯待重查」，不悄悄指向另一筆餘額。

## 4. 數量模型與差額

對時間 T，先找不晚於 T、仍有效、同範圍的最新餘額觀測 B。

```text
Q(T) = B.quantity + sum(known net changes where B.time < occurred_at <= T)
```

沒有 B 時，沿用既有固定期初＋已完成 Bull 購入＋有效已知異動。餘額獨立啟動的新專案在首筆觀測以前沒有可用推估量。

- 餘額是該時刻已完成異動之後的數量；同一時刻的異動計入該觀測對帳，不再次計入觀測後推估。若實際先後不明，應修正查看時間或先保持差額未解釋。
- 每筆餘額另計算「區間預期量」：首筆由既有固定期初與同截止已知異動得出；後續由上一有效回報餘額＋兩次觀測間的已知淨異動得出。
- `residual = reported_quantity - expected_quantity`。正值代表多於預期，負值代表少於預期。數量不採金額四捨五入容差；一 satoshi 差額仍顯示。
- 系統另外保存「固定期初＋全部已知異動」的完整帳本預期量及總差額，供稽核。不能因重新採用回報餘額作錨點，就宣稱舊差額已解釋。
- 首次輸入時的預期量／差額凍結保存；後補資料另產生目前重算結果，可看出為何改變。
- 無原因也接受餘額，按回報數量估值並標示「使用者回報；差額待釐清」。不推定為費用、供款、買賣或投資增值。
- 較新餘額與預期一致，不會結清較早觀測的未解釋差額；歷史待核對清單持續保留。
- 異動補登在錨點之前：重算適用區間的差額，不再扣／加目前回報量。異動在錨點之後：只在後續推估量計入一次。
- 若有效帳本推算出負持倉，不夾成零或掩蓋；標示數量矛盾，停止受影響的估值發布，保留診斷資料。
- 一般餘額更新／費用補登不另立組合範圍基準；即使 BTC 變成零，仍保留追蹤帳戶身分。真正範圍改變才另立基準。

## 5. 異動類型、證據及去重

| 類型 | 對 BTC 等值數量的影響 | 限制 |
|---|---|---|
| `fee` | 減 | 實際支付的 BTC 等值費用 |
| `sale` | 減 | 不自動創造收到的 CAD 現金、出售收入或已實現損益 |
| `spend` | 減 | 支付的本金，費用另列 |
| `external_out` | 減 | 移出追蹤範圍；不自動作成 CAD 提款 |
| `external_in` | 加 | 非 Bull 購入的外部移入；成本／是否供款另行分類 |
| `own_transfer` | 零 | 同一追蹤範圍自己的錢包轉移；填移動的總量作說明，費用另列 |
| `conversion` | 零 | BTC／LBTC 1:1 換網路；填轉換總量作說明，費用另列 |

所有異動的 `quantity_btc` 為正值；方向由類型控制。`sale`／`spend`／轉出數量不包含另列的費用；已有 Bull CSV 交付量扣過的費用不得再扣。

必要欄位：類型、數量、帶時區的 `occurred_at`、來源名稱 `source`、該來源內唯一 `reference`。來源與 reference 組成去重鍵；reference 可是交易／單據 ID，或使用者自行指定且不重用的紀錄代號。

- `source` 是來源說明，不是鏈上驗證。使用者聲明可補登但須標示為聲明；不把沒有附件／獨立核驗的 reference 說成已核驗交易。
- 同一去重鍵、相同經濟內容：重交不重記。內容不同：要求指向既有 `event_id` 的明確修訂。同秒同數量的兩個真實事件須有不同 reference，不能只以金額／時間判斷重複。
- 不以「金額相同」自動把 Bull 訂單與手動異動配對。Bull 購入缺漏應補 CSV，不以 `external_in` 代登；若發現原手動紀錄其實是 Bull 購入，先作廢誤分類紀錄，再匯入 CSV，保留替代關聯。
- 後補的 Bull 訂單若早於原期初聲明的購入截止，可能與當時推算期初重疊。系統須標示重疊待核對；不得默默把它加進固定期初之外，也不得自動重新扣算期初。需明確修訂期初證據／聲明後才宣稱完整帳本可對帳。
- 第一版支持單筆 CLI 及有固定欄位的 CSV 批次匯入。原始批次 CSV 原樣封存；CLI 產生封存 JSON。先前 YAML 範例只是欄位示意，本版不規劃 YAML 解析器。
- 任意正負 `adjustment` 或以差額自動生成費用不在第一版範圍。

## 6. 異動與哪次差額關聯

**`--balance-id` 必須從一開始就設計進補原因介面，不能靠「最新差額」猜測。**

- 想解釋特定觀測的差額：明確提供 `--balance-id`。系統查核 ID 存在、未作廢、範圍一致及時間適用。
- 單純先記一筆真實異動、尚無對應餘額：可省略 balance ID。系統按真實時間計入帳本，日後按時間區間對帳；不自行附上某個聲稱是使用者指定的餘額 ID。
- B 的補原因區間為 `(上一有效餘額時間, B.time]`；首筆從既有帳本適用範圍起至 B.time。早於追蹤適用範圍的異動不硬塞進本期。
- 指定的異動若超出該區間：拒絕該關聯並顯示可適用區間／觀測 ID；不更改異動日期來迎合差額。
- 同一異動是一筆全域經濟紀錄；balance ID 只建立解釋關聯，不能再加減一次。同一事件不能複製給多次差額。
- 已存在異動要補關聯：使用 `btc_events.py link E000001 --balance-id B000001 --expected-revision 1 --reason "Attribute to observation"`，不是再次 `add`。重新關聯須先明確 `unlink` 並留下原因。
- 部分說明允許；列出已補登說明及剩餘差額。超過原差額也不截斷或自動結清，而是顯示新的相反方向差額。零淨量轉移／換網路本身不能解釋非零差額。
- 區間差額為零只能表示「目前已知資料算術相符」；除非另有核驗紀錄，仍屬使用者回報／補登，不能標為獨立錢包驗證完成。

## 7. 操作範例（日期與 ID 須替換）

日常可省略觀測時間；若要保留真正查看時間，建議明確提供：

```bash
# Balance only
.venv-portable/bin/python scripts/update.py --btc-balance 0.07990000 \
  --btc-balance-as-of "2024-11-10T18:10:00-05:00"

# Either or both CSV files plus an optional balance
.venv-portable/bin/python scripts/update.py /path/to/holdings.csv /path/to/orders.csv \
  --btc-balance 0.07990000 --btc-balance-as-of "2024-11-10T18:10:00-05:00"
```

第一個例子的合成假設：當時預期 0.08000000，回報 0.07990000，差額 −0.00010000。輸出餘額 ID 假設為 B000001；先按 0.07990000 估值，差額待釐清。

稍後確認費用後：

```bash
.venv-portable/bin/python scripts/btc_events.py add \
  --balance-id B000001 \
  --type fee --quantity-btc 0.00010000 \
  --occurred-at "2024-11-10T18:00:00-05:00" \
  --source "wallet manual record" --reference "fee-20241110-001"

.venv-portable/bin/python scripts/update.py
```

費用在該餘額之前：區間預期改為 0.07990000、剩餘差額變零；該回報量不再扣成 0.07980000。最後一條命令重產最近估值的新報告版，保留舊版。

先記一筆在最近餘額之後的新費用，暫時不關聯：

```bash
.venv-portable/bin/python scripts/btc_events.py add \
  --type fee --quantity-btc 0.00001000 \
  --occurred-at "2024-11-12T09:00:00-05:00" \
  --source "wallet manual record" --reference "fee-20241112-001"

.venv-portable/bin/python scripts/update.py \
  --valuation-as-of "2024-11-12T09:00:00-05:00"
```

`btc_events.py add` 僅保存異動，不自行發布報告。若事件晚於最近報告時間，CLI 顯示目前報告未涵蓋該事件，並提示使用適用的新估值時間；裸 `update.py` 不會自動變成今天。新時間須能取得適用行情。

更正／作廢與批次範例：

```bash
.venv-portable/bin/python scripts/btc_balances.py revise B000001 \
  --quantity-btc 0.07991000 --expected-revision 1 --reason "Corrected transcription"
.venv-portable/bin/python scripts/btc_events.py revise E000001 \
  --quantity-btc 0.00009000 --expected-revision 1 --reason "Corrected fee amount"
.venv-portable/bin/python scripts/btc_events.py void E000001 \
  --expected-revision 2 --reason "Duplicate of imported transaction"
.venv-portable/bin/python scripts/btc_events.py import /path/to/btc-events.csv
```

餘額查看時間誤填時，使用唯資料命令作廢並建立替代紀錄；接著另跑 update。`btc_balances.py add` 不發布報告，也可供先保存歷史觀測使用。`--as-of` 必填，避免將更正當成今天的新查看：

```bash
.venv-portable/bin/python scripts/btc_balances.py void B000001 \
  --expected-revision 2 --reason "Incorrect observation time"
.venv-portable/bin/python scripts/btc_balances.py add \
  --quantity-btc 0.07991000 --as-of "2024-11-10T18:20:00-05:00" \
  --source "user reported total" --replaces-balance-id B000001
```

`--replaces-balance-id` 只能指向同範圍已作廢紀錄。異動身分誤填時同理，`btc_events.py add` 可用 `--replaces-event-id` 指向已作廢原異動；替代關聯僅供審計，不再次影響數量。

批次 CSV 欄位：

```csv
source,reference,type,occurred_at,quantity_btc,balance_id
wallet manual record,fee-20241110-001,fee,2024-11-10T18:00:00-05:00,0.00010000,B000001
```

手冊須同時提供「查 ID → 補原因 → 查看剩餘差額 → 重產報告」、漏 Bull 訂單、部分原因、多次觀測、同時間更正、來源重疊及零總量的完整範例。

## 8. 保存、發布與失敗重試

- 遷移／變更前 SQLite 備份；原始 CSV、CLI 聲明 JSON 與修訂來源依日期／雜湊封存，不覆寫。
- 已實作 SQLite 的餘額、異動、修訂、對帳關聯及作業狀態表；錢包表首次實際寫入才建立，外鍵／去重約束落在資料層，不只依 CLI 檢查。
- 同一 update 的輸入先全部解析及驗證，再以一個資料提交階段保存；使用共享交易或隔離暫存庫實作，不能把目前多個獨立匯入直接當成整批原子操作。資料驗證／提交失敗不留下部分有效正式紀錄；已封存但未採用的檔案以作業狀態識別。
- 資料提交與報告發布是兩階段。資料已保存但公開行情下載、計算或報告驗證失敗時，資料保留，明示「資料已保存，報告未發布」，輸出 operation ID、固定估值截止及錯誤。
- 待重試作業保存接受的 ID／修訂及估值截止；資料已有後續更正時，不默默重播舊狀態，提示作業已過期並要求以目前資料重新生成。
- 已實作 `update.py --resume-operation OPERATION_ID`：無需再次輸入總量或 CSV，不重新取「現在」作觀測時間，不重加異動。此選項不能與新輸入混用。
- 正常重試仍查詢最新官方 ETF 資料，成功後保存新證據；已取得的適用凍結價格／匯率重用。離線分析重播只允許完全相同估值指紋。
- 三種報告和核對全部成功才更新 `reports/latest.json`。舊報告、舊 payload、當時行情及對帳結果保留；後補資料產生新的報告修訂，不覆蓋舊版。
- 已提交且成功的同一 operation ID 重試回傳已保存結果，不另造觀測；待發布／失敗的作業列表與診斷可唯讀查詢。無參數重產仍使用最近保存估值時間，不悄悄處理未發布的新時間；CLI 顯示待發布提示。

作業查詢／重試介面亦屬本次設計，不留待實作後補：

```bash
.venv-portable/bin/python scripts/update.py --list-operations
.venv-portable/bin/python scripts/update.py --show-operation OPERATION_ID
.venv-portable/bin/python scripts/update.py --resume-operation OPERATION_ID
```

前兩者唯讀；三者不能互相混用或搭配新輸入。唯資料命令亦建立 operation 記錄，但明示不要求發布；其後的 update 是獨立發布作業。

## 9. 報告與狀態

ODS、Markdown、PDF 同一 payload；新增 BTC 對帳表，含 balance ID、查看時間、範圍、回報量、區間預期量、差額、已知原因及剩餘差額。完整帳本預期／原記錄對帳值及各異動 ID 另列審核明細。

- 最新估值列示採用的數量、最近餘額時間、之後已知購入／異動及資料日期差異。
- 狀態至少區分：無觀測的帳本推估、使用者回報、沿用餘額加已知異動推估、差額待釐清、部分說明、算術相符、來源／關聯矛盾。核驗層級另外列示。
- 舊未解釋區間不因有新觀測而消失；歷史曲線可呈現回報量對估值的影響，但不稱其為投資增值。
- BTC 數量圖區分 Bull 累積購入、回報餘額及推估持有量；沿用／混合日期總值仍明示。現有三幣總覽、公司／產業／地區分母同步採用本期適用數量。
- 成本未知不填零；費用／出售／外部轉出涉及成本分配而沒有可靠方法時，實際完整成本及損益維持未知；選用的 Bull 均價代理仍可估算，不能當成可靠實際成本分配。出售收到的資產未補入時，報告顯示涵蓋限制，不創造現金。
- 報告模板由程式條件產生；未回報新 CSV／餘額不代表沒有新活動。

## 10. 回歸驗收契約

1. 任一／兩份 CSV、餘額單獨、餘額搭 CSV、無輸入皆符合時間與沿用規則；無新資料不新增今日點。
2. 未知原因接受觀測且不創造交易／供款；零餘額合法，零帳戶仍保留範圍。
3. 費用早於錨點不再扣一次，晚於錨點只扣一次；等時刻按已完成異動處理。
4. 多次觀測保留舊未解釋差額，部分／超額原因準確重算；完整帳本與區間對帳不混淆。
5. 明確 ID 查詢、錯誤／作廢 ID、越界時間、改量修訂、改時間作廢重建及新前置觀測造成關聯失效。
6. Bull 漏單補入、手動重複、來源去重鍵衝突及原期初截止前訂單重疊，不雙計。
7. 同時刻去重、不同數量須修訂、同量新時間為新觀測；事件來源 reference 去重。
8. 未來資料不倒灌歷史，舊股票不冒充重新報價；八位小數、DST offset、無時區、負數及非有限值驗證。
9. 整批資料失敗回滾、資料成功但報告失敗、固定 operation 重試、過期 operation及最新報告指標不提前更新。
10. 舊資料庫遷移／舊報告保持可讀；既有測試回歸，新增隔離財務情境測試；三幣合計、ODS 公式／圖片及 PDF 受影響版面驗證。

以上情境應透過隔離合成資料回歸；執行目前 test suite 取得當輪結果，不引用某個使用者專案的測試總數或報告版本。金融規則修改需保存回歸證據；報告修改還需公式／結構及受影響 ODS／PDF 視覺檢查。

## 11. 文件與實作對應

修改本契約時同步 README、AGENTS、TODO、手冊、核心 API、報告規格、ODS 文件、CLI help 與模板。未實作部分不能寫成可用命令；私人工作階段細節與真實驗收資料放在忽略目錄。

### 實作對應

- wallet.py：整數 satoshi、餘額／異動追加修訂、來源 reference 去重、區間關聯與對帳。
- operations.py：隔離暫存資料庫整批提交、輸入修訂指紋、operation 查詢及報告重試。
- workflow.py：可選總量、單／雙 CSV、無輸入與歷史截止選擇。
- btc_balances.py／btc_events.py：唯讀查詢及有備份的資料操作。
- wallet_reports.py：共同對帳頁、ODS 公式及兩份審核 CSV；reporting.py 增加數量比較圖。
- 新專案首筆餘額以前保持未知歷史；後加 Bull 僅把錨點之後的購入計入推估，不把錨點以前購入加第二次。
- 明確更換全部錢包範圍、獨立鏈上核驗及歷史成本分配不在本版；不得用一般餘額更新暗中更換範圍。
