# Wealth Ledger 使用手冊

本手冊描述已支援的操作契約。報告可選英文／繁體中文／簡體中文（第 21 節），程式碼及欄位名稱使用英文；所有數量、金額、時間及 ID 範例均為合成示例，不能直接套用到真實帳本。日期示例採過去時間，但仍須使用真實查看／入帳時間；報價來源也必須適用該截止。

日常使用：第 3 節更新持倉；第 5–8 節記錄供款與回補歷史；第 13 節處理 Bull CSV、平均買入價及全持倉推估；第 19 節提供可選 BTC 總量、按 ID 補原因及重試；第 20 節為不寫入正式資料的離線預檢；第 21 節為語言設定與離線重繪。開發規則見 [開發文件](development.md)及 [TODO.md](../TODO.md)。

## 1. 選定追蹤起點

新 clone 沒有任何使用者資料。首份有效 Wealthsimple 持倉 CSV 的 `As of` 時間成為股票追蹤基準；帳戶範圍由 CSV 決定，可包含支援的 TFSA、RRSP 與 Non-registered。只提供 Bull 或 BTC 總量也可開始相應的資產範圍，見第 13／19 節。原始檔、SQLite、凍結匯率、報告與備份全部保存在本機專案內。

這是資產的期初基準，不是當天的供款。基準資產已包含開始追蹤之前的供款及投資結果，不能再把整筆基準資產登成新的入金。只有一期資料時不能計算期間績效；沒有完整資金流也不能把市值變化當作投資報酬。BTC 的購入事件與市值觀測不足以啟用全組合期間報酬，仍須資金來源、轉移及涵蓋契約。

| 想知道的事情 | 必要資料 |
| --- | --- |
| 現在持有什麼、各帳戶多少錢 | 持倉 CSV 與凍結匯率 |
| 資產市值比上次增加多少 | 前後兩份完整持倉 CSV |
| 期間投入多少、提款多少 | 有日期及來源的資金流紀錄 |
| 扣除投入後的投資增值與期間報酬 | 前後估值、完整資金流及明確的完整性確認 |
| 開戶以來投入與績效 | 更早的完整資金流、可靠期初估值或開戶起點，及必要的歷史資料支援 |

## 2. 開始使用

正式流程全部由 Python 執行，不依賴 LLM、Codex、Node.js 或本機 LibreOffice。需要 Python 3.12 或更新版本。ODS 可用支援 OpenDocument 的試算表軟體閱讀；產生報告不需啟動任何辦公室軟體。

首次安裝（先安裝 Python 3.12+）：

```bash
git clone https://github.com/gh-slee/wealth-ledger.git
cd wealth-ledger
python3 -m venv .venv-portable
.venv-portable/bin/python -m pip install -r requirements.lock
```

本文多行命令採 Bash 語法；Windows PowerShell 請使用單行命令。Windows 可用 `py -3 -m venv .venv-portable`；後續命令的 Python 路徑改成 `.venv-portable\Scripts\python.exe`。例如：

```powershell
.venv-portable\Scripts\python.exe scripts/update.py --input C:\Downloads\holdings.csv --kind monthly
```

移機時保留私人專案資料並重建虛擬環境，勿直接搬用另一平台的環境。可先執行 `.venv-portable/bin/python examples/demo.py --output work/demo`，在隔離合成帳本產生報告；不讀取正式金融資料、不查行情。詳見 [合成示範](../examples/README.md)。

## 3. 每月更新流程

1. 在券商下載相同帳戶範圍、同一估值日的完整持倉 CSV。
2. 同時下載從上次快照到這次快照之間的活動紀錄；核對已完成的入金、出金及帳戶轉移。
3. 整理資金流 CSV 並匯入。資料尚未齊全時仍可先更新持倉，報酬會保持未提供。
4. 核對全部帳戶與期間後，明確聲明資金流完整性。
5. 匯入新的持倉 CSV，開啟新報告並查看資料品質與期間績效狀態。

正式月度快照：

```bash
cd wealth-ledger
.venv-portable/bin/python scripts/update.py \
  --input ~/Downloads/holdings-report-YYYY-MM-DD.csv --kind monthly
```

臨時觀測使用 `--kind interim`。每個月以最新的完整正式快照作月度比較點，所有臨時觀測及舊報告仍保存。日期使用 CSV 的 `As of` footer，不由檔名推定。已匯入的 `interim` 不會因重匯相同檔案並指定 `monthly` 而改成正式點；匯入時先選好類型。

重複匯入同一份 Wealthsimple 資料不會增加股票歷史快照。Bull 更新的估值時間規則見第 13.1 節。同一估值時間的不同內容會保存為修訂；新的估值時間即使持倉相同，仍是一個新觀測。不要手動改寫原始 CSV 的日期來製造歷史。

只重新產生報告，例如補入資金流後：

```bash
.venv-portable/bin/python scripts/update.py
```

不提供檔案時沿用最近保存的估值時間，即使執行日較晚也不建立新估值點。指定股票歷史快照時間可使用 `--snapshot-id 1`。重產報告會增加 `rNN`，不覆蓋舊報告。`reports/latest.json` 記錄最近成功產生的報告位置；支援符號連結的平台亦有 `reports/latest/`。

## 4. 如何取得 Wealthsimple 的資料

以下為下載方式指引；介面名稱可能調整，請以附列的券商官方文件為準。建議使用網頁版。

### 4.1 持倉、活動及年度供款核對資料

進入 **Profile → Documents → Generate document**：

| 文件選項 | 選擇方式 | 本工具用途 |
| --- | --- | --- |
| Holdings report (CSV) | 估值日與帳戶 | 正式持倉輸入 |
| Custom activity statement | 期間與帳戶，下載 CSV | 入金、出金、交易與轉移的來源 |
| Contribution confirmation statement | 稅務年度與適用註冊帳戶 | 年度供款總額核對 |

供款確認書不包含提款、前機構轉入的供款及同類型 Wealthsimple 帳戶間移動，不能取代完整活動紀錄。活動文件與供款確認書應交叉核對，而不是把兩者各匯入一遍。[Wealthsimple 官方文件](https://help.wealthsimple.com/hc/en-ca/articles/35654428540571-Request-a-custom-statement)

也可從網頁版 **Activity** 篩選帳戶、活動類型與日期，查看明細或下載活動 CSV；不明的手動調整應再對照月結單。[Wealthsimple 活動說明](https://help.wealthsimple.com/hc/en-ca/articles/39449252453019-View-your-account-activity-and-running-balance)

### 4.2 補足較舊紀錄

在 **Documents → Statements** 下載各帳戶月結單 CSV／PDF；亦可在 **Generate document → Bulk download monthly statements** 選期間與帳戶，批次下載 ZIP。若線上沒有需要的舊紀錄，可向 Wealthsimple 支援索取。[Wealthsimple 月結單說明](https://help.wealthsimple.com/hc/en-ca/articles/360056580894-Find-your-monthly-statements)

保存券商原始活動 CSV、PDF 與 ZIP 到 `data/evidence/wealthsimple/`，並在整理後的每筆資金流 `source` 欄填入來源檔名或相對路徑。資金流匯入器會另保存「整理後的 CSV」；不會自動取得 `source` 欄所指向的券商文件。勿刪除原始證據。

**目前支援範圍：** Wealthsimple 原生持倉 CSV 可以直接匯入；券商活動 CSV 尚未有自動轉換器，必須先整理成下一節的統一資金流格式。不要把原生活動 CSV 直接交給持倉或資金流匯入命令。流程也不會登入券商、同步帳戶或擷取登入憑證。

## 5. 供款、提款與轉移怎麼分類

本工具的「投入資金」是跨越**目前追蹤投資組合邊界**的資產移動。它與 TFSA／RRSP 的稅務供款概念不同；本版不計算 CRA 供款額度。

| 事件 | `flow_type` | 對整體組合的影響 |
| --- | --- | --- |
| 從未納入追蹤的銀行／現金帳戶入金 | `deposit` | 增加外部投入 |
| 從投資帳戶提款到未納入追蹤的帳戶 | `withdrawal` | 減少淨投入 |
| 兩個已追蹤投資帳戶間轉移 | `transfer_out` + `transfer_in` | 整體相抵，各帳戶仍有流入／流出 |
| 留在帳戶內的股息或利息 | `income` | 屬投資結果，不是新供款 |
| 在帳戶內扣除的費用 | `fee` | 減少投資結果，不是提款 |
| 買賣證券、帳內換匯等 | `internal` 或不登錄 | 不算外部投入 |

例如，未追蹤的 Wealthsimple chequing 帳戶轉入 TFSA，對本投資組合是 `deposit`；已追蹤的 Non-registered 轉入已追蹤 TFSA，則是成對轉移。後者可能涉及稅務供款或其他稅務事件，本工具的整體投入仍相抵。

從尚未追蹤的券商移入資產會改變追蹤邊界，不能因為文件寫著「transfer」就自動當作組合內部轉移。實物轉倉、跨日轉移、混合幣別與轉移費用需先核對估值及範圍；本版沒有專用自動處理流程，不要用原始買入成本代替移入當日市值。新增券商前先規劃帳戶範圍與資料轉換。

## 6. 建立並匯入資金流 CSV

先查看穩定帳戶 ID：

```bash
.venv-portable/bin/python scripts/cash_flows.py accounts
```

輸出包含 `account_id`、帳戶標籤與遮罩帳號。複製 `examples/templates/cash_flows.csv` 到自己的輸入檔，使用 UTF-8 CSV，並填入正確的 `account_id`。可以用試算表編輯，儲存時保留日期與交易 ID 的文字格式。

| 欄位 | 填寫規則 |
| --- | --- |
| `flow_id` | 強烈建議填穩定、全資料庫唯一的交易 ID；券商 ID 可加來源及帳戶前綴 |
| `date` | 必填，`YYYY-MM-DD`；使用已完成、實際入帳的日期並保持一致 |
| `account_id` | 必填，使用 `accounts` 命令輸出的 ID |
| `flow_type` | 必填，上一節列出的英文類型 |
| `currency` | 必填，目前只支援 `CAD`／`USD` |
| `amount` | 必填，正數、無千位逗號及貨幣符號；方向由類型決定 |
| `usd_cad` | USD 換算時的 CAD per USD；CAD 紀錄留空 |
| `fx_date` | 提供 `usd_cad` 時必填，不能晚於資金流日期 |
| `fx_source` | USD 必須有匯率或 CAD 等值的來源 |
| `amount_cad` | 可選；USD 可用有來源的 CAD 等值代替匯率換算 |
| `transfer_id` | 成對轉移必填，兩側共用同一 ID |
| `source` | 建議填券商文件／銀行證據的檔名或相對路徑 |
| `note` | 可選，保留核對所需備註 |

以下是**合成資料**；`ACCOUNT_ID_FROM_COMMAND` 必須替換，不能直接匯入正式資料庫：

```csv
flow_id,date,account_id,flow_type,currency,amount,source,note
example-deposit-001,2024-10-15,ACCOUNT_ID_FROM_COMMAND,deposit,CAD,2000,activity-october.csv,Example only
example-withdrawal-001,2024-10-20,ACCOUNT_ID_FROM_COMMAND,withdrawal,CAD,300,activity-october.csv,Example only
```

這兩筆的淨外部投入為 CAD 1,700。假設 USD 500、當日已核實 CAD per USD 為 1.40，可填 `usd_cad=1.40`、當日或最近適用的 `fx_date` 及來源，CAD 等值為 700；例子匯率不能直接套用真實交易。資金流換算不使用期末匯率。

成對轉移需要不同帳戶、相同 `transfer_id`、相同日期、CAD 等值相等，一側 `transfer_out`、另一側 `transfer_in`。不配對時期間報酬會被停用；不得為了通過檢查改寫真實入帳日期。

匯入：

```bash
.venv-portable/bin/python scripts/cash_flows.py import /path/to/cash-flows.csv
```

同一原始檔或相同穩定 `flow_id` 不會重複新增；同一 ID 的內容不同會拒絕匯入。本版不是以新 CSV 覆蓋舊資金流。未填 `flow_id` 時程式按內容產生 ID；更動日期、來源或備註可能產生不同 ID，所以不要靠改備註來更新已匯入紀錄。兩筆合法、內容相同的交易也必須用不同 ID 區分。

## 7. 確認期間資料完整

匯入資料與確認完整性是兩件事。程式無法知道你是否漏下載了某個帳戶或某一天。

假設兩份完整快照為 2024-05-31 與 2024-06-30，核對全部追蹤帳戶後：

```bash
.venv-portable/bin/python scripts/cash_flows.py coverage \
  --start 2024-05-31 --end 2024-06-30 --status complete
.venv-portable/bin/python scripts/update.py
```

上述日期為流程示範；只有真實下一份 CSV 使用該日期、並完成核對時才執行。邊界為 **`(start, end]`**：不包含起始日，包含結束日。首份基準日晚間以前的資金流已反映在基準資產內。

| 狀態 | 何時使用 | 是否提供投入調整後績效 |
| --- | --- | --- |
| `partial` | 已有部分紀錄，仍有缺漏 | 否 |
| `complete` | 已核對期間內全部相關資金流與帳戶轉移 | 是，其他估值與配對條件亦須通過 |
| `no_external` | 已核對並確認沒有外部入金／出金；內部轉移仍要完整記錄 | 是，其他條件亦須通過 |
| 未聲明 | 尚未提供或核對 | 否，不當作零 |

預設涵蓋全部已追蹤帳戶。若只核對一個帳戶，可加 `--account ACCOUNT_ID_FROM_COMMAND`；不代表整體已完整。最新完整性聲明會取代同範圍較舊聲明，帳戶專屬聲明優先；發現缺漏可以再聲明 `partial`。相鄰的完整月度期間可支援累計績效，任何缺口都會阻止累計計算。帳戶專屬 `no_external` 也不容許該帳戶有轉移流量；若有轉移，應使用 `complete` 並登錄兩側。

本版資金流只記錄日期。如果快照不是日終、同一天在快照前後都有資金流，不能精確按時間切分；先釐清邊界或選擇一致的日終快照，再確認完整性。相同日期的兩份快照不提供日期加權期間報酬。

## 8. 沒有追蹤過去供款，如何補資料

**建議以第一份可靠快照作基準，把之後每一期記完整；過去資料可平行整理。** 不需要先找回全部開戶歷史，才能追蹤下一個月的投資結果。

1. 從最早可取得的日期下載活動紀錄及各帳戶月結單，連同以前券商的紀錄一起保存。
2. 逐筆找出已完成的入金、出金及轉移，保留原始日期、幣別、金額與來源。銀行明細可核對外部入金／提款，但無法單獨確認投資帳戶間移動。
3. 用供款確認書或 RRSP 供款收據核對年度供款總額；它們不能補出每筆日期，也不能代替提款及轉倉紀錄。
4. 可核實的舊交易可使用資金流 CSV 匯入，保留原始日期。基準日及之前的紀錄會列在資金流清單，不會被算成基準之後的新投入。
5. 若只有年度總額而沒有逐筆日期，保存在來源證據及整理筆記中，標示「年度總額／日期未核實」；不要虛構 1 月 1 日或基準日的大額入金。
6. 缺月、缺帳戶、只有轉倉金額或有不明差額時，保留缺漏狀態。不要用「目前市值減成本」反推歷史供款。

| 找回的資料程度 | 能可靠回答的問題 |
| --- | --- |
| 只有基準及之後完整資料 | 追蹤開始後的淨投入、增值及可用期間報酬 |
| 只有以前年份的供款合計 | 已證實年份的供款合計；不能提供日期加權績效 |
| 有完整舊入金／出金，但沒有適用的歷史估值 | 可整理投入歷史；舊月度成長曲線仍不足 |
| 完整開戶資金流、轉倉處理與可靠歷史估值 | 可規劃開戶以來績效及歷史回補 |

現有報告的績效區間以已匯入快照為界。只補舊資金流不會自動把基準移到開戶日，也不會產生開戶以來 XIRR。程式會拒絕早於目前基準的持倉 CSV。需要回補舊持倉、建立零資產開戶起點、加入舊券商或處理轉倉時，應另規劃資料遷移與驗證，再變更目前基準。

CRA 資料可作 TFSA 供款紀錄的輔助核對，但不是即時來源；仍須對照各金融機構的紀錄。[CRA 官方說明](https://www.canada.ca/en/revenue-agency/services/tax/individuals/topics/tax-free-savings-account/contributing/before.html) 本工具的投資資金流不等於完整稅務供款台帳。

## 9. 報告怎麼閱讀

- `portfolio.ods`：含 BTC 的合併報告有十一個工作表，包含「比特幣追蹤」與「BTC餘額對帳」；券商專屬報告為九個。適合篩選、核對、公式試算與查看內嵌分析圖表。
- `report.pdf`：固定版面、嵌入所選語系字型，適合閱讀、保存及分享分析圖表。
- `report.md`：文字、表格與圖表連結，適合版本比較；移動時一併保留 `charts/`。
- `data.json`／`manifest.json`：同一輪報告的分析資料、來源及驗證資訊。

CAD／USD／TWD 總額是同一組資產的不同表示方式，不能相加。原幣持倉與成本另外保留 CAD／USD。各期匯率凍結保存，歷史值不被今日匯率改寫。

ODS 圖表採同輪報告的內嵌 PNG，每次執行更新流程會重新產生。圖片不依賴外部圖檔，也不會因閱讀軟體缺字型而改變標籤；但在 ODS 手動改公式時，圖像不會即時更新，也不能編輯圖表系列。需要新分析時，更新正式輸入並重新產生報告。

報告文字與「重點觀察」由程式中的固定說明、條件規則及資料模板產生，不呼叫 LLM。日期、金額、BTC 數量與比例依本期 payload 填入；來源沿用、混合日期、錢包未對帳及供款限制依實際狀態顯示。模板是在開發時寫入程式，執行時不需要 AI 重新撰寫。

目前合併報告的「重點觀察」以估值口徑及資料限制為主，不是每期生成的新市場評論或投資建議。文字主要位於 `src/wealth_ledger/combined.py` 與 `reporting.py`，ODS 的 `workbook.py` 使用同一份 findings；因此三種格式可以一致。若日後調整文案，應修改共同模板及相關文件，不只手改一份報告。

```text
Net external contributions = deposits - withdrawals
Investment gain = closing value - opening value - net external contributions
```

例如，資產從 CAD 100,000 增至 110,000，入金 6,000、無出金，則淨投入 6,000、投資增值 4,000；這不是 10% 投資報酬。投資增值包含價格、股息、帳內費用及 CAD 估值的匯率影響。內部轉移在整體組合相抵，但影響各帳戶的期間計算。

Modified Dietz 使用資金流日期加權，屬期間報酬估算；XIRR 是年化的金額加權報酬，短期間可能波動很大。資料不足、分母不適用或 XIRR 有多次現金流符號變化時，不強行顯示數值。持倉表的「未實現損益」只涉及目前仍持有部位，與追蹤期間總報酬不同。

## 10. 錯誤、更正與備份

| 狀況 | 處理方式 |
| --- | --- |
| CSV 缺必要欄位或 `As of` | 重新下載官方持倉 CSV，不手動偽造欄位或日期 |
| 少了一個已知帳戶 | 重新下載完整範圍；期間績效暫停，缺帳戶不歸零 |
| USD 資金流缺匯率來源 | 補入流入當日的已核實匯率或有來源的 CAD 等值 |
| 轉移未配對 | 查明兩側、日期及金額；不可改寫證據只求配對 |
| 找到漏登的新交易 | 保留其真正交易 ID，另匯入，再重產報告 |
| 已匯入交易金額／日期／帳戶錯誤 | 先聲明相關期間 `partial`；本版沒有資金流修改或作廢命令，需安排有備份的修訂或重建 |
| 原生券商活動 CSV 格式不符 | 先轉換成統一資金流格式；不可交給持倉匯入器 |

不要用新增一筆反向交易來抵銷資料輸入錯誤；那會扭曲日期加權績效。不要直接編輯 SQLite 或刪除原始檔。正式修改前須先保留目前資料庫與來源，再選擇匯入前備份或正確來源重建；目前沒有自動還原 CLI。

每次持倉或資金流匯入前會建立 SQLite 備份；成功產生報告後也備份。`backups/` 與資料在同一磁碟，不能替代另一磁碟或安全備份位置的專案備份。

SQLite 不加密、沒有密碼。本機檔案權限限制存取；來源、報告與備份仍包含敏感財務資訊。已列入 `.gitignore` 的資料不要上傳公開版本庫。

## 11. 檔案位置與日後券商支援

```text
docs/user-manual.md           This manual
data/raw/holdings/YYYY/MM/    Archived original holdings inputs
data/raw/activity/YYYY/MM/    Archived normalized flow inputs
data/evidence/wealthsimple/   Broker statements saved by the user
examples/templates/cash_flows.csv Blank normalized flow template
data/db/portfolio.sqlite3    Portfolio and flow history
data/fx/                    Frozen FX and public source evidence
reports/YYYY-MM-DD_HHMM/rNN/ Immutable report editions
reports/latest.json         Latest successful report pointer
backups/                    Database backups
```

未來券商採同一分析與報告層，新增「券商原始資料 → 統一持倉／資金流」轉換器。接入時需取得實際 CSV 範例及官方欄位說明，核對交易 ID、日期、幣別、撤銷、轉倉與帳戶識別，避免不同券商帳號碰撞、同一轉移重複計入，以及改變追蹤範圍時產生虛假增值。

目前其他券商原生持倉格式、Wealthsimple 原生活動自動轉換、多券商自動對帳、稅務供款額度及開戶以來自動回補均尚未實作。統一資金流格式已建立，未來轉換器可沿用；現階段的手動整理只限已建立的帳戶與已支援的 CAD／USD。

## 12. 驗證範圍

獨立 Python 環境已驗證匯入去重、修訂、供款、日期截止、三幣換算及隔離的第二期流程。ODS 公式快取使用獨立計算器核對；XML／套件清單以 ODF 1.2 schema 檢查。圖表改為內嵌 PNG，並內嵌繁體中文字型；已用隔離的 LibreOffice 閱讀環境驗證圖表與中文儲存格。這是開發驗收，正式產生流程仍不需要 LibreOffice。

開發測試不修改正式資料庫：

```bash
PYTHONPATH=src .venv-portable/bin/python -m unittest discover -s tests -v
```

## 13. Bull Bitcoin：購入與供款追蹤

### 13.1 匯出與匯入

在 Bull Bitcoin 的 Financials／訂單紀錄下載所有訂單 CSV。建議每次匯出完整歷史，或至少涵蓋上一次之後的全部活動；完整歷史重匯會去重。匯入器目前支援 CAD 入金及由 CAD Balance 買入 BTC／LBTC；原生 Bull CSV 的出售、不同付款形式及費用差額尚未支援，遇到時停止，不悄悄略過。獨立錢包費用／出售等可用第 19 節的手動異動介面補登；它不取代 Bull 原生訂單轉換。

日常只需把一份或兩份檔案交給同一個命令；程式依 CSV 欄位辨識，不靠檔名。兩個來源的順序不限，每次最多一份各來源的 CSV：

```bash
# Wealthsimple only
.venv-portable/bin/python scripts/update.py /path/to/holdings.csv

# Bull Bitcoin only
.venv-portable/bin/python scripts/update.py /path/to/orders.csv

# Both, in either order
.venv-portable/bin/python scripts/update.py /path/to/orders.csv /path/to/holdings.csv
```

| 情況 | 估值時間與資料使用 |
|---|---|
| 只提供 Wealthsimple | 採新的 `As of`；依固定期初／已知購入及異動或最近適用餘額推估 BTC，標示 Bull 資料沿用 |
| 只提供 Bull | 採執行時間（取整至分鐘），納入截止前已完成訂單並取得 BTC 價格；股票仍沿用最後快照的數量與原幣市價 |
| 同時提供兩者 | 通常採 Wealthsimple 的 `As of`；Bull 帳本有更晚完成訂單時自動改採執行時間，避免漏列新買入，股票日期仍明示 |
| 第一次只有 Bull | 產生 BTC／Bull 現金範圍報告，Wealthsimple 標示尚未提供；日後加入股票另立範圍基準 |
| 不提供任何 CSV，亦無新 BTC 總量／明確估值截止 | 重產最近保存估值時間的報告，不新增今日點 |
| 同日重交相同 Bull CSV，沒有新增內容 | 沿用當日已保存的適用估值點，避免一直增加重複點 |
| 隔日重交相同 Bull CSV | 可新增當日 BTC 價格估值點，購入量不變，不新增供款或交易 |

例如股票快照是 10 月 9 日，12 月 10 日只提交 Bull：程式會自動更新 BTC 的 12 月 10 日估值，但股票依然是 10 月 9 日持倉及原幣市價。當期匯率用於三幣換算；這是含不同日期來源的估計合計，不是 12 月 10 日的完整資產觀測，也不當成投資報酬。報告同時列各來源更新狀態與日期。

「最新已完成訂單日期」只是事件日期，不代表錢包餘額已核對，也不證明之後沒有活動。沒有新 CSV 時保留已知資料，明示沿用，不自動假設沒有交易。Bull 的月度入金／購入歷史按真實完成時間補入；股票實際歷史不被重新估值點改寫。圖表用虛線標示含沿用／不同日期資料的合計，股票帳戶線只使用原始快照。

原有 `--input`／`--bull-input` 相容。`--valuation-as-of` 現在是選用的進階覆寫，平常不用填：

```bash
.venv-portable/bin/python scripts/update.py /path/to/orders.csv \
  --valuation-as-of 2024-12-10T22:00:00-05:00
```

指定時間必須含時區，且不能早於所採用股票快照；只納入截止前已完成訂單。新時間沒有匯率／BTC 價格快取時需要網路，只查詢公開市場資料，不上傳投資檔。價格與匯率凍結後可重用同一金融估值；正常報告仍查最新官方 ETF 資料。完整離線重播須另指定相符的 `--lookthrough-run-id`，見第 15 節。

只看原本的 Wealthsimple 報告：

```bash
.venv-portable/bin/python scripts/update.py --wealthsimple-only
```

首次 Bull 訂單帳本匯入須明示該帳本範圍的期初 BTC、LBTC、CAD 均為零。先複製 `config/bull-opening.example.json` 到私人檔案，核對所有欄位及依據，再透過 `--bull-opening-file /path/to/private-bull-opening.json` 提供。公開示例不是任何使用者的聲明；程式不會替新 clone 自動採用零假設。已有使用 Bull 前持倉時，用第 18 節獨立補登有效期初量，不改原帳本聲明；不能無聲改變已保存假設。

### 13.2 數量與估值

總覽以 BTC ＋ LBTC 的 1:1 合計顯示「BTC 等值」。原始 BTC、LBTC 數量與交付網路保存，原始交付累計不等於現在各網路的錢包餘額。Liquid 與主鏈間的自動／手動轉換不在Bull 訂單匯出裡；它是自己資產間的轉移，不是再投入一次資金，但相關費用可能減少持有量。

尚無餘額觀測時，估計持有量＝固定期初＋CSV 中已完成的 BTC／LBTC 購入交付總量＋已補登淨異動。只有已補登的實際費用會扣除；未知後續費用不自行推定，估計量不標成獨立核驗錢包值。日期明確的餘額與異動介面已提供，見第 19 節；不能修改買入訂單來硬湊餘額。

BTC 價格採 Coinbase Exchange BTC-USD 在估值截止前最後完整一分鐘的 close，最多容許五分鐘時差，保存原始回應及雜湊。CAD／TWD 使用報告匯率換算；不使用截止時間之後的價格，也不拿最後一次買入價格代替當期市值。LBTC 採 BTC 1:1 價格作估值代理。BTC 的 CAD 是估值幣別，與原幣 CAD／USD 證券表分開。

「BTC 累積與每月投入」表的**平均買入價（CAD／BTC）**＝該月已完成 Bull 買入的 CAD 支出 ÷ BTC＋LBTC 交付等值數量。這是依交付數量加權的有效買入價格，不是各訂單報價的簡單平均，也不使用入金金額、累計量或本期估值價格計算。沒有購入的月份顯示不適用；只涵蓋該月已完成購入，不包含未知的 Bull 使用前取得成本或後續錢包費用。ODS 同欄用公式，正式更新由腳本自動重算。

有後補期初時，主要報告的「目前有效期初持倉（Bull 使用前）」列出實際固定 BTC＋LBTC 等值數量；不以原來的零假設代表有效期初。原 Bull BTC／LBTC／CAD 零值及完整聲明另存每份報告的 `btc-opening-audit.json`，不再放在日常 ODS／Markdown／PDF 中。原始紀錄不修改；此附件標明舊數量假設已由獨立期初聲明補充，原 CAD 現金依據仍保留。

Bull CSV 可計算已完成購入支出及對應平均買入價；**無法計算使用 Bull 前的實際取得成本或歷史投入**。例如合成帳本 Bull 購入 0.01000000 BTC 等值、支出 CAD 1,000.00，另有固定期初 0.00500000 BTC 等值。購入支出已知，期初實際成本未知，所以實際完整持倉成本／損益仍未知。工具預設 `actual_only`；可明確選用 `bull_average_proxy` 的「Bull 均價推估」欄位，但不能當作實際歷史成本。入金紀錄可另列，但不能由買入支出推定完整歷史外部供款。數量來源與異動／費用涵蓋分開呈現，規則見下方資料狀態。

### 全持倉成本與損益：Bull 均價推估

公開預設為 **`actual_only`**，不以後來購入單價填補未知實際成本。若要額外查看代理估算，可用 CLI 選項，或複製 `config/local.example.toml` 到忽略的 `config/local.toml`：

```bash
.venv-portable/bin/python scripts/update.py --btc-cost-policy bull_average_proxy
```

```toml
[reporting]
btc_cost_policy = "bull_average_proxy"
```

CLI 設定優先於本機 TOML；沒有設定採 `actual_only`。選擇 `bull_average_proxy` 後，主 BTC 表額外使用以下估算方式，不需另填取得成本：

```text
Reference average CAD/BTC = Completed Bull purchase spend / Delivered BTC+LBTC equivalents
Estimated holding cost CAD = Current BTC equivalents * Reference average
Estimated P&L CAD = Current market value CAD - Estimated holding cost CAD
Estimated return = Estimated P&L CAD / Estimated holding cost CAD
```

這個參考均價只從已完成 Bull 買入 CSV 計算，原始 BTC 與 LBTC 交付按 1:1 合計；期初量、新回報餘額、入金或手動費用都不改均價。新 CSV 增加實際完成購入時才重算加權均價，重複匯入不重計。

估算成本套用到**全部目前 BTC 等值數量**，包括固定期初及未解釋餘額差額。即使有待釐清差額，估算仍可顯示，對帳差額不消失。只有新總量時，參考均價不變，估算成本及損益按總量縮放；同估值價格、正數量及正均價下，損益率不變。若價格低於均價，更多數量會增加估算虧損的絕對金額，不一定讓損益改善。

例如 Bull 購入 0.06 BTC、支出 CAD 6,000，參考均價為 CAD 100,000／BTC。估值單價 CAD 120,000：

| 回報總量 BTC | 估算成本 CAD | 市值 CAD | 估算損益 CAD | 估算損益率 |
|---|---:|---:|---:|---:|
| 0.08 | 8,000 | 9,600 | 1,600 | 20% |
| 0.09 | 9,000 | 10,800 | 1,800 | 20% |
| 0.07 | 7,000 | 8,400 | 1,400 | 20% |

這些是推估值，沒有補齊期初的實際支出，也不把增加數量當供款或投資增值。出售／支付／費用後，推估仍套用同一參考均價，但不代表實際剩餘成本分配、已實現損益或交易費用已計算；那些功能仍需另補歷史資料及政策。無 Bull 已完成購入時沒有參考均價，不能計算推估；有參考均價但零持倉時，估算成本與損益為零，比例不適用。

啟用時 ODS／Markdown／PDF 明示「Bull 均價推估」，`btc-cost-estimate.json` 保存政策、方法、輸入及結果；`actual_only` 不顯示代理估算數字。`data.json`、持倉來源與組合分析的實際 book／avg_cost／unrealized 欄位仍保留原狀，不把推估加進全組合實際損益。既有完整實際成本、供款、期間績效仍依原完整性條件呈現。

每月數量圖表示實際完成訂單的累積購入量；不代表每個月的實際錢包餘額或歷史市值。新增估值時間可保存合併市值歷史點；含沿用來源或不同日期資料時清楚標示為估計，不列同步完整正式快照。原有 Wealthsimple 基準與報告保留。

### 報告中的資料狀態

- **有效數量**：採用適用的帳本、固定期初或餘額觀測與之後已知異動；後補等值不拆成未確認的主鏈／Liquid 數量，也不填入 CAD 成本或現金欄。
- **數量狀態與費用涵蓋**：如果有期初聲明，它保存當時回報的總量。報告時間與該參考時間相同且總量相符時，顯示「使用者回報基準總量（期初補登依據）；未獨立核驗」；之後沒有新回報時顯示基準＋已知購入推估。有另登餘額則區分當時回報及其後已知淨異動推估。費用涵蓋另列，只納入已提供紀錄，未知費用不自行估算或額外扣除；不代表已提供基準總量失效，也不將期初聲明重複寫成一次新觀測。成本的 Bull 均價推估與此數量來源分開。
- **Bull 已知購入成本**：從已完成訂單計算，正常顯示數字。**使用 Bull 前取得成本／歷史投入**：缺當時支出及來源時顯示未提供。
- **全持倉估算成本／損益／損益率**：選用 `bull_average_proxy` 時另外顯示，不能當實際歷史成本；預設 `actual_only` 不產生代理估算。實際完整成本不全時，其他實際欄位仍顯示未提供或未能計算並說明缺項。
- **錢包回報與帳本差額**：未提供日期明確餘額時顯示「未計算；尚未提供餘額觀測」；有觀測但帳本不足時顯示帳本不足。已知零差額仍列零，不當成缺資料。
- **零現金／零購入月份**：可以是有效資料；例如 Bull CAD 入金與買入支出相等，帳本剩餘現金為零，並不代表期初 BTC 為零。無購入月份的平均買入價為不適用。

每次正式產生報告，程式在發布前核對 ODS／Markdown／PDF 的有效期初與持倉、已知購入成本、缺失成本及對帳狀態，並核對稽核附件。若舊假設重新混入日常報告、有效數值與 payload 不符、缺成本變成數字或狀態不同步，會停止發布並保留上一份成功報告。可在 `manifest.json` 的 `presentation_validation` 查看結果；失敗按第 19 節 operation 流程查詢／重試，不重交總量。檢查不等於獨立核驗錢包或補齊歷史交易。

### 13.3 入金如何計算

`Funding` 是 CAD 進入 Bull balance，`Buy Bitcoin` 使用那筆餘額購買，兩者不能相加當成兩次供款。例如合成帳本入金 CAD 1,000、買入支出 CAD 1,000，推算 CAD 剩餘零；這不是 CAD 2,000 的投入或資產。實際值由各使用者自己的訂單計算。

對 Bull 帳戶而言可看到入金紀錄，但對全部追蹤資產而言仍要知道資金從哪裡來：

- 未追蹤銀行帳戶轉入：屬整體組合的外部投入。
- 已追蹤 Non-registered 轉出到 Bull：屬組合內轉移，不增加整體投入。
- 主鏈與 Liquid、冷錢包與熱錢包互轉：屬內部轉移；費用另記錄，不能算供款。

本版將 Bull 入金來源標示為尚未分類，不自動匯進 Wealthsimple 的供款帳本。Wealthsimple 帳戶的完整期間績效仍可計算；合併股票與 BTC 的 Modified Dietz／XIRR 暫不啟用，須另補資金來源分類、轉移配對及錢包餘額／費用資料與對帳完整性。這項限制不妨礙查看已知 Bull 入金、買入成本、每月購入數量與合併估值。

### 13.4 日後補入使用 Bull 前的 BTC

若只有總持有量、沒有原始交易史，應另建立有日期的「期初持倉／餘額觀測」，成本及歷史供款標示未知；不能將差額當成新購入、假設成本為零，或虛構購買日期。先釐清總量是否已包含 Bull 購入，以免重複。

現已支援獨立補登使用 Bull 前的 BTC 等值數量，見第 18 節。原 `bull-opening.json` 與舊報告保留；新增聲明與比較範圍基準，不直接修改原假設或資料庫，不把補登資產當成新的供款或投資增值。

參考來源：[Bull 官方 CSV 匯出說明](https://www.bullbitcoin.com/fr/blog/launch-of-bull-bitcoin-version-2)、[Bull Wallet 跨網路轉移](https://www.bullbitcoin.com/blog/how-to-move-bitcoin-from-your-spending-wallet-to-cold-storage-privately)、[Liquid 資產說明](https://docs.liquid.net/docs/liquid-assets)、[Coinbase candle 格式](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles)。

## 14. 不定期更新、漏月與補交

每月是整理建議，不是程式執行前提。隔 1.5 個月、2 個月或更久仍可匯入，所有比較採實際日期與相隔天數。

| 情況 | 處理方式 |
|---|---|
| 10 月後到 12 月才有新 Wealthsimple 持倉 | 歷史只有 10 月與 12 月觀測；11 月未提供，不補值、不歸零。比較這兩次觀測，不稱為單月報酬 |
| 補交當時保存的 11 月 CSV | 若日期晚於起始基準，可依原始 `As of` 匯入；歷史按日期排序，不依提交順序 |
| 12 月 Bull CSV 含 10–12 月全部訂單 | 已存在的訂單去重，新訂單按真正完成月份補入；可恢復每月購入／入金事件，不自動補月末持倉 |
| Bull 匯出只涵蓋部分日期 | 只記錄已提供內容；訂單首尾日期不證明其他日期沒有交易，應另外下載遺漏期間 |
| 持倉有更新，但供款不完整 | 可比較資產值，不能將其直接稱為扣除投入後的投資增值或期間報酬 |
| 兩種來源日期不同 | 依第 13.1 節自動選時間；各自列日期，含舊來源合計以估計呈現 |

例如 10 月至 12 月的供款要涵蓋整段期間，而不只 12 月；完整確認後，原有 Wealthsimple 期間計算使用真正日期加權。缺少月份不等於沒有供款。即使不定期匯入，也建議在看到文件時保存原始 CSV 與活動證明，之後才有可靠資料補交。

## 15. ETF 公司曝險與官方資料更新

日常命令不變，可提供 Wealthsimple、Bull，或兩份 CSV。即使只有 Bull 更新，程式也會對沿用的股票部位重新查詢最新官方 ETF 成分。沒有新 CSV 的重產命令沿用已保存的資產估值時間，但仍查詢最新成分，另存公司分析版本，不增加投資歷史觀測：

```bash
.venv-portable/bin/python scripts/update.py
```

ODS「組合分析」在原有證券排名／帳戶矩陣之後新增前 20 大公司、計算來源、基金覆蓋率及官方日期。前 20 大公司表格在 ODS、Markdown 與 PDF 的第一欄均有排名 1–20，依直接及 ETF 間接合計持倉市值由大到小排列。ODS「圖表分析」、Markdown 與 PDF 同步增加直接個股／ETF 間接股份堆疊圖。完整公司清單與各 ETF 的公司金額另存 `company-exposure.csv`；未知項目另存 `unresolved-exposure.csv`，來源及逐份原始檔 SHA-256 存在 `fund-sources.json`。

`company-exposure.csv` 包含全部已解析公司，不限前 20；有直接／間接金額、三幣等值、三種比例及每檔 ETF 分項。比例存成小數分數，例如 `0.154` 表示 15.4%。`unresolved-exposure.csv` 用於核對根 ETF、穿透路徑、項目名稱及尚未解析淨市值；其中金額已包含在資產總額及分母內，不能再次相加。一般閱讀以 ODS／PDF 為主，這兩份 CSV 供完整明細與審核使用。

### 計算口徑

- 公司 CAD 金額＝所有帳戶直接個股 CAD 市值＋各根 ETF CAD 市值 × 最終公司成分權重。
- 主占比＝公司金額 ÷ 全部非現金投資工具 CAD 市值。分母含自託管 BTC、比特幣 ETF、ETF 內現金及尚未解析部分；排除帳戶現金持倉。
- 同時列出占含現金總資產、占已解析公司股份兩種比例，分母彼此不同。
- 基金中基金逐層相乘。QQC 使用 CI 披露的 QQQM 部位，再讀取 Invesco US 的 QQQM 成分；Vanguard 使用官方已穿透的完整持倉，讀取全部分頁。
- 發行商權重依原始精度保留，不重新縮放到 100%。未披露的正餘額保留未知；超過 100% 的小幅四捨五入差額另列調整，過大則拒絕計算。
- 比特幣、已知現金和債券不列為公司。期貨、掉期、外匯合約及無法確認的股份／基金列未知；衍生工具淨市值不等於其名目或 delta 曝險，因此表格是公司股份市值估計，不包含完整衍生工具曝險。
- 公司名稱依可審核的 `config/company-aliases.json`、證券識別碼及保守名稱規則合併。ISIN／CUSIP／SEDOL／FIGI 是證券識別碼，不直接當作公司識別碼；ADR、股份類別及別名由公司規則進一步合併。相同代號不作跨市場合併依據。含多國同名歧義又缺識別的資料保留未知。

完整所有公司身分仍可能因發行商改名、非標準別名或未支援的證券類型需要維護對照表；程式不請 LLM 猜測。`company-exposure.csv` 保留來源名稱、解析方法及每檔 ETF 金額，便於審核。修改對照表後重產新分析版，原有保存版本仍可離線重播。

### 最新資料、不同日期與下載失敗

「最新」指本次程式查詢官方已發布資料，並非所有發行商都有當日成分。每份報告分別列投資估值時間、成分有效日期、下載時間及查詢狀態。現有介接包含 TSX VEQT、VFV、QQC、XCHP、ZNQ、FBTC，以及美國 SMH 和 QQC 底層 QQQM。FBTC 使用 Fidelity **Canada** 的基金資料，避免與美國同代號基金混淆。QQC 使用目前基金管理人 CI 的資料，沒有沿用舊加拿大 Invesco 來源。

CI 主要持倉表未披露部分保持未知；Vanguard 月度、Fidelity 季度資料可能較早。已查詢但日／月／季公布資料超過各介接器的合理期限，會標示較舊；期限不是發行商保證的更新承諾。

下載／解析失敗，或新 ETF 尚未介接時，報告仍可產生，但該基金全額列未解析，狀態明示不完整；不將未知當零，不悄悄沿用舊資料。未解析部分可能影響前 20 排名，故只列依已披露成分估計的結果。原始下載失敗前已保存的公開證據也保留供檢查。

ETF 分析是估計目前股票快照依最新公布成分的公司曝險。成分日期可能晚於快照日；本分析不重寫以前的投資市值、供款或實際績效。每次另建 SQLite `lookthrough_runs`；資產歷史 `snapshots`／`combined_observations` 的日期與筆數不因更新公司分析而增加。

### 離線重現已保存的分析

最新報告的 `manifest.json` 或 `data.json` 會記錄 `lookthrough_run_id`／`lookthrough.run_id`。例如保存分析版本 1 後：

```bash
.venv-portable/bin/python scripts/update.py --lookthrough-run-id 1
```

僅在目前採用的投資估值時間、持倉與總額完全符合該版本時才能重播；有新持倉或新價格就不能混用舊分析。離線重播不查詢發行商，明示「保存版本重播」，不宣稱是當日最新成分。必要的股票／BTC／匯率資料仍需已保存；這不是離線匯入任意新 CSV 的模式。

ODS 公司金額與占比是公式；保存的官方權重及基金已解析公司比重為輸入值。調整持倉金額會連動，但公司排序、公司對照、官方成分與 PNG 圖不會在試算表裡自動重新下載或重畫。正式更新應重新執行程式，以產生一致的三種格式及圖表。

### 保存位置與擴充

- `data/raw/fund_holdings/時間-識別/基金/`：不可覆寫的公開官方原始證據。
- SQLite `fund_sources`：完整解析成分、日期、網址、原始證據 SHA-256 與解析版本。
- SQLite `lookthrough_runs` 與 `lookthrough_run_sources`：投資估值指紋、公司對照指紋、計算結果及來源關聯。
- 各報告 `rNN/`：三種報告、PNG、完整公司 CSV、未知項目 CSV、來源 JSON、資料 JSON 與 manifest。

新 ETF 需在 `fund_sources.REGISTRY` 新增具基金識別與官方來源的介接器，並加入官方格式測試；尚未支援時會明確保留未知。正式流程全部由 Python 腳本執行，無 LLM、代理人、Codex、Node 或本機 LibreOffice 相依。網路僅取得公開成分；不傳送持倉金額、帳號、CSV 或供款資料。

### 官方下載如何自行執行

| ETF | 官方來源 | 程式取得方式 |
|---|---|---|
| VEQT、VFV | Vanguard | 官方 GraphQL 資料介面，讀取全部成分分頁 |
| XCHP | BlackRock／iShares | 官方持倉 CSV |
| SMH | VanEck | 官方持倉 Excel，Python 直接解析 |
| ZNQ | BMO | 官方基金網站資料介面 |
| FBTC | Fidelity Canada | 官方基金 JSON 資料介面 |
| QQC | CI | 官方基金資料頁，再讀取 QQQM 成分 |
| QQQM | Invesco US | 官方持倉 JSON 資料介面 |

以上是已實作介接方式，不保證發行商介面永遠不改版。程式使用固定欄位、日期、權重與公司對照規則，不呼叫 LLM，也不操作登入中的瀏覽器。新 ETF 或官方格式改版需要維護介接器；失敗會列未解析。工具目前由命令啟動，沒有定時排程、監看資料夾或自動登入券商下載私人 CSV。

## 16. 開發與待辦

專案規則見 [AGENTS.md](../AGENTS.md)，開發與測試見 [開發文件](development.md)，後續功能見 [TODO.md](../TODO.md)。私人的工作階段、帳本與報告狀態放在忽略的 `private/`，不屬公開文件。查看本機最新結果時讀 `reports/latest.json` 及 manifest，不為查狀態執行更新命令。

日常便利功能建議下一項為 FUT-002 統一狀態查詢；資金流主線為 Bull 入金來源分類與轉移配對。這些尚未實作，不影響目前支援的更新流程。其他券商／銀行／交易所的可擴充來源介接亦屬待辦，不表示現在已能匯入任意 CSV。正式功能始終由 Python 執行，不呼叫 LLM。

## 17. 產業、國別與地區配置

沿用原有更新命令即可，無須另交分類檔案。每次正常更新由 Python 查詢本輪最新官方已公布 ETF 成分及分類，保存原始證據、有效日期、下載時間與 SHA-256；沒有 LLM 或代理人呼叫。「最新」指發行商已公布資料，可能是月末資料，不代表今日成分。投資快照時間與成分／分類日期可能不同，不以後來公布資料改寫過去績效。

### 分類來源與缺漏規則

- **產業採 GICS**：Vanguard 官方持倉介面明確提供 `gicsSectorDescription` 與 `icbIndustryDescription`，兩者分開保存。即使基金主要分類體系為 ICB，也只取明確 GICS 欄位。BlackRock 的 `Sector`、Invesco 的 `sectorName` 等標籤保存為原始發行商分類，不因名稱類似就當作 GICS，不自行把 ICB 換成 GICS。
- **國別採官方國別／市場**：使用基金成分的官方國別欄位；不是公司營收來自何處，也不保證所有發行商均採法律註冊地。直接個股不能只憑交易所、幣別或 ISIN 前綴判斷。例如台積電 ADR 在美國掛牌，不因此列美國。
- **缺漏按同公司轉用**：部位先採自身官方成分列；沒有某維度時，從本輪下載且已可靠合併成同一公司的資料中，取該維度最新有效日。該日多份資料有衝突則保持未分類。直接個股也依此規則取得分類；找不到同公司官方證據時仍列未分類。每筆保存轉用方法、日期、基金、網址與來源狀態。
- **地區採明列地理分組**：依官方國別代碼分成北美洲、拉丁美洲及加勒比海、歐洲、亞洲、中東、非洲及大洋洲，對照表在 `src/wealth_ledger/classification.py`。這是工具的展示政策，不是發行商的成熟／新興市場等級，也不是完整全球地名資料庫。未支援或非國家代碼（例如 `XE`）保持未分類；新增代碼需維護及測試對照表。

分類欄位與基金頁面可核對：[Vanguard VEQT](https://www.vanguard.ca/en/product/etf/asset-allocation/9692/vanguard-all-equity-etf-portfolio)、[Vanguard VFV](https://www.vanguard.ca/en/product/etf/equity/9563/vanguard-sp-500-index-etf)。分類體系說明見 [S&P GICS](https://www.spglobal.com/spdji/en/landing/topic/gics/) 與 [FTSE Russell ICB](https://www.lseg.com/en/ftse-russell/industry-classification-benchmark-icb)。官方介面改版仍可能需要維護；失敗不以舊快取冒充最新。

### 比例、日期與對帳怎麼看

| 指標 | 分母及意思 |
|---|---|
| 占全部投資 | 全部非現金投資 CAD 等值，包含直接 BTC、比特幣 ETF、ETF 內現金及未解析工具；排除帳戶現金 |
| 占公司股票 | 已解析公司股份的 CAD 合計，包含股份中尚未分類部分；非公司項目為不適用 |
| 公司股票覆蓋率 | 有該維度分類的股份 CAD ÷ 已解析公司股份 CAD；不包含尚未解析成公司的工具，因此須一起看未解析金額 |
| 分類占全部投資 | 有分類股份 CAD ÷ 全部非現金投資 CAD；BTC 等非公司資產沒有產業／國別，不代表資料缺漏 |
| 有效日期範圍 | 實際採用分類證據的最早／最新有效日，不是下載日；逐筆來源另列 |

每維度的已分類公司、未分類公司、比特幣（直接及 ETF）、ETF 內現金淨額、債券、未解析工具／餘額及四捨五入調整，合計等於同一非現金投資總值。負的淨現金或微小四捨五入差額保留原符號，不強制正規化。這些是總值的拆分，不能再加到資產總覽。

同家公司不同基金的官方分類可能因日期或發行商口徑而不同；有自身分類的部位保留該列，並在逐筆審核檔提供證據。這不是跨公司營收、衍生工具名目／delta 或底層外匯風險分析。

### 報告與審核檔

- ODS「組合分析」在公司穿透表之後新增三組配置表，各列 CAD／USD／TWD、兩種占比、保存時覆蓋率／日期、各根持倉覆蓋及計算係數。國別表列全部已分類國別。
- Markdown／PDF 同步提供 GICS、國別、地區及覆蓋率；國別閱讀摘要列前 15 國及「其餘已分類國別」，未分類／非公司項目仍逐類列出。完整國別見 ODS／CSV。
- 三張新圖為 `13_sector_exposure`、`14_country_exposure`、`15_region_exposure`，主軸都是占全部非現金投資；灰色項目為未分類或非公司對帳項，極小負差額仍保留精度。
- `allocation-exposure.csv` 是完整三維度分類表，包含三幣金額與兩種比例；比例欄位是小數分數，`0.1` 表示 10%，三幣金額不可相加。
- `classification-detail.csv` 是逐公司、逐穿透路徑的來源審核檔；包含原始 GICS／ICB／發行商分類／國別，以及 `assignments` JSON 的官方日期、網址、基金、來源狀態與採用方法。這是公司部分的明細；非公司／未知對帳仍見配置表及 `unresolved-exposure.csv`。

ODS 分類金額與比例使用公式，連動持倉 CAD 市值與匯率；保存的分類係數為輸入值。改持倉市值可試算三幣配置，但保存時覆蓋率、日期、分類身分、排序與 PNG 不會自行更新。正式結果須重跑程式，手動試算不寫回 SQLite。

### 保存與歷史重播

分類保存在 `lookthrough_runs` 的共同 payload；此分析不新增股票快照、訂單、供款或估值日期。每輪官方查詢建立獨立分析版，新報告仍保存 `rNN`，不覆寫舊版。未提供 CSV 的更新仍沿用已保存金融估值，僅刷新官方分析。

有保存分類的分析可在**相同資產估值**下用 `--lookthrough-run-id` 離線重播，保留當輪分類與日期，明示未重新查詢。較舊分析沒有分類資料時仍呈現當時結果，不用今日分類補入歷史。分析 ID 屬各使用者本機資料，不要固定套用文件示例版號；先讀 `reports/latest.json` 與 manifest。


## 18. 補登使用 Bull 前的 BTC 持倉（缺少交易史）

如果你確認「全部錢包 BTC＋LBTC 等值合計」已包含匯入的 Bull 購入，並明確將差額歸為 Bull 使用前持倉，可使用獨立聲明補登：

**固定期初量 = 聲明總量 − 參照截止時間內 Bull 已完成購入 BTC＋LBTC。**

這是依你的指示分配數量，不是從訂單證明差額的來源。它不代表費用已核對、取得日期已知或 BTC／LBTC 目前網路分布已確認。僅補登數量時，期初成本及歷史實際投入 CAD 為未知；不填零、不用今日市價估算供款。實際完整 BTC 平均成本、未實現損益及損益率仍不可計算；選用 `bull_average_proxy` 時主 BTC 表按第 13.2 節額外顯示全持倉估算；預設 `actual_only` 不補代理數字。已知 Bull 購入支出另列。

先複製 `config/crypto-opening.example.json` 到私人工作目錄，修改以下欄位：

| 欄位 | 用法 |
|---|---|
| `reported_total_btc_equivalent` | 含全部追蹤錢包及 LBTC 1:1 等值的總量，最多八位小數 |
| `reference_as_of` | 計算已完成 Bull 購入的截止時間，ISO 8601 並附時區；若只是參照報告時間，需在 basis 說明不是精確錢包觀察時間 |
| `declared_on` | 實際聲明日期 YYYY-MM-DD |
| `balance_scope` | 確認全部錢包範圍後填 `all_wallets_btc_plus_lbtc` |
| `basis` | 你為何把差額視為 Bull 前持倉，以及已知／未知的涵蓋範圍 |
| `confirmed_by` | 聲明來源，例如個人確認或可核對的來源識別；不要放憑證 |

示例只有模擬數值，**不要直接匯入正式庫**。此命令會先備份資料庫，保存原始 JSON 並追加 SQLite 修訂，然後可產生報告：

```bash
cd wealth-ledger
.venv-portable/bin/python scripts/crypto_opening.py import /path/to/private-opening.json
.venv-portable/bin/python scripts/update.py
```

查看目前期初聲明（唯讀）：

```bash
.venv-portable/bin/python scripts/crypto_opening.py show
```

原始聲明按日期及 SHA-256 保存於 `data/raw/crypto/opening/YYYY/MM/`，SQLite 表為 `crypto_opening_revisions`；原 Bull 零期初帳本聲明、訂單及歷史報告不變。若明確更正聲明，匯入新 JSON 會追加修訂並另立比較範圍，舊修訂保留，不覆寫來源。缺乏資料的期初取得日期、成本及歷史供款仍未知。

後補持倉另立含期初資產的比較範圍基準，舊範圍估值與報告保留。若新範圍只有一個基準點，不畫兩點歷史曲線，也不把補登量算成當日成長；不補造 Bull 使用前市值。

**之後只需照常提供任一或兩份 CSV。** 期初量固定保留，新 Bull 訂單按 ID 去重後累加；不需每月重交總餘額，重交相同聲明不會重算期初。若未來回補先前漏掉的 Bull 購入或發現出售／費用，先核對是否與原聲明重疊；不要再用同一舊總量機械扣除新累計量。低於已提供購入量的聲明會被拒絕，需另處理出售、費用或來源缺漏。

已知 Bull Funding／Buy 仍不相加為兩次供款。這個期初聲明不新增任何 CAD 入金、交易或 cash_flows；若要補齊開戶以來投入，仍需可靠歷史交易、轉帳或資金流證據，不能只靠目前 BTC 數量推算。


## 19. BTC 餘額、異動與差額對帳

本節命令已實作。正式流程全為 Python，無須 LLM、錢包登入或 LibreOffice。請先 `cd wealth-ledger`，所有例子的 ID、數量及時間均須替換成實際資料；未來日期會拒絕。單位是 BTC 數量，不是 CAD／USD 市值。

### 19.1 可選總量：不需要 CSV 也能更新

```bash
# Optional total; time defaults to the start of this execution
.venv-portable/bin/python scripts/update.py --btc-balance 0.07990000

# Use the actual viewing timestamp when available
.venv-portable/bin/python scripts/update.py --btc-balance 0.07990000 \
  --btc-balance-as-of "2024-11-10T18:10:00-05:00"

# Either CSV, or both; balance remains optional
.venv-portable/bin/python scripts/update.py /path/to/holdings.csv /path/to/orders.csv \
  --btc-balance 0.07990000 --btc-balance-as-of "2024-11-10T18:10:00-05:00"
```

總量固定涵蓋全部納入追蹤錢包 BTC＋LBTC，按 1:1 BTC 等值；最多八位小數，零合法。沒有提供查看時間時，程式採本次執行開始時間，明示不是程式讀取錢包。可選 `--btc-balance-source "wallet display"` 補充來源說明。時間／來源選項不能單獨使用。

只有總量時沿用股票與 Bull 資料，保留其來源日期。新總量一般新增估值點；回補舊餘額不使最近報告時間倒退。完全不提供新資料時，`update.py` 仍重產最近保存時間，不新增今天的觀測。相同查看時間及數量去重；省略時間再次執行是另一個新的查看聲明，重試同一次失敗作業請見 19.7。

新專案可只有餘額：首次觀測以前的成本、購入、供款及帳本預期量未知。之後加入 Bull 仍須提供明確原始帳本期初假設；觀測以前的購入已在觀測中，不再次加到餘額。未知歷史不會因加入訂單自動變完整。

`--valuation-as-of` 控制報告截止，不改查看時間；不能用未來資料推算過去。明確要求歷史合併報告時選不晚於截止的股票快照；沒有適用股票快照會停止。一般更正舊餘額先保存，再重產最新適用報告即可。新餘額不能搭配 `--wealthsimple-only`、`--snapshot-id` 或 `--lookthrough-run-id`。

### 19.2 新總量不符、還沒有原因

照常接受回報量並用於估值，保存 ID、時間、原始聲明 JSON 及初次預期／差額。差額維持「待釐清」，不猜成費用、出售、供款或新的期初。原固定期初及 Bull 訂單不覆寫。

後續數量＝最近適用回報餘額＋該時間之後的已知淨異動。舊觀測／舊差額保留；較新的觀測一致也不能消除較早問題。預期量與回報量相符僅表示算術相符，未自動核驗鏈上交易或錢包。

### 19.3 查 ID，再補原因

```bash
.venv-portable/bin/python scripts/btc_balances.py list
.venv-portable/bin/python scripts/btc_balances.py show B000001
.venv-portable/bin/python scripts/btc_events.py list --balance-id B000001
```

輸出／報告的穩定 `balance_id` 指向一次觀測；修訂不換 ID。想解釋特定差額時指定它，不自動採用「最新差額」。異動須在上一有效觀測之後、該觀測時間之前或同時。初次觀測的區間依既有帳本適用範圍；超出區間或已作廢 ID 拒絕關聯。

例：預期 0.08000000、回報 0.07990000，先留下 −0.00010000；之後確認觀測前支付費用：

```bash
.venv-portable/bin/python scripts/btc_events.py add \
  --balance-id B000001 \
  --type fee --quantity-btc 0.00010000 \
  --occurred-at "2024-11-10T18:00:00-05:00" \
  --source "wallet manual record" --reference "fee-20241110-001"
.venv-portable/bin/python scripts/update.py
```

預期改為 0.07990000、剩餘差額零；持有量仍 0.07990000，不再扣到 0.07980000。只補部分費用也接受，顯示剩餘差額；補得過多則顯示相反方向差額，不截斷為零。第一次記錄的差額與後補重算值都保留。

`source` 為來源名稱，`reference` 為該來源內唯一交易／單據或自訂紀錄代號；相同來源＋reference 去重，內容不同須明確修訂。自訂代號可以保存使用者聲明，但不是獨立核驗證據。

### 19.4 尚無觀測時先記異動；既有異動補關聯

```bash
.venv-portable/bin/python scripts/btc_events.py add \
  --type fee --quantity-btc 0.00001000 \
  --occurred-at "2024-11-12T09:00:00-05:00" \
  --source "wallet manual record" --reference "fee-20241112-001"
.venv-portable/bin/python scripts/btc_events.py show E000002

# Explicit attribution of an existing event; no second economic entry
.venv-portable/bin/python scripts/btc_events.py link E000002 \
  --balance-id B000003 --expected-revision 1 --reason "Attribute to observation"
.venv-portable/bin/python scripts/btc_events.py unlink E000002 \
  --expected-revision 2 --reason "Wrong attribution"
```

不為解釋第二次差額複製同一費用。關聯只是解釋，經濟影響按真實時間只計一次。回補較早的觀測／作廢前一觀測，可能改變區間；原關聯不再適用時顯示「關聯待重查」，需查詢、更正關聯，不能悄悄改接另一筆。

`btc_events.py add` 僅保存資料，不發布報告。若事件晚於最近報告時間，裸 `update.py` 不會涵蓋它；需指定較新的估值截止，CLI 會提示：

```bash
.venv-portable/bin/python scripts/update.py \
  --valuation-as-of "2024-11-12T09:00:00-05:00"
```

### 19.5 類型與批次匯入

| 類型 | 數量方向 | 注意 |
|---|---|---|
| `fee` | 減 | 實際錢包／跨鏈費用；Bull 交付量已扣的費用不能再扣 |
| `sale`、`spend` | 減 | 本金與費用分開；不自動創造收到的現金或已實現損益 |
| `external_out` | 減 | 移出追蹤範圍，是否供款提款須另分類 |
| `external_in` | 加 | 非 Bull 購入的外部移入，成本／來源／供款另分類 |
| `own_transfer`、`conversion` | 零 | 自己錢包之間／BTC-LBTC 1:1 換網路；填移動總量，費用另列 |

異動數量全採正值，方向由類型決定。Bull 漏掉的購入應補 CSV，不手動當作 `external_in`；若先前誤分類，明確作廢誤分類紀錄再匯入 CSV，保留替代依據。後補在原期初購入截止以前的訂單可能與固定期初重疊，會列待核對，不自動重算期初或加兩次。

複製 `examples/templates/btc_events.csv`，按固定欄位填入：

```csv
source,reference,type,occurred_at,quantity_btc,balance_id
wallet manual record,fee-20241110-001,fee,2024-11-10T18:00:00-05:00,0.00010000,B000001
```

```bash
.venv-portable/bin/python scripts/btc_events.py import /path/to/btc-events.csv
.venv-portable/bin/python scripts/update.py
```

批次全數通過才提交；原始 CSV 另存。`balance_id` 可留空。YAML 不是支援的輸入格式。售出／轉出後缺現金對端或成本分配時，報告明示涵蓋限制；實際完整成本／損益保持未知，不代填零；若選用 `bull_average_proxy`，仍可依本期數量估算，但不代表完成實際成本分配。

### 19.6 更正、作廢及更換誤填時間

```bash
.venv-portable/bin/python scripts/btc_balances.py revise B000001 \
  --quantity-btc 0.07991000 --expected-revision 1 --reason "Corrected transcription"
.venv-portable/bin/python scripts/btc_events.py revise E000002 \
  --quantity-btc 0.00009000 --expected-revision 1 --reason "Corrected fee"
.venv-portable/bin/python scripts/btc_events.py void E000002 \
  --expected-revision 2 --reason "Duplicate of imported transaction"
```

修訂追加保存，不刪原始值；`--expected-revision` 必須符合目前版本。餘額時間／範圍、異動來源＋reference 是身分，不能默默修改。錯誤餘額時間用作廢後替代：

```bash
.venv-portable/bin/python scripts/btc_balances.py void B000001 \
  --expected-revision 2 --reason "Incorrect observation time"
.venv-portable/bin/python scripts/btc_balances.py add \
  --quantity-btc 0.07991000 --as-of "2024-11-10T18:20:00-05:00" \
  --source "user reported total" --replaces-balance-id B000001
.venv-portable/bin/python scripts/update.py
```

`btc_balances.py add` 只保存資料，時間必填。異動來源 reference 錯誤時同樣作廢，再 `add --replaces-event-id ORIGINAL_ID`，新的 reference 不重用原代號。不以反向假交易修正。

### 19.7 資料已保存、報告失敗與重試

```bash
.venv-portable/bin/python scripts/update.py --list-operations
.venv-portable/bin/python scripts/update.py --show-operation OPERATION_ID
.venv-portable/bin/python scripts/update.py --resume-operation OPERATION_ID
```

前兩者唯讀。新輸入經隔離暫存資料庫全數驗證後整批提交；格式／紀錄錯誤不留下部分正式資料。之後若行情、分析或報告流程發生阻止發布的錯誤，明確輸出「資料已保存，報告未發布」、固定截止及作業 ID。重試不重交 CSV 或總量、不重新取現在、不重記費用；已成功的作業回傳保存結果。單一 ETF 未解析但流程仍可完成時，照常發布並明示未解析覆蓋，不一律視為整份報告失敗。

輸入有後續修訂時，舊作業標為過期並拒絕重試；直接按目前資料與所需估值截止產生新報告。唯資料命令（餘額／異動）不要求自動發布；修改後另跑 update。無參數重產不自動處理未發布的新時間，會提示待發布作業。

正常重試仍查詢最新官方 ETF 公布資料；相同估值可使用適用凍結價格／匯率。`--lookthrough-run-id` 只在明確重播完全相同估值時使用。新輸入不能搭配離線重播。三種報告核對成功才更新 latest 指標；舊報告與當時凍結資料保留。

每次變更前有 SQLite 備份。輸入 JSON／批次 CSV 保存於 `data/raw/crypto/wallet/YYYY/MM/`；提供的行情／匯率參考 JSON 另封存於 `data/raw/reference/YYYY/MM/`。互斥鎖 `work/update.lock` 記錄 PID；意外中斷後先確認該 PID 已不在執行，再移除殘留鎖，不在仍有更新時刪除。

### 19.8 報告如何閱讀

ODS 新增「BTC餘額對帳」，Markdown／PDF 新增「BTC 餘額與異動對帳」。列出穩定 ID、時間、回報量、區間預期量、剩餘差額、首次記錄值及適用異動。報告時間顯示 America/Toronto 與 offset，另列回報來源及時間是使用者指定或採執行時間；SQLite／來源聲明保留 UTC 與原始時間。完整帳本預期量另外保留，不能因採新餘額作錨點就把舊差額歸零。

有觀測時，另有 BTC 累積購入／回報餘額／錨點後推估量比較圖；不補造缺月餘額。`btc-reconciliation.csv` 與 `btc-events.csv` 供審核，完整追加修訂仍在 SQLite／封存來源及 show 命令。已知費用及資料缺漏顯示實際狀態，文字全由程式模板產生。

**本版不啟用合併投資報酬。** 錢包範圍變更、獨立鏈上驗證、歷史成本分配及 Bull 入金來源／資金流完整性另有待辦。完整數量設計見 [BTC 對帳設計](btc-reconciliation-plan.md)。

## 20. 匯入預覽／預檢（FUT-001）

本功能已實作，採選用模式。一般 update 指令仍自動檢查、匯入與產生報告；加 `--dry-run` 才只預覽。預檢不會寫入正式 SQLite、原始來源、行情快取、備份、作業紀錄或最新報告，也不生成 ODS／Markdown／PDF／PNG。

### 20.1 單份、雙份、餘額與無新輸入

```bash
cd wealth-ledger

# Either CSV
.venv-portable/bin/python scripts/update.py /path/to/holdings.csv --dry-run
.venv-portable/bin/python scripts/update.py /path/to/orders.csv --dry-run

# Both sources
.venv-portable/bin/python scripts/update.py /path/to/holdings.csv /path/to/orders.csv --dry-run

# Optional balance only; replace the example quantity and viewing time
.venv-portable/bin/python scripts/update.py --dry-run   --btc-balance 0.07990000 --btc-balance-as-of "2024-10-10T17:00:00-04:00"

# Preview regenerating the last successful valuation
.venv-portable/bin/python scripts/update.py --dry-run

# Machine-readable output on stdout
.venv-portable/bin/python scripts/update.py /path/to/orders.csv --dry-run --json
```

上面的餘額數字與日期只是示例，請換成真正查看紀錄。也可將任一／兩份 CSV 與可選總量同時提供。省略 `--btc-balance-as-of` 時，採預檢這次執行開始時間；之後正式執行會採那次的新時間。若要比較同一次查看，請明確提供實際查看時間。

原 `--input`／`--bull-input`、`--kind`、`--snapshot-id`、`--wealthsimple-only`、`--valuation-as-of` 及適用的參考 JSON 可依原互斥規則使用。`--dry-run` 不能搭 operation 查詢／重試或 `--lookthrough-run-id`；ETF 分析不在本模式執行。`--json` 僅適用預檢，正常更新仍保持原有輸出。

### 20.2 預覽能告訴你什麼

- Wealthsimple：來源持倉日期、列數、帳戶涵蓋、缺帳戶提醒，以及預計新增／修訂／重複狀態。
- Bull：新增、修訂、既有訂單及檔內重複數；已完成訂單的經濟內容衝突會阻止更新，未完成訂單可按正式規則預覽修訂。
- 共用截止：沿用哪個來源與日期、預計估值時間；缺月不補造，股票沿用不冒充當日持倉。
- BTC：新回報的查看時間、當時帳本預期量與差額、截止時適用量及仍待釐清的觀測數。沒有足夠帳本時預期量／差額為 null，不填零；未知差額不當成費用／供款。回報晚於明確報告截止時，明示本期尚未採用它。
- 行情：已有適用匯率／價格，或缺資料待確認；不計算缺行情下的假市值。

隔離模擬使用與正式更新相同的 CSV 解析、帳戶／快照身分、訂單匯入、時間選擇及 BTC 對帳函式。私有暫存資料於結束時清除，不保留新 balance_id／snapshot_id／source_id，不能拿預檢暫存 ID 去補原因。正式 ID 要在實際匯入後查詢。

### 20.3 狀態與退出碼

| JSON status | 意義 | 退出碼 |
|---|---|---|
| `checked` | 本模式範圍內的本機輸入／適用行情檢查通過；ETF 及報告仍未驗證 | 0 |
| `pending_reference` | 尚缺適用行情；已完成的結構／數量檢查可閱讀，依賴行情的項目仍待確認 | 0 |
| `blocked` | 輸入、來源衝突、截止／數量、損壞參考或並行更新等問題需要處理 | 2 |

JSON 的 `blockers` 為阻止項目，`checks` 列各項已通過／待確認，`pending_checks` 另外列尚未驗證範圍。`simulation_complete=false` 表示模擬未完整完成，例如缺持倉匯率時只完成不依賴匯率的檢查，不能當作完整成功。非法命令列組合仍由 argparse 回傳退出碼 2 及 stderr 說明，不保證產生 JSON。

退出碼 0 只代表預檢未發現本模式的阻止問題，不代表已正式匯入或能完成行情下載與報告發布。自動化呼叫須一起讀取 status／pending_checks，不以退出碼 0 宣稱全流程已驗收。

### 20.4 離線限制與正式提交

預檢不連網、不登入券商／錢包，也不呼叫 LLM。只使用精確日期／截止且通過既有有效性規則的已保存匯率／BTC 報價，或你提供的適用參考 JSON；不從別的估值時間借價格、不造匯率。

沒有新日期的匯率時，仍可檢查 Wealthsimple 格式、數學、去重、修訂、帳戶與基準限制；依賴匯率的現金 CAD 異常檢查及完整資料模擬列待確認。BTC 數量對帳可以獨立於市值行情檢查。最新官方 ETF 下載、公司／分類分析、圖表、ODS／PDF 與發布檢查保持未驗證，正式更新仍依原政策執行。

看完後，移除 `--dry-run`／`--json` 再執行正式更新。正式流程重新讀取輸入、驗證並備份；不直接提交預檢副本。檔案、資料庫或執行時間變動可能使結果不同，尤其省略餘額查看時間的兩次執行。正式報告失敗仍按第 19.7 節 operation 流程重試。


## 21. 報告語言與離線另版

支援 `en-CA` 英文（加拿大）、`zh-TW` 繁體中文（台灣）、`zh-CN` 簡體中文（中國）。新安裝預設英文；已有資料的舊專案保留繁中。語言不改 CAD／USD／TWD、Toronto 時區、金融計算、ETF 資料日期或成本政策。

```bash
# Normal update in Traditional Chinese
.venv-portable/bin/python scripts/update.py /path/to/holdings.csv --locale zh-TW
# Offline preview in English
.venv-portable/bin/python scripts/update.py /path/to/orders.csv --dry-run --locale en-CA
# Simplified Chinese command help
.venv-portable/bin/python scripts/btc_events.py --locale zh-CN --help
```

永久偏好寫在忽略的 `config/local.toml`，保留同一 `[reporting]` 區段內其他設定，不重複新增區段：

```toml
[reporting]
locale = "zh-TW"
btc_cost_policy = "actual_only"
```

CLI 覆寫優先於本機設定，只影響該次。接受 alias `en`、`zh-Hant`、`zh-Hans`；`zh` 因繁簡不明而拒絕。唯讀查詢／dry-run 不寫設定。首次正常修改作業才保存相容預設。重試已提交的作業沿用作業保存的語言／資源版本，不改用後來的偏好；資源已改版而不符時明確拒絕重試，改以目前資料另產生新報告。

**只想將舊報告換語言時使用專用指令：**

```bash
.venv-portable/bin/python scripts/render_report.py \
  --from-report /path/to/saved-report-bundle \
  --locale en-CA \
  --output /path/to/new-english-edition
```

來源需有 data.json、manifest 及保存的 ETF 分析；指定來源以外尚不存在的新目錄。指令不匯入 CSV、不新增持倉／BTC 餘額、不查行情／官方成分、不連 SQLite、不改 latest，也不覆寫來源。估值及來源日期保持原值，另記重繪時間並標示凍結重播。data.json 保留原始位元；manifest 記錄所用語系、字典／字型版本及來源 checksum。舊版若沒有 data checksum，只能驗證中繼資料一致，不能追溯保證原始檔從未改動。

ODS、MD、PDF 及 PNG 使用同一語言。公司原名、股票代號、自訂帳戶名稱、來源備註／reference 仍保留原文；JSON／CSV 欄名及稽核附件維持原 schema。字型已隨專案提供，不需安裝本機 LibreOffice 或中文字型。格式化的未知值不變成 0；語言切換不補足歷史成本或供款證據。

本文仍是繁體中文，README 為英文；完整文件三語版本尚未提供。開發 Git 工具與外部系統／來源原始診斷可能保留英文。新增語言與技術細節見 [語系契約](i18n-plan.md)。
