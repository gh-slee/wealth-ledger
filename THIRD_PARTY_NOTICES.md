# 第三方資料與授權

專案自行撰寫的程式及文件依 [MIT License](LICENSE) 提供。此授權不取代字型、相依套件或正式執行時下載資料的授權條款。

## 字型

`assets/fonts/NotoSansTC-Regular.ttf` 為 Noto Sans TC 繁體中文字型的固定 Regular 衍生版本，由可變字型固定字重為 400。來源為 Google Fonts／Noto 專案；字型依 SIL Open Font License 1.1 提供。原有版權聲明、保留字型名稱及完整條款保留於 [assets/fonts/OFL.txt](assets/fonts/OFL.txt)，不得以本專案 MIT 授權替代。ODS／PDF 使用相同字型；ODS 同時嵌入 OFL 文件。

`assets/fonts/NotoSansSC-Regular.ttf` 是未修改的 Noto Sans SC Regular，Version 2.004-H2；Adobe 2014–2021 版權與 SIL Open Font License 1.1 條款保留於 [OFL-SC.txt](assets/fonts/OFL-SC.txt)，資產版本與 SHA-256 見 [來源紀錄](assets/fonts/NotoSansSC-provenance.json)。zh-CN 報告使用此檔並在 ODS 嵌入對應授權；不以專案 MIT 取代字型授權。

## Python 相依套件

正式環境使用 `requirements.lock` 列出的套件，包含 Matplotlib、ReportLab、pypdf、Pillow、tzdata、certifi 及其相依套件。這些套件由套件管理器安裝，不將其第三方程式碼重新授權為 MIT；實際授權與版本以安裝套件隨附的 metadata、LICENSE 及上游文件為準。

## 官方 ETF、匯率與行情

正常執行時會從供應者的公開來源下載資料，保存在各使用者的私人資料目錄，並記錄取得時間、有效日期及雜湊。公開可取得不代表有權將整份下載內容重新發行；本 repository 不提供已下載的官方成分資料、行情證據或私人分析報告，亦不授予相關資料的再散布權。

`tests/fixtures/fund_sources/` 是自行撰寫的最小合成格式樣本，不是官方 response 的重發行。欄位、基金識別碼及必要的解析名稱用於格式相容性測試；公司、權重及日期皆為虛構，不代表任何基金成分或最新官方資料。來源格式參考位址保存在 [fixture 說明](tests/fixtures/fund_sources/README.md)。

## 合成示範

`examples/` 的 CSV、匯率、BTC 價格、訂單及 ETF 成分均為虛構測試資料，不包含真實使用者資料，不能作為投資或稅務計算輸入。合成報告僅用於驗證安裝、程式流程及格式生成。
