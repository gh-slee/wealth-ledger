# 合成範例與離線示範

這個目錄完全使用虛構資料，可公開分享及重複測試。CSV、帳戶識別碼、訂單、價格、匯率與 ETF 成分都不能當成真實金融紀錄。

## 檔案

| 檔案 | 用途 |
|---|---|
| `data/wealthsimple-holdings.csv` | 模擬 TFSA、RRSP 與 Non-registered 的 CAD／USD 證券及現金快照 |
| `data/bull-orders.csv` | 模擬一筆 CAD Funding、BTC 與 LBTC 各一筆已完成購入；訂單沒有真實錢包地址 |
| `data/fx.json` | 模擬 CAD／USD／TWD 匯率，與範例估值日期相符 |
| `data/btc-price.json` | 模擬同截止時間的 BTC-USD 一分鐘完成 K 線，不是官方行情 |
| `templates/cash_flows.csv` | 供款及轉移的空白欄位模板 |
| `templates/btc_events.csv` | BTC 費用、收入及支出等異動的空白欄位模板 |
| `../config/bull-opening.example.json` | 明確的虛構 Bull 零期初聲明；開始用自己的 CSV 前需根據自己的歷史修改 |

## 生成 ODS、Markdown 與 PDF

先依主 README 安裝相依套件。在 repository 根目錄執行：

```bash
.venv-portable/bin/python examples/demo.py --output work/demo
```

結果包括 `portfolio.ods`、`report.md`、`report.pdf`、PNG 圖表、CSV 分析附件及 `demo-manifest.json`。ODS／PDF 使用隨專案提供的中文字型，不需 LibreOffice、LLM 或其他本機應用程式。Markdown 的圖表連結為相對路徑，分享時保留同一輸出目錄。

示範在系統暫存目錄建立獨立 SQLite，結束時清除；只把合成報告複製到指定輸出目錄。不讀取正式資料庫、`config/local.toml` 或既有報告；不查詢網路、不修改 `reports/latest.json`。已有同名輸出目錄會拒絕覆寫，請改用新的路徑。

ETF 成分由程式提供虛構公司與配置，保存模式標示為 `synthetic_demo`，來源不是官方資料。這不是正式 `scripts/update.py` 的公開行情流程，不能以此確認官方網站仍可連線。

## BTC 成本政策

新帳本預設 `actual_only`：不將後來的 Bull 均價自動套用未知期初量。已知 Bull 購入支出仍會列出。

若要檢查可選的全數量 Bull 均價代理：

```bash
.venv-portable/bin/python examples/demo.py --output work/demo-proxy --btc-cost-policy bull_average_proxy
```

此選項只影響示範的報告估算，不把估算成本寫成實際成本。正式工具的選項與本機設定方式見 [操作手冊](../docs/user-manual.md)。

## 使用自己的資料

請把範例與正式帳本分開。不要先將示範 CSV 匯入日常帳本，再以真實 CSV 覆蓋；歷史資料是追加保存。首次 Bull 匯入需要明確的期初聲明，不能因為沒有歷史紀錄就擅自填零。

資料模板只包含欄位名稱。把填入個人資料後的檔案放在 `data/` 或私人輸入目錄，不能把它提交回 `examples/`。每次正式更新、餘額觀測及供款操作的完整範例見操作手冊。


## Report languages

The demo defaults to English (`en-CA`). Select `--locale zh-TW` or `--locale zh-CN` with a new output path for each run:

```bash
python examples/demo.py --output work/demo-tc --locale zh-TW
python examples/demo.py --output work/demo-sc --locale zh-CN
```

Each run uses an isolated synthetic ledger, bundled fonts, and offline references. Source names and machine exports stay unchanged. The demo's manifest/data can also be used by scripts/render_report.py for an offline alternate language edition; it remains synthetic demonstration data.
