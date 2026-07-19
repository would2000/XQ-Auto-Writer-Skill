# 版本與發布流程

本文件是 XQ Auto Writer Skill 的人工發布程序。GitHub Actions 只做唯讀驗證，不自動建立 tag 或 Release；完整單人開發方式另見[單人維護流程](SOLO-MAINTENANCE.md)。儲存庫啟用 [Release Immutable](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases) 後，只會保護未來發布的 Release，不會追溯改變既有版本。

## 版本來源

- `VERSION` 是目前版本的唯一機器可讀來源，內容不含 `v`，例如 `0.1.0`。
- `CHANGELOG.md` 必須有且只有一個 `[Unreleased]`，並包含與 `VERSION` 相同的正式版本標題。
- Git tag 與 GitHub Release 在版本前加 `v`，例如 `v0.1.0`。
- 已推送的 tag 不得移動或重用。修正已發布版本時建立新的 PATCH 版本。

## 版本選擇

| 變更 | 版本調整 | 範例 |
| --- | --- | --- |
| 相容的新功能或知識來源 | MINOR | `0.1.0` → `0.2.0` |
| 錯誤、UI selector 或解析器修正 | PATCH | `0.1.0` → `0.1.1` |
| CLI、JSON 契約或設定格式的不相容變更 | MAJOR | `1.2.0` → `2.0.0` |
| 只有文件或測試調整 | 通常不單獨發布 | 累積到下一版本 |

`1.0.0` 以前代表公開介面仍可能調整。不相容變更仍必須在 CHANGELOG 與 Release Notes 中清楚說明。

## 每個功能的開發流程

1. 大型功能建立 GitHub Issue；小型文件或修正可直接由 PR 說明，不另外維護第二套功能編號。
2. 從最新 `main` 建立 `agent/<description>` 分支。
3. 開發期間把使用者可見變更加入 `CHANGELOG.md` 的 `[Unreleased]`。
4. 執行本文件的驗證命令。
5. 推送分支並建立 Draft PR；適用時連結 Issue，列出本機測試、CI 與 XQ UI 驗證狀態。
6. `CI / verify` Passed 後由單一維護者自行 Squash merge；不要求第二人 approval，不得對公開的 `main` 使用 force push。

## 準備正式版本

1. 決定 MAJOR、MINOR 或 PATCH。
2. 更新 `VERSION`。
3. 將 `[Unreleased]` 的內容移到 `## [x.y.z] - YYYY-MM-DD`，並保留新的空白 `[Unreleased]`。
4. 更新 README 中的目前版本與必要的升級步驟。
5. 建立 `chore(release): vx.y.z` PR，通過檢查並合併。

## 發布前驗證

在專案根目錄執行：

```powershell
python scripts/check_release_metadata.py
python scripts/check_repository_hygiene.py
python -W error::ResourceWarning -m unittest discover -s tests -v

$scripts = Get-ChildItem .agents/skills/xq-xscript-compiler/scripts -Filter *.py
python -m py_compile $scripts.FullName scripts/check_release_metadata.py scripts/check_repository_hygiene.py

git diff --check
git status -sb
git submodule status
```

版本驗證器必須回傳 `status: success`。工作樹必須乾淨，submodule 必須固定在預期提交。

本地檢查不等於 XQ GUI 驗證。凡是修改 UI selector、建檔或編譯流程，都必須在已登入 XQ 且桌面解鎖的 Windows 環境，使用不含真實交易指令的最小腳本驗證成功、錯誤及修復路徑。

## GitHub 保護設定

- `main` 應要求 PR 與 `CI / verify`，approval 數量為 0，並禁止刪除及 force push。
- `refs/tags/v*` 應允許建立新 tag，但禁止更新或刪除既有 tag。
- Repository Settings 的 Releases 區段應啟用 Release immutability。Tag Ruleset 保護所有 `v*` tag；Release Immutable 另外鎖定已發布 Release 的 tag 與附件，並建立可驗證的 attestation。
- 管理員 bypass 只供 CI 或 Ruleset 故障緊急復原，不得用於跳過失敗的產品測試。
- 變更 Ruleset 後必須從 GitHub API 讀回 target、條件、規則與 enforcement；不要用移動正式 tag 的方式測試。

## 合併後建立 tag

```powershell
git switch main
git pull --ff-only origin main
python scripts/check_release_metadata.py

$version = (Get-Content VERSION -Raw).Trim()
git tag -a "v$version" -m "v$version"
git push origin "v$version"
```

建立 tag 後確認本機與遠端指向相同提交：

```powershell
git rev-parse "v$version^{}"
git ls-remote origin "refs/tags/v$version^{}"
```

## 建立 Draft GitHub Release

先複製並完成 Release Notes，不要直接發布含有預留文字的模板。Release 必須先建立為 Draft，讓維護者在不可變保護生效前核對內容與全部附件：

```powershell
$releaseNotes = Join-Path $env:TEMP "xq-auto-writer-v$version.md"
Copy-Item docs/release-notes-template.md $releaseNotes
notepad $releaseNotes

gh release create "v$version" `
  --repo would2000/XQ-Auto-Writer-Skill `
  --verify-tag `
  --draft `
  --title "v$version" `
  --notes-file $releaseNotes
```

Draft 建立後，必須確認：

1. tag 剝離後的 commit 與已通過 `main` CI 的提交完全一致。
2. Release Notes 沒有預留文字、秘密、本機路徑或未驗證的成功聲明。
3. 所有預定附件都已上傳；若有附件，先記錄檔名與 SHA-256。
4. Draft 不是 prerelease，且版本號尚未被其他 Release 使用。

確認無誤後才正式發布：

```powershell
gh release edit "v$version" `
  --repo would2000/XQ-Auto-Writer-Skill `
  --draft=false `
  --latest
```

## 發布後驗證

Release Immutable 啟用後，正式發布會鎖定關聯 tag 與附件。標題和 Release Notes 仍可修改，但不得把發布後編輯當作補傳或替換附件的方式。

```powershell
gh release verify "v$version" `
  --repo would2000/XQ-Auto-Writer-Skill

gh release view "v$version" `
  --repo would2000/XQ-Auto-Writer-Skill `
  --json tagName,isDraft,isPrerelease,isImmutable,url
```

`gh release verify` 必須成功，且讀回結果必須是 `isDraft: false`、`isPrerelease: false`、`isImmutable: true`。若有自行上傳的附件，再使用 `gh release verify-asset "v$version" <path>` 驗證本機檔案。GitHub 自動產生的 source ZIP／tarball 不適用 `verify-asset`。

## 中斷與回復

- PR 合併前：修正功能分支或關閉 PR，不影響 `main`。
- 已合併但尚未建立 tag：用新的 revert／修正提交處理，不重寫 `main`。
- tag 已推送：不要移動同名 tag；建立 PATCH 版本修正。
- Draft Release 建立或檢查失敗：在正式發布前修正 Draft；不要重新建立程式提交或移動 tag。
- Immutable Release 已發布：不得替換、補傳或刪除附件，也不要刪除 Release；內容有誤時保留原版本並建立新的 PATCH 版本。GitHub 不允許重用曾由 Immutable Release 使用的 tag 名稱。
- `gh release verify` 失敗或 `isImmutable` 不是 `true`：停止宣告發布成功，保存實際錯誤並檢查儲存庫設定；不得以重建同名版本掩蓋問題。
- 第三方 submodule 或 XSHelp 權利狀態不明時停止發布，不把第三方內容納入 MIT 再授權。
