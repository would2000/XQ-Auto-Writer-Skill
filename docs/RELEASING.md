# 版本與發布流程

本文件是 XQ Auto Writer Skill 的人工發布程序。第一次實際流程驗證完成前，不以 GitHub Actions 自動建立 tag 或 Release。

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

1. 建立 GitHub Issue，使用 Issue 編號追蹤功能，不另外維護第二套功能編號。
2. 從最新 `main` 建立 `agent/<description>` 分支。
3. 開發期間把使用者可見變更加入 `CHANGELOG.md` 的 `[Unreleased]`。
4. 執行本文件的驗證命令。
5. 推送分支並建立 Draft PR；PR 必須連結 Issue、列出測試及 XQ UI 驗證狀態。
6. Review 完成後才合併；不得對公開的 `main` 使用 force push。

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
python -W error::ResourceWarning -m unittest discover -s tests -v

$scripts = Get-ChildItem .agents/skills/xq-xscript-compiler/scripts -Filter *.py
python -m py_compile $scripts.FullName scripts/check_release_metadata.py

git diff --check
git status -sb
git submodule status
```

版本驗證器必須回傳 `status: success`。工作樹必須乾淨，submodule 必須固定在預期提交。

本地檢查不等於 XQ GUI 驗證。凡是修改 UI selector、建檔或編譯流程，都必須在已登入 XQ 且桌面解鎖的 Windows 環境，使用不含真實交易指令的最小腳本驗證成功、錯誤及修復路徑。

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

## 建立 GitHub Release

先複製並完成 Release Notes，不要直接發布含有預留文字的模板：

```powershell
$releaseNotes = Join-Path $env:TEMP "xq-auto-writer-v$version.md"
Copy-Item docs/release-notes-template.md $releaseNotes
notepad $releaseNotes

gh release create "v$version" `
  --repo would2000/XQ-Auto-Writer-Skill `
  --verify-tag `
  --title "v$version" `
  --notes-file $releaseNotes
```

發布後以 `gh release view "v$version"` 讀回版本、tag、URL 與發布狀態。

## 中斷與回復

- PR 合併前：修正功能分支或關閉 PR，不影響 `main`。
- 已合併但尚未建立 tag：用新的 revert／修正提交處理，不重寫 `main`。
- tag 已推送：不要移動同名 tag；建立 PATCH 版本修正。
- Release 建立失敗：修正 Release Notes 後重試同一個已驗證 tag，不重新建立程式提交。
- 第三方 submodule 或 XSHelp 權利狀態不明時停止發布，不把第三方內容納入 MIT 再授權。
