# 将仓内钩子部署到目标仓。换机/误删后一条命令重建流水线。
# -Local：部署本地提交闸门 pre-commit 到本仓 .git/hooks/；否则部署双钩到 bare 发布仓。
param(
    [switch]$Local,
    [string]$BareRepo = 'E:\setup package\evalshield-release.git'
)
$ErrorActionPreference = 'Stop'
if ($Local) {
    $hookDir = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) '.git\hooks'
    if (-not (Test-Path $hookDir)) { throw "非 git 工作树（无 .git/hooks）: $hookDir" }
    $names = @('pre-commit')
} else {
    if (-not (Test-Path (Join-Path $BareRepo 'hooks'))) { throw "非 bare 仓或无 hooks 目录: $BareRepo" }
    $hookDir = Join-Path $BareRepo 'hooks'
    $names = @('post-receive', 'pre-receive')
}
foreach ($name in $names) {
    $src = Join-Path $PSScriptRoot $name
    $dst = Join-Path $hookDir $name
    # LF 校验前置：钩子必须是 LF 换行，bash 遇 CRLF 会报 bad interpreter。
    # 先验源文件再拷贝，坏钩子不落目标仓（ES-6-H-1）
    $bytes = [IO.File]::ReadAllBytes($src)
    if ($bytes -contains 13) { throw "钩子含 CR（CRLF），需转 LF 后再部署：$src" }
    Copy-Item $src $dst -Force
    Write-Host "hook installed -> $dst"
}
Write-Host "LF check OK"
