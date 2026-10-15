# 開發與貢獻

本文件描述公開專案的開發流程，不包含使用者帳本、報告版本或工作階段歷史。先讀 [AGENTS.md](../AGENTS.md)、[README](../README.md)及 [TODO](../TODO.md)；功能契約見 [核心 API](core-api.md)、[報告規格](report-spec.md)與 [BTC 對帳](btc-reconciliation-plan.md)。

## 可重現環境

使用 Python 3.12+，依 README 建立 `.venv-portable` 並安裝 `requirements.lock`。不要依賴另一部電腦的虛擬環境、Codex 快取、本機辦公室程式或 LLM 服務。正式解析、下載、計算與報告均由程式完成。

```bash
PYTHONPATH=src .venv-portable/bin/python -m unittest discover -s tests -v
```

測試使用合成 CSV、隔離專案與公開發行商格式樣本。不要將真實資料庫、券商匯出、交易 reference、錢包地址或私人報告作為 fixture。公開格式樣本與合成持倉須可區分；樣本不能當作最新行情。

## 變更原則

- 先界定支援輸入、預設政策、錯誤狀態及既有資料遷移方式。
- 公開預設 `actual_only`；明確設定才使用 `bull_average_proxy`。本機偏好不能成為其他使用者的隱含預設。
- 財務邏輯用 Decimal／satoshi；維持來源、時間、範圍、去重及追加修訂契約。
- 公開查詢與純計算分開；測試注入行情／官方格式，不依賴測試當時網站狀態。
- 報告共用 payload。結構或文字變更需更新發布檢查；金額／比例改動核對公式及三幣結果，版面改動檢視受影響 ODS／PDF。
- 文件修改不重產金融報告或新增觀測；記錄真正執行的驗證，不把舊測試當成本輪重跑。

## 隱私及本機指引

`data/`、`reports/`、`backups/`、`private/`、`work/`、虛擬環境與本機設定均為忽略狀態。公開模板位於 `examples/templates/`，設定以 `.example` 檔名區分。報告可能包含敏感金額，即使遮罩帳號也不應預設公開。

如果存在 `private/AGENTS.local.md` 或 `private/session-handoff.md`，只供授權本機開發情境讀取。不能把其中的金額、日期、來源檔名、個人偏好或驗收狀態複製到公開文件；公開產品契約以目前程式及通用文件為準。

## 提交與推送

詳見 [公開發布流程](publishing.md)。只 stage 經審核的公開檔案，提交／推送前檢查內文與 outgoing commits。Git ignore 不會清除已追蹤資料或文件內個資。

開發發布與正常更新指令分離。未有有效登入或私人授權設定時只產生計畫，不自行建立 repository、推送或合併。經授權後使用功能分支＋PR，不自動合併 `main`。CI 使用乾淨 clone、合成示範與隔離測試，不需私人帳本或 LLM。

完成變更後更新 TODO 與受影響契約，記錄驗證及限制；私人工作階段細節另存忽略目錄。待辦不是下一個工作階段的自動執行指令。


## 翻譯與呈現

三語資源與新增語言驗收見 [語系契約](i18n-plan.md)。程式／註解／機器契約使用英文；程式文案使用穩定 key 與具名參數。更新一個 key 時三語同步，不在執行時呼叫 LLM 或翻譯服務。來源名稱與 reference 保留原文。

金融資料與顯示深拷貝分離；格式化用 Decimal，不使用 process-global locale。工作表使用穩定 ID，字型隨 locale 選取且附授權。變更報告需通過三語公式／快取／缺漏語意驗證，並檢視 PDF 與圖表。CI 的合成示範覆蓋三種語言及明確 BTC 代理政策；首次遠端 CI 驗收仍需公開發布後完成。
