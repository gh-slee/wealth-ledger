# 報告字型

`NotoSansTC-Regular.ttf` 是隨專案提供的繁體中文字型，讓 PDF 與 PNG 不依賴作業系統字型。由 Google Fonts 的 Noto Sans TC 可變字型固定為 `wght=400`，並將 PostScript 名稱設為 `NotoSansTC-Regular`；實際字重已核對為 400。

原始來源：[Google Fonts Noto Sans TC](https://github.com/google/fonts/tree/main/ofl/notosanstc)。授權為 SIL Open Font License 1.1，完整條款見同目錄的 `OFL.txt`。正式報告使用此 Regular 檔。

ODS 嵌入同一字型及授權，並指定拉丁與亞洲文字樣式；閱讀程式對內嵌字型的支援依軟體而定。公式可編輯；圖表為內嵌 PNG，不能編輯系列或隨儲存格變更即時重畫。PDF 已嵌入字型，PNG 已轉成圖像。


## 簡體中文

`NotoSansSC-Regular.ttf` 為未修改的 Noto Sans SC Regular（Version 2.004-H2），用於 zh-CN。包含 TrueType outlines；字型中繼資料標示 Adobe 2014–2021 與 SIL OFL 1.1，完整授權另見 `OFL-SC.txt`。版本、SHA-256 與來源專案記錄於 `NotoSansSC-provenance.json`，上游為 [Noto CJK](https://github.com/notofonts/noto-cjk)。這是專案隨附資產，不依賴使用者本機應用程式或作業系統字型。

en-CA 與 zh-TW 選 TC；zh-CN 選 SC。驗收檢查三語字典漢字的 cmap 覆蓋，以及同程序依序產生不同語言 PDF 的抽文／字型註冊隔離。字型授權不屬於專案 MIT。未來新增語言需另驗證字形覆蓋及授權。
