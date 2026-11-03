# EvalShield 发版日脚本（T5 · 优化6说明书 §5.2-2）
# 前置：产品追认已落名（缺陷文档签字表）；master HEAD 即发布内容。
# 本轮（开发期）不执行——git tag 保持为空属预期状态。
# dry-run 语法：.\release-day.ps1 -DryRun（只校验取号与防呆，不打 tag / 不 push）
param([switch]$DryRun)
$ErrorActionPreference = 'Stop'
Set-Location 'e:\code\EvalShield'

# 防呆 1：锚定 `APP_VERSION:` 属性行（注释提及 APP_VERSION 不会抢先命中）
$ver = (Select-String 'APP_VERSION:' backend\app\config.py | Select-Object -First 1).Line -replace '.*"([^"]+)".*','$1'
if (-not $ver) { Write-Host 'FAIL: 未能从 config.py 取到 APP_VERSION'; exit 1 }

# 防呆 2：tag 已存在则拒绝重复打
if (git tag --list "v$ver") { Write-Host "FAIL: tag v$ver 已存在，请勿重复发版"; exit 1 }

# 防呆 3：跟踪文件必须干净（发版内容 = HEAD；untracked 不在 HEAD 中，不阻断——ES-6-V-1）
if ((git status --porcelain --untracked-files=no)) { Write-Host 'FAIL: 工作树有未提交的跟踪变更，先 commit 再发版'; exit 1 }

$today = Get-Date -Format 'yyyy-MM-dd'
if ($DryRun) {
    Write-Host "[DryRun] APP_VERSION=$ver，防呆全部通过；正式发版请去掉 -DryRun 执行"
    exit 0
}
git tag -a "v$ver" -m "EvalShield $ver · 发布日 $today · 版本隔离改造出口准则达成（签字表全落名）"
git push release "v$ver"
Write-Host "tag v$ver created @ $today — 请把根 LICENSE 的 Change Date 更新为 $today + 3 年的绝对日期并单独 commit"
