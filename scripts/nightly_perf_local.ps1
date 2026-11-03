# ES11 本机夜间性能基线任务（GitHub origin 未配置前的替代链路）
# 每周由任务计划程序调用：采集 P95 → 环比劣化检查（>20% 非 0 退出）→ 基线 commit 入库
# 注册（管理员 PowerShell，一次性）：
#   schtasks /Create /TN EvalShield-NightlyPerf /SC WEEKLY /D SUN /ST 02:00 ^
#     /TR "powershell -NoProfile -ExecutionPolicy Bypass -File E:\code\EvalShield\scripts\nightly_perf_local.ps1" ^
#     /RL LIMITED
$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$log = Join-Path $Root 'logs\nightly_perf_local.log'
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null

"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] === collect start ===" | Out-File -Append $log
python scripts/collect_es11_perf.py *>> $log
$rc = $LASTEXITCODE
"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] collect rc=$rc" | Out-File -Append $log

# 无论劣化与否都保留当夜基线（趋势不断档）；rc=1 时 commit 信息标注告警
git add verification/perf-baselines/es11-*.json 2>> $log
if (-not (git diff --cached --quiet)) {
    $msg = if ($rc -eq 1) { "chore(perf): nightly es11 baseline [REGRESSION ALERT rc=1]" }
           else { "chore(perf): nightly es11 baseline" }
    git commit -m $msg 2>> $log
    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] baseline committed" | Out-File -Append $log
} else {
    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] no baseline change to commit" | Out-File -Append $log
}
exit $rc
