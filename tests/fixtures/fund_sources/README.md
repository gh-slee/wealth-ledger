# 合成來源格式樣本

這裡的樣本為自行撰寫的最小解析測試資料。它們不是官方網站回應或下載工作簿的副本；公司、持倉、權重、日期、識別碼及分類測試內容為虛構。解析器必要的公開基金識別碼、欄位與特定名稱保留，用於確認格式及來源辨識。

樣本不包含網站程式、分析追蹤參數、session metadata、持倉全表或官方工作簿的原始 properties。XLSX 為自行生成的最小 OOXML ZIP。這些合成樣本依本專案 MIT 授權提供。

## 格式參考

以下位址說明對應的正式介接格式，並非樣本的金融資料來源：

- Vanguard GraphQL：`https://www.vanguard.ca/gpx/graphql`，`delayeredHoldings`、分頁及 `portIds` 欄位。
- BlackRock CSV：`https://www.blackrock.com/ca/investors/en/products/332756/fund/1464253357814.ajax?fileType=csv&fileName=XCHP_holdings&dataType=fund`。
- VanEck XLSX：`https://www.vaneck.com/us/en/investments/semiconductor-etf-smh/downloads/holdings/`。
- BMO GraphQL：`https://df.bmogam.com/api/graphql/etf-funds-production`，公開基金 profile `ZNQ-a`。
- Fidelity JSON：`https://fidcaproductsapi.fidelity.ca/FidcaProductsAPI/api/fundPage/fund/EN/FBTC`。
- CI HTML：`https://funds.cifinancial.com/en/create-html-for-pdf.html?series_id=49756`。
- Invesco JSON：`https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/46138G649/holdings/fund?idType=cusip&productType=ETF`。

## 測試範圍

樣本涵蓋百分比與小數權重、負現金、缺權重、cash、crypto、ADR、子基金、有效日期與每日 NAV 日期不同，以及分頁的總筆數／cursor 完整性檢查。分類測試另使用明確 GICS 與 ICB 欄位，不能從任意產業標籤猜測分類體系。

測試不使用網路，也不把樣本作為正式更新的備援、最新官方持倉或行情。正常更新仍由正式介接器取得官方已公布資料。
