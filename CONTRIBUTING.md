# 參與開發

Wealth Ledger 的正式功能由 Python 執行。開發時可以使用 LLM；使用者匯入、計算、官方 ETF 下載與報告生成不能依賴 LLM 或特定電腦上的應用程式。

## 開發環境

目前正式安裝方式是複製 repository，在 checkout 內建立 Python 3.12+ 虛擬環境，依 `requirements.lock` 安裝。CLI 與中文字型依 checkout 結構讀取；尚未提供可獨立安裝的 wheel 或 PyPI 發行版。

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python examples/demo.py --output work/demo-review
```

Windows 可使用 `.venv\Scripts\python.exe`；設定 `PYTHONPATH` 的方式依 shell 調整。目前 CI 設定為 Linux／Python 3.12，不宣稱已完成 Windows 或 macOS 的完整跨平台驗收。

## 修改規則

- 金融數值使用 `Decimal`；未知資料保持未知，不能自行補零、猜測供款或改寫歷史。
- 新的來源介接器需有離線合成格式樣本及錯誤案例。樣本應自行撰寫，保留解析需要的欄位及公開基金識別碼，不能提交券商原始匯出或整份官方下載回應。
- 測試使用系統暫存目錄，不能依賴已有的 `data/`、`work/`、報告、私人設定或虛擬環境。
- 報告修改需驗證影響到的公式、三幣合計及發布檢查；版面修改另檢查 ODS／PDF 視覺輸出。
- 程式碼、註解及識別名稱使用英文；報告支援 en-CA／zh-TW／zh-CN，操作文件目前為繁中、README 為英文。翻譯貢獻遵守 [語系契約](docs/i18n-plan.md)，三語 key／參數須同步、原始來源文字不翻譯。
- 同步更新操作手冊、TODO 及通用開發文件，說明驗證方式與限制。

## Pull request

在功能分支進行修改，提交前執行離線測試、合成示範及 repository 的發布隱私檢查。PR 請說明觸發情境、修改後行為及測試，不附私人財務報告或原始交易樣本。未知來源格式可先建立只含虛構資料的最小重現。

專案採 MIT 授權；貢獻程式及文件時請確認有權以相同授權提供。字型及相依套件另依各自授權，見 [第三方說明](THIRD_PARTY_NOTICES.md)。
