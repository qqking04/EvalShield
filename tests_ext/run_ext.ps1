$ErrorActionPreference = 'Stop'
# ES8-BUG-013 联调跑通脚本：起 Keycloak + EvalShield 栈 → 冒烟 SSO/支付沙箱用例。
# 前置：本机可用 docker；tests_ext/env.sandbox 已按 example 填写。
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $dir

if (-not (Test-Path 'env.sandbox')) { Write-Host 'FAIL: 缺少 env.sandbox（复制 env.sandbox.example 填写）' -ForegroundColor Red; exit 2 }

docker compose -f docker-compose.ext.yml --env-file env.sandbox up -d --build
Write-Host '==> 等待 /api/health ...'
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    try {
        $r = Invoke-WebRequest -Uri 'http://localhost:8000/api/health' -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch { }
}
if (-not $ok) { Write-Host 'FAIL: 服务未在 60s 内就绪，docker compose logs 排查' -ForegroundColor Red; exit 1 }

python -m pytest . -m ext -q
$code = $LASTEXITCODE

# 截图/证据归档目录（人工补 M2-E*/M10-E* 通过证据后关闭本项）
New-Item -ItemType Directory -Force -Path '..\verification\ext-run' | Out-Null
Write-Host "==> 证据归档目录：verification/ext-run/ （pytest 退出码 $code）"
exit $code
