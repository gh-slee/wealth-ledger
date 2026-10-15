# 公開版本與開發發布

正式追蹤工具不需要 Git、GitHub、GitHub CLI 或 LLM。本文件的開發工具只用於維護公開程式；一般 CSV 匯入、BTC 更新與報告重產不會上傳任何內容。

## 公開範圍

公開版本包含程式、測試、合成示範、通用文件、明確列出的設定範例、字型及授權、建置設定與 CI。公開路徑由 `scripts/check_publication.py` 的白名單定義；新類型的檔案須先審查，再修改白名單。

以下內容保留本機：`data/`、`reports/`、`backups/`、`work/`、`private/`、產生的輸出、資料庫及其 sidecar、個人設定、登入資訊、編輯器狀態、私人交接。`config/` 只允許明確命名的範例及公司別名檔案。不要用 `git add .`：每次明確指定已審查的公開檔案。

`.gitignore` 只能阻止尚未追蹤的檔案；曾經提交後再刪除的敏感內容仍存在歷史中。發布檢查另外掃描整個 Git index 與所有將發布的提交，包含已刪除的舊檔案版本。掃描使用 NUL 分隔的 Git 輸出，拒絕未知路徑、符號連結、submodule、未解決合併、典型憑證、私鑰、機器特定家目錄及私人 fixture 標記。Git 作者與提交者電子郵件須採 GitHub `users.noreply.github.com` 身分。

**模式掃描不能證明完全沒有個人資料。** 財務數字或一般文字不一定有可辨識特徵；首次發布及新增範例仍須人工審查檔案清單、內容與來源。允許的字型及官方格式 fixture 也須核對授權、來源及合成性質，不能把個人 CSV 改名為範例。

## 首次公開準備

首次 repository 建立及推送與日後功能開發分開處理。先隔離私人資料，取得可審閱的公開 manifest，完成乾淨安裝與測試，再明確核准首次遠端建立／發布。以下檢查不建立 Git repository、不連網、不推送：

```bash
python scripts/check_publication.py --worktree --manifest private/publication/worktree-manifest.json
```

輸出 `passed`、公開路徑、檔案大小、SHA-256 及違規原因。manifest 本身放在忽略目錄。掃描不輸出憑證內容。來源檔案不通過時，先處理問題；不要關閉檢查或改成掃描空範圍。

Git 初始化並刻意加入公開檔案後，可以依序執行：

```bash
python scripts/check_publication.py --staged
python scripts/check_publication.py --all-history
```

`--staged` 檢查整個 index，包含本次未修改但已追蹤的私人檔案。`--all-history` 須在第一個提交存在後執行，檢查 HEAD 全部可到達歷史及提交文字／身分；沒有有效 ref 時會停止，不視為通過。也可用 `--outgoing origin/main` 僅查指定基準以外的歷史；正式發布工具會額外先檢查全部歷史。

首次公開後，維護者自行登入 GitHub CLI，確認遠端及 commit 身分，不把 token 寫進專案或聊天。使用 GitHub 提供的 noreply 電子郵件；不是捏造第三方地址。登入、建立 repository 與設定實際 remote 都需要明確授權。

## 本機發布授權

複製 `config/publish.example.toml` 為 **Git 忽略的** `config/publish.local.toml`，填入自己維護的實際 repository，再設定 `authorized = true`。這是本機維護者允許未來已授權開發產生 feature branch 與 PR 的紀錄；不是追蹤工具的一般設定，也不代表任意新增功能已獲授權。

設定包含：

- `host`：目前僅支援 `github.com`。
- `repository`：自己的 `OWNER/REPOSITORY`。
- `remote`：已設定的 Git remote，例如 `origin`。
- `feature_prefix`：允許的分支前綴，例如 `feature/`。
- `create_pr = true`：每次使用功能分支及 PR；不直接推 default branch，不強制推送，不合併 PR。

遠端 fetch URL 及全部 push URL 必須與本機授權精確相符；只允許沒有內嵌憑證的 HTTPS 或 Git SSH URL。工具不自動建立 repository。`refs/remotes/origin/HEAD` 等遠端預設分支資訊必須已設定；尚未取得時由維護者確認後執行 `git remote set-head origin --auto`，不猜測基準分支。

## 日後開發流程

1. 依當次使用者授權完成程式與文件修改。
2. 檢視差異，刻意 stage 要發布的公開檔案。不要 stage 其他工作；工具不自動 `git add`。
3. 將可公開的 PR 說明寫入本機文字檔，例如忽略目錄中的 `private/publication/pr-body.md`。說明問題、結果及驗證，不含本機財務狀態。
4. 先取得發布計畫，再加 `--execute` 執行。

```bash
git add -- src/wealth_ledger/example.py tests/test_example.py docs/user-manual.md
python scripts/dev_publish.py \
  --branch feature/example-improvement \
  --message "Improve input validation" \
  --title "Improve input validation" \
  --body-file private/publication/pr-body.md
```

預設只顯示計畫，保持 branch、index 及提交不變。正式執行使用相同參數加上 `--execute`：

```bash
python scripts/dev_publish.py \
  --branch feature/example-improvement \
  --message "Improve input validation" \
  --title "Improve input validation" \
  --body-file private/publication/pr-body.md \
  --execute
```

正式流程依序檢查本機授權／remote／身份／index／歷史，確認 `gh` 登入及 repository，fetch 更新遠端資訊，重新檢查，執行完整 unittest 套件，測試後再檢查；HEAD、分支、index 內容或 PR 說明若改變即停止，要求重新審查。確認一致後僅 commit 已 stage 的變更，掃描待推提交，正常 push 功能分支，建立或沿用該分支的開啟中 PR。輸出包含 PR URL。LLM 開發工作階段若建立 PR，還須依當時 Codex 工具規則將 PR 附加至該工作階段；程式本身不依賴 Codex。

不接受未 stage 的 tracked 變更。未追蹤檔案不會自動加入；不會因旁邊有私人 CSV 而上傳。新分支只能由沒有本機額外提交的預設分支建立。要沿用已存在的功能分支，先自行切換到該分支，再執行工具，避免切入不相關工作。

如果測試、commit、push 或 PR 階段失敗，工具停止，不回滾或刪除既有提交。修正原因後檢查目前分支／index／遠端；已 commit 的變更可在同一分支重試，既有開啟中 PR 會沿用。不要用 force push 解決掃描失敗。首次 push 成功而 PR 建立失敗時，分支可能已存在遠端，這不代表整個流程尚未發布。

## Git hooks 與限制

可選擇啟用 repository 專用 hooks，不修改全域 Git 設定：

```bash
python scripts/install_git_hooks.py
```

`pre-commit` 檢查整個 index；`pre-push` 從 Git 標準輸入取得待推 ref，掃描每個 ref 的全部可到達歷史，拒絕自動刪除分支。hooks 缺 Python／Git 或檢查無法完成時會阻止操作。Git hooks 可被維護者繞過，因此不能代替內容審查；CI 在上傳後才執行，也不能防止首次洩漏。

檢查工具退出碼：`0` 通過、`1` 發現違規、`2` 無法完成檢查。發布工具失敗退出 `2`。所有測試只使用隔離暫存 repository、合成資料或模擬命令，不接觸正式帳本或遠端。
