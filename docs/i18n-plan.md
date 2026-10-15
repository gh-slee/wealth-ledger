# Wealth Ledger 語系契約與貢獻指南

首批語系：`en-CA`（英文／加拿大）、`zh-TW`（繁中／台灣）、`zh-CN`（簡中／中國）。本文由原設計提案更新為實作契約；遠端發布狀態另見 TODO。報告與日常 CLI 採靜態字典和 Python 程式，執行時不使用 LLM、翻譯服務或作業系統 locale。

## 1. 選擇與相容性

優先序：`--locale` → 忽略的 `config/local.toml` `[reporting].locale` → 專案預設。新專案為 `en-CA`；已有 SQLite 或 latest 的舊專案為 `zh-TW`。第一次正常寫入作業保存專案預設，CLI 臨時覆寫不改偏好；唯讀查詢與預檢不寫設定。

接受 `en`、`zh-Hant`、`zh-Hans`；大小寫及底線正規化後使用正式標籤。`zh` 有歧義，`en-US` 等未支援地區不自動降級。無效語系在金融提交前拒絕。既有 BTC 成本政策保留。

```toml
[reporting]
locale = "zh-TW"
btc_cost_policy = "actual_only"
```

```bash
python scripts/update.py /path/to/holdings.csv --locale en-CA
python scripts/update.py /path/to/orders.csv --dry-run --locale zh-TW
python scripts/btc_events.py --locale zh-CN --help
```

建立作業時凍結 locale、字典雜湊、格式／渲染版本及字型雜湊；重試不套用新偏好。若保存的資源版本已變更，停止重試而非悄悄換文字。沒有語系欄位的舊作業／ODS 按既有繁中相容行為處理。

## 2. 呈現層與資料不變條件

`i18n.py` 使用 `ContextVar` 隔離每次呈現。`formatting.py` 僅格式化 Decimal／日期。金融核心、來源 parser、事件 ID、JSON／CSV 欄名、歷史與去重規則維持原契約。

```text
raw CSV / saved ledger / frozen analysis
                  |
       original values + stable codes
                  |
       presentation context + locale
          /          |          \
        ODS       Markdown     PDF / PNG
```

字典在 `src/wealth_ledger/locales/`：`registry.json`、三語 JSON 與 `legacy.json`。現有訊息抽取後使用穩定 `message.<hash>`／`cli.<hash>`，新訊息可採具意義的英文 namespace；key 不能因修改措辭而改名。`legacy.json` 是封閉的舊程式文案相容表，不是任意文字翻譯器。舊 payload 不改寫；呈現使用深拷貝。固定模板只接受既定具名參數，缺 key、缺參數、多參數或三語參數不符必須報錯。

來源名稱、代號、帳戶自訂名稱、交易 reference 與備註保留原文；可能與介面語言不同。`SourceText` 明確標記不翻譯的文字。分類與合成 BTC 顯示標籤才由程式翻譯。歷史相容程式不應擴展為全文搜尋替換。

## 3. 數字、時間、字型與公式

三語首版都使用 `.` 小數點、`,` 千分位及明確金融 ISO 日期；時間仍為 `America/Toronto`。CAD／USD／TWD 是同一資產的不同等值，語系不改幣別、時區或稅務政策。

實作使用標準庫的明確格式 profile 與 Decimal，沒有新增 Babel 或平台相依。這三個 profile 尚不需要一般 CLDR 格式引擎；未來語系若需要不同日期／數字規則，須擴充 formatter 或另審核鎖定的可攜套件。顯示字串不能解析回金融計算。未知、不適用、未啟用、未能計算與有效零值分開；微量非零值不能因格式化變零。

工作表內部 ID 為 `overview`、`positions`、`btc_tracking` 等英文值；實際表名由 locale 決定。跨表引用透過 ID 映射及跳脫，函數、數字、快取維持 OpenFormula 機器格式。驗證器讀取 ODS locale metadata 再核對表名／公式；沒有 metadata 的舊檔使用繁中。

英文／繁中隨附 Noto Sans TC；簡中隨附 Noto Sans SC。PDF 字型註冊名稱含 locale／字型雜湊，避免同程序切換時重用錯誤字型。PDF `/Lang`、ODS 樣式語言與文件 locale 同步，字典／字型版本寫入 manifest。字型授權與來源見 `assets/fonts/README.md`。ODS 圖表仍為內嵌 PNG，不依賴 LibreOffice。

## 4. 離線重繪與歷史

只切換保存報告的語言：

```bash
python scripts/render_report.py \
  --from-report /path/to/saved-report-bundle \
  --locale en-CA \
  --output /path/to/new-english-edition
```

來源需要 `data.json`、manifest 及凍結 ETF 分析。輸出須為來源資料夾以外的新目錄，不覆寫。驗證資料雜湊（若有）、估值截止、分析 ID 與金融指紋（若有）；產生後再確認來源沒有變更。舊 manifest 沒有 checksum 時，僅能標示 `legacy_metadata_consistency`，不宣稱完整來源認證。

不讀寫帳本、不連網、不更新匯率／價格／ETF、不新增金融觀測、不改 latest；新 data.json 與來源逐位元相同。新 manifest 記錄重繪時間、語系版本及來源 manifest 雜湊。分析文字明示凍結重播。報告日常更新仍按原契約查詢最新官方資料，不能用正常 update 當成純語言切換。

機器匯出／稽核附件保留原 schema 與來源語言。離線重繪不補足缺少的實際成本、供款或錢包異動，也不追溯重新估值。

## 5. 新增語言與驗收

1. 在 registry 登記正式 locale、名稱、方向、格式及隨附字型／授權。新的國家不等於新增券商、稅務或幣別支援。
2. 以英文 catalog 的完整 key 集合建立獨立 UTF-8 JSON；人工校對術語、具名參數、未知／零值語意，禁止執行時翻譯。新增共用 key 必須同時更新目前三語。
3. 驗證 `validate_catalogs()`、字型 cmap 覆蓋、所有公式與快取、PDF 抽文／Lang、ODS 語系、英文長標籤與 CJK 換行，並檢查 PDF／PNG 實際畫面。
4. 同一合成 payload 生成各語系，核對 Decimal 總額、金融指紋、公式數量、原始 payload／SQLite 不變。測試未知成本、錢包差額、零持倉與最小 BTC。
5. 測試缺 key／參數／字型、無效 locale、重試凍結資源，以及離線重繪禁止網路／覆寫／latest 異動。
6. 更新 CI、README、手冊及公開檔案允許清單。新增 catalog／字型路徑必須顯式審查，不放寬任意 JSON／字型下載或私人文件發布。

未來來源 plugin 可使用 provider namespace 訊息，但 plugin SDK 尚未實作。原始錯誤、系統診斷及來源公司名稱不保證翻譯；開發 Git 工具與完整文件三語翻譯不在本版範圍。
