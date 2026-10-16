# 自架 Web App：架構與實作契約

狀態：**設計基準，尚未實作 Web App**。目前可用產品仍為 README 所述的 Python CLI。本文件記錄已選擇的技術方向與第一版設計；目錄、API 及狀態為待實作契約，不是現有可執行介面。詳細進度見 [TODO](../TODO.md)。

## 產品與技術邊界

第一版為單一主機、每個 instance 一位 owner／家庭使用，可有多個獨立帳本。Owner 管理全部帳本；帳本隔離資料與設定，不宣稱提供家庭成員之間的細粒度權限或多租戶 SaaS。

| Layer | Selected direction |
|---|---|
| Browser | React + TypeScript + Vite |
| UI | Tailwind CSS + shadcn/ui |
| Navigation and server state | React Router + TanStack Query |
| Tables and charts | TanStack Table + Apache ECharts |
| API | FastAPI + Pydantic + versioned OpenAPI contracts |
| Finance and reporting | Existing Python services, shared by CLI and worker |
| Storage | SQLite plus immutable source/report files |
| Runtime | Docker Compose: web/API and one Python worker |
| Exports | ODS, Markdown, PDF, PNG, CSV and JSON |

前端 Node 工具只用於開發及映像建置；正式容器以 Python 提供 API／靜態前端及背景工作。正式功能不依賴 LLM、Codex、Node server、本機 LibreOffice 或維護者個人帳本。保留 en-CA、zh-TW、zh-CN。

第一版保留目前支援的 Wealthsimple／Bull、CAD／USD 證券、CAD／USD／TWD 等值及 America/Toronto 的金融日期契約。來源 plugin SDK、其他幣別／地區模型依既有獨立 roadmap 推進；Web UI 不代表這些功能已完成。

## 共用服務及私人工作區

CLI 與 Web worker 皆呼叫與 HTTP／React 無關的 Python application service，包含來源辨識、預檢、備份、互斥、資料提交、分析、報告驗證與發布。從 CLI 抽出 publisher，明確傳入 workspace，不以改寫 module-global PROJECT 或每次 HTTP 呼叫 shell CLI 達成。

- code_root：唯讀程式、字型、語系、報告資源及官方來源 registry。
- workspace_root：每個帳本的 SQLite、原始來源、FX／BTC／ETF 證據、報告、備份、作業與本機設定。
- 內建公司別名等資源由 code_root 讀取；私人覆寫有明確 schema／版本／優先序與雜湊。
- CLI 提供顯式工作區選擇及舊 checkout-local 相容用法；所有日常命令、備份、查詢／續跑與預檢使用相同解析規則。
- 指定錯誤工作區須停止，不默默改用另一份帳本。Web 只接受 server-managed portfolio ID，不接受任意主機路徑。
- 圖表／字型快取屬私人可寫目錄；外部工作區在程式目錄唯讀時也能完成三種報告。

目標 volume 結構：

```text
/data/
  admin/app.sqlite3
  admin/queue.sqlite3
  secrets/
  uploads/<upload-id>/
  portfolios/<portfolio-id>/
    config/local.toml
    data/db/portfolio.sqlite3
    data/raw/
    data/fx/
    data/prices/
    reports/
    backups/
    work/
  cache/
```

網站 owner／session／portfolio registry／upload／job／report artifact metadata 存在獨立 app.sqlite3，不把 Web migrations 套入既有金融庫。Huey 使用獨立 queue.sqlite3；不是三個資料庫服務。各金融帳本仍由現有核心保存。SQLite 僅支援同一主機的本機 volume，不宣稱 NFS、多主機共用或水平擴展已可使用。

## 登入與授權設計

採用 owner 帳號密碼及 **server-side opaque session**。

- Owner 由受信任的主機／容器 CLI 初始化；沒有公開註冊或未登入即可領取 instance 的網頁。
- 密碼採 Argon2id，透過維護中的密碼函式庫驗證；只保存 hash，不記錄／回傳密碼。
- Session ID 為足夠長的隨機值；資料庫保存其雜湊與期限。Cookie 使用 HttpOnly、SameSite=Lax；HTTPS 部署使用 Secure。
- 預設閒置 30 分鐘、絕對 12 小時；進度輪詢不延長閒置期限。登入輪替 session，登出／改密碼／主機重設可撤銷。
- React 與 API 同 origin。修改動作採 POST 等適當方法、CSRF token 及 Origin 驗證；SameSite 不作唯一防護。
- 登入與登出也納入 CSRF／來源驗證；登入節流不依賴未受信任的 forwarded IP。
- 第一版不需要 JWT／refresh-token 架構、外部登入供應商或電子郵件服務。密碼遺失由主機 CLI 重設並撤銷 session。
- 所有帳本 API、來源下載、JSON／圖表／報告／ZIP 都需驗證登入及 portfolio 所屬。猜到 artifact ID 不代表獲准存取。
- 不在 browser localStorage 保存登入憑證或持久化金融快取。TanStack Query 的 key 包含 portfolio 與 report ID，登出清空並中止舊請求，切換帳本不顯示前一份資料。

Web 登入密碼與磁碟加密是不同層次：SQLite 仍未加密。Owner/session 流程須依維護中的元件、明確期限及安全測試實作，不把 FastAPI 的 JWT 教學當作必用政策。

## 上傳、預檢與提交

1. 登入後選擇帳本，上傳支援 CSV（任一來源或各一份），或提交日期明確的可選 BTC 總量。首用 Bull 的期初依據、可選來源 JSON 及資金流走明確表單／檔案種類。
2. 串流保存至隔離 uploads 區；原始名稱為 metadata，磁碟路徑由 server 產生。每 CSV 上限 10 MiB、整批上限 25 MiB；reference JSON 各上限 64 KiB。限制與編碼／列數檢查在 API 及 worker 皆執行。
3. 依內容辨識格式；未知／模稜兩可格式拒絕。不上傳 ZIP／任意可執行程式，不從 CSV URL 安裝 parser。
4. 背景執行既有離線預檢，顯示重複／修訂、來源日期／沿用、帳戶範圍、BTC 差額與待取得參考資料。預檢不寫金融帳本／正式 operation，不下載行情或官方成分。
5. 使用者確認同一批 upload hashes／request digest 與帳本 input fingerprint，才排入正式匯入。預檢後帳本改變須重跑；缺參考資料可明示 pending，blocked 不可提交。
6. 正式作業驗證、互斥、備份，再呼叫共用金融服務。只有成功產生並驗證整組報告，才更新最新成功版本指標。

畫面會分開顯示「來源已上傳」「資料已提交」「報告已發布」。未提供新 CSV 不表示零活動；不定期快照與沿用來源的既有語意保留。首次 Bull 不自動採零期初，已補登期初／餘額也不因新 CSV 重算。

BTC 餘額、事件、供款、涵蓋聲明與期初功能需逐步提供 Web 表單；原 CLI 持續可用。事件歸因使用 balance ID，修改／作廢使用 expected revision 與 reason，不把觀測差額自動當費用或供款。

## 背景工作與恢復

初版建議 **Huey + SQLite storage**，獨立 worker process，每個 instance 起一個工作執行程序。維持兩個服務，不強制 Redis。app.sqlite3 的 job 狀態才是使用者可見的持久化紀錄；queue 不是金融帳本，也不是完成憑證。

Job 保存 portfolio ID、upload hashes、版本化 request、idempotency key、核心 operation ID、固定執行／估值上下文、狀態與產物 ID。相同 idempotency key 搭配不同 request 必須拒絕。佇列只傳內部 job ID；外部請求不能提供序列化 task、pickle、callable 或 shell 命令。

- 需可靠連結 job 與核心 operation：核心 operation 先持久化關聯，再進入可提交階段。跨 DB／queue 的中斷由 reconcile 補齊，不能假設跨三個 SQLite 檔案有單一交易。
- `queued -> running -> data_committed -> published` 為主流程；預檢有獨立狀態；另有 `blocked`、`failed`、`report_failed`、`interrupted`、`needs_review`。
- 已保存資料但報告失敗：沿原 operation 與截止續跑，不重新匯入或建立現在時間的餘額。
- 核心已發布但 Web job 尚未更新：重新核對 operation／產物 manifest 後補記成功，不再發布一版。
- 中斷時無法證明提交進度：標示 needs_review，提供有界的恢復程序，不猜測成功／失敗後自動再執行。
- 重啟會檢查 app jobs、核心 operations 與 queue。遺失的排隊通知可重送；不依賴 queue 自動重試就宣稱 exactly-once。
- SQLite 寫入按帳本序列化；CLI 與 worker 共用互斥機制。跨容器使用同主機 OS advisory lock／可驗證 owner token，PID 僅供診斷，不依 PID 猜測並刪鎖。
- 報告渲染使用程序隔離，避免 Matplotlib／語系的共享狀態互相污染。增加 worker 需重新驗收鎖、資源與執行上限。
- 第一版採輪詢進度，不要求 WebSocket。取消只在安全邊界生效；已提交資料不因按取消而倒轉。

API 可用 async 處理網路請求；FastAPI BackgroundTasks／單純 thread pool 不替代持久化工作與恢復契約。

## 畫面、查詢與匯出

- 儀表板、持倉／帳戶、來源與日期、公司／產業／國別曝險、歷史、BTC／資金流、作業、報告庫與設定。
- 只讀頁面及圖表使用選定的已發布凍結 payload；開啟頁面不建立新估值、觀測、官方下載或報告。資料已提交但未發布時保留舊成功版並顯示 pending。
- 後端金融金額／數量／比例以 Decimal 字串傳輸，未知為 null。前端只作排序／格式化／繪圖，浮點轉換限視覺座標，不成為金融計算來源。
- 圖表保留不完整／沿用旗標與真實日期，不把缺月補成假觀測，不以資產變化冒充已扣供款報酬。
- ECharts tooltip 等自訂 HTML、Markdown 預覽與 CSV 匯出須處理來源文字的 XSS／公式注入。下載原始 CSV 時保持原字節並明示是未修改的原始證據。
- 報告檔案由 report/artifact registry 解析受限相對路徑，驗證 manifest／checksum，拒絕 traversal、跨帳本與非預期 symlink；私人檔案不經公開 static/media 路由。
- 保留 ODS／Markdown／PDF 原有公式、快取、字型、圖表與校驗；提供既有詳細 CSV／JSON、持倉／歷史／流量等匯出與選定報告 ZIP。匯出範圍／未知狀態必須可核對。
- 三語 Web UI 共用 locale ID 與術語；來源名稱、reference 與機器 key 保持原文。所有原有精度、日期、成本與資料完整性政策沿用。

API 以 `/api/v1` 為目標 namespace，按 auth、portfolios、uploads/previews、jobs、reports/artifacts、balances/events、flows 與 settings 分組。完整 request/response schema、錯誤碼及 generated TS client 在各階段測試固定；不將尚未存在的 URL 寫成操作教學。

## 持久化、備份與還原

Named volume 保存完整 `/data`；映像升級與一般容器重建保留資料，但 volume 持久化本身不是異機備份。清楚說明刪除 volume 的效果，文件不把帶刪除資料選項的命令當正常更新步驟。

完整 instance 備份需包含：網站資料庫、各帳本 SQLite、原始 CSV／參考證據、所有歷史報告與設定、必要 secrets／版本 metadata、uploads 及可恢復的 job 關聯。授權金鑰／密碼 hash 所在的備份應視為私人資料，與可分享的報告／資料匯出分開。

1. 進入明確維護模式，阻止新 Web／CLI 寫入及 worker 領取工作，等待執行中提交到安全邊界。
2. 取得 instance／帳本鎖，以 SQLite backup API 製作一致副本；複製不可變證據與報告，不直接複製正在寫入的 DB 檔。
3. 附 schema／程式版本、相對路徑、每檔 SHA-256、資料庫 integrity／foreign-key 檢查、帳本邏輯 fingerprint 與備份範圍。
4. 原子完成新備份，驗證後才解除維護。備份放在不同目的地或明確下載保存；保留策略不自動刪原始資料。
5. 還原至新的空 volume／目錄，先驗證 archive 路徑／大小／hash／版本與資料關聯，再啟用服務；不覆寫活動帳本。
6. 還原後撤銷既有登入 session，工作標示需核對／恢復，不重新匯入已提交資料。金融內容維持備份版本，網站 auth metadata 的撤銷另記錄。

首版備份採明確手動動作；排程備份另列，不因提供背景 worker 就自動排程。SQLite 檔案未加密的現況不變；完整保護仍依部署者的磁碟與備份儲存政策。

## 現有 CLI 帳本採用

採「複製／驗證／切換」，保留原副本。

- 來源停止寫入，以唯讀來源連線製作 DB backup；複製原始證據、歷史報告、設定與必要恢復檔案。
- 保留帳戶／快照／訂單／餘額／事件／來源 ID、revision、來源字節與 hash、凍結 FX／價格、期初量、報告及 locale／成本政策。
- 比對 schema／資料列／關聯與邏輯 fingerprint；SQLite backup 的檔案雜湊可能不同，不以它單獨判斷金融內容改變。
- 舊稽核 metadata 的原路徑保持證據身分；服務用單獨的經驗證相對路徑映射存取新位置，不重寫舊 manifest 或接受瀏覽器任意主機路徑。
- 有未完成提交時先核對；可證明資料已提交的報告 operation 走固定上下文恢復。未知中斷狀態保留 needs_review。
- 不重交 CSV、不重算歷史、不產生新基準或供款。切換失敗保留可用舊 CLI 工作區，正式私人遷移另明確執行。

## Docker 與發布

- 同一個版本化映像用不同命令執行 web/API 與 worker；前端 multi-stage build 產生靜態資源後放入 Python runtime。
- 正式 runtime 非 root；程式層可唯讀，temp／cache 有明確可寫位置；不掛載 Docker socket。
- 預設 loopback，提供 HTTPS／反向代理部署契約、trusted hosts/proxy 與 cookie 設定。Secrets 由私人檔案／volume 提供，不放入映像、前端 Vite 變數或原始碼。
- 字型、前端元件／圖表靜態資源隨映像提供，無第三方 CDN／分析追蹤。官方 ETF／價格／FX 查詢按既有 registry，不把私人帳戶／金額作 request payload。
- `.dockerignore` 與 Dockerfile COPY 白名單共同限制 build context；排除 DB、原始來源、私人報告、備份、設定、登入資訊、.git 及工作檔。
- CI 使用乾淨公開 checkout 與合成資料，驗證映像內容及 volume 重啟。容器映像公開發布須在相應測試與授權範圍內執行，不能使用維護者完整私人 checkout 當任意 build context。
- 開發仍用 feature branch＋PR，先測試與隱私／歷史檢查，不自動合併。Web 功能尚未存在時 README 明示 planned。

## 分階段實作與驗收

| ID | Deliverable | Acceptance |
|---|---|---|
| WEB-001 | Workspace resolver and shared application service | 所有日常 CLI 使用外部帳本；舊用法相容；兩帳本互不讀寫；程式目錄唯讀仍能產生三格式；合成遷移前後內容一致 |
| WEB-002 | FastAPI, owner/session, metadata migrations and Compose foundation | 登入／登出／撤銷／CSRF／節流／跨帳本／路徑攻擊測試；無 owner 不可公開接管；容器重建保存設定 |
| WEB-003 | Upload, offline preview, Huey worker and recovery | 相同提交不雙計；預檢過期拒絕；kill/restart 各提交邊界；資料已保存／報告失敗可續跑；未知狀態 fail closed |
| WEB-004 | React dashboard, tables, charts and report library | 三幣與三語一致；缺月／未知／沿用旗標；帳本切換與登出清除快取；桌面／手機、鍵盤與 tooltip 安全驗收 |
| WEB-005 | Data/report exports and consistent backup/restore | 三格式與 API payload 一致；私人下載均受保護；新空 volume 還原後原始證據與金融內容一致 |
| WEB-006 | Advanced finance forms and adoption | BTC 期初／餘額／事件與 balance ID 歸因、修訂／作廢、資金流／涵蓋；既有 CLI 與新工作區完整互通 |
| WEB-007 | Container/release acceptance and operating guide | 乾淨安裝／升級／重啟／異機備份演練、映像隱私、支援平台 smoke tests、鎖定依賴／授權與完整操作文件 |

每階段獨立 PR 與可用驗收；不把七項一次標完成。現有 CLI 測試與財務不變式持續通過。正式個人帳本不得當開發 fixture；所有截圖、CI、示範與 benchmark 使用合成資料。

## 官方參考

- [FastAPI password hashing](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)：使用密碼函式庫；本設計另選 server-side session，不因範例採 JWT 就複製其部署政策。
- [Huey guide](https://huey.readthedocs.io/en/stable/guide.html)：SQLite storage、consumer 與 task 功能；可靠恢復另依本文件的 job/operation 契約。
- [SQLite backup API](https://www.sqlite.org/backup.html)：一致資料庫副本。
- [Docker volumes](https://docs.docker.com/engine/storage/volumes/)：容器外的持久化資料。
- [React Router SPA](https://reactrouter.com/how-to/spa)、[TanStack Query](https://tanstack.com/query/latest/docs/framework/react/overview)：前端路由及 server-state 管理。
