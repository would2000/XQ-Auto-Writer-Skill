# 單人維護流程

本專案預設由一位維護者管理。Pull Request 是合併前的安全檢查點，不代表需要第二位審查者。

## 日常修改

1. 從最新 `main` 建立 `agent/<description>` 分支。
2. 大型功能建立 GitHub Issue；小型文件或修正可直接在 PR 說明原因。
3. 把使用者可見變更新增到 `CHANGELOG.md` 的 `[Unreleased]`。
4. 執行本機驗證後推送並建立 Draft PR。
5. 等待 `CI / verify` 通過，檢查變更範圍後自行 Squash merge；不要求第二人 approval。
6. 合併後確認 `main` 的 CI 再次通過。

## CI 與 XQ 的界線

GitHub Actions 只驗證版本 metadata、公開儲存庫衛生、單元測試、Python 語法與 submodule 狀態。標準 runner 沒有登入後的互動式 XQ 桌面，因此 CI 成功不能視為 XScript 已完成真實編譯。

修改 UI selector、建檔、編譯或 XScript 行為時，仍須在本機已登入 XQ、桌面解鎖的 Windows 工作階段執行適用的最小編譯測試，並在 PR 明確記錄 Passed、Partially Passed、Failed 或 Unable to Test。

## 緊急 bypass

日常開發不得使用管理員 bypass。只有 CI 或 Ruleset 本身故障、且正常 PR 無法修復時才能暫時使用；事後必須建立 Issue，記錄原因、操作、影響與恢復狀態。不得用 bypass 跳過失敗的產品測試或未驗證的 XQ 變更。

## 發布

Tag 與 GitHub Release 維持人工發布。每次發布使用獨立 release PR 更新 `VERSION` 與 CHANGELOG；合併並重新驗證後，取得明確授權才建立新的 annotated `v<版本>` tag。GitHub Release 必須先建立為 Draft，核對 tag、commit、說明及全部附件後才正式發布。發布後以 `gh release verify` 與 `isImmutable: true` 驗證 attestation 與不可變狀態。已發布 tag 或附件不得移動、替換或刪除，修正使用新的 PATCH 版本。

## 復原

- PR 合併前：修正或關閉功能分支。
- Workflow 錯誤：以新的 PR 修正或 revert，不重寫 `main`。
- Ruleset 誤鎖：先切換為 Disabled，再修正必要 check 名稱或條件。
- 尚未發布的 Draft 有問題：直接修正 Draft 並重新核對。
- Immutable Release 已發布後有問題：發布 PATCH 版本，不移動舊 tag、不替換附件，也不重用版本名稱。
