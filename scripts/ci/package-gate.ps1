# EvalShield 深度回归通道（发版前必跑；日常低频）
# 四段：P1 全量后端 pytest → P2 出包+打包面用例 → P3 前端 vitest/build → P4 F1 bundle 残留扫描
# exit 0 = 全绿；任一失败立即终止并透传非零码
#
# §4.3-1 核对定稿（2026-10-18）：frontend/vite.config.js L9 `__EDITION__` 缺省 = 'community'。
#   因此 P3 构建前显式 $env:EDITION='enterprise'（对应 BUG-8：enterprise 页面验证必须带该变量），
#   P4 主判据 = OSS 源码树 grep（私有树 enterprise 构建产物天然含商业组件，不作 F1 判据）。
# §4.3-2 核对定稿：release_oss.sh 为纯静态出包（compileall + 路由基线对账），
#   不依赖 8000 活体实例，P2 可在服务停机时执行——与 T1 钩子 stage2 互补。
param(
    [switch]$SkipFrontendBuild   # 仅调试其它段时用
)
$ErrorActionPreference = 'Stop'
$ROOT = 'e:\code\EvalShield'
Set-Location $ROOT

function Step($name, $body) {
    Write-Host "`n===== $name ====="
    # 原生命令（python/npx/bash）的 stderr 在 Stop 模式下会抛终止错误（假失败）：
    # 段内临时切 Continue，成败一律以退出码判定
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $rc = 0   # 新会话 $LASTEXITCODE 未定义：纯 cmdlet 段不跑原生命令时防 $null -ne 0 假失败
        & $body
        if ($null -ne $LASTEXITCODE) { $rc = $LASTEXITCODE }
    } finally {
        $ErrorActionPreference = $prev
    }
    if ($rc -ne 0) { Write-Host "FAIL: $name (exit $rc)"; exit $rc }
    Write-Host "PASS: $name"
}

# P0 交付 .ps1 编码断言（ES7-M-7：PS5.1 对含非 ASCII 的 UTF-8 无 BOM 脚本按 GBK 误读 → ParserError）
# 判据：scripts/ 与 tests/ 下所有含非 ASCII 字节的 .ps1，首三字节必须为 EF BB BF
Step 'P0 ps1 encoding gate (UTF-8 BOM)' {
    $bad = @()
    $ps1s = Get-ChildItem "$ROOT\scripts","$ROOT\tests" -Recurse -Filter *.ps1 -File -ErrorAction SilentlyContinue
    foreach ($f in $ps1s) {
        $b = [System.IO.File]::ReadAllBytes($f.FullName)
        $hasBom = ($b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF)
        $nonAscii = $false
        foreach ($byte in $b) { if ($byte -gt 0x7F) { $nonAscii = $true; break } }
        if ($nonAscii -and -not $hasBom) { $bad += $f.FullName }
    }
    if ($bad) { $bad | ForEach-Object { Write-Host "FAIL(no BOM, non-ASCII): $_" }; exit 1 }
}

# P1 全量后端（依赖本机 PG 种子库；活体引擎用例已在测试内 self-skip，见 T4 后终态）
Step 'P1 pytest full' {
    Push-Location "$ROOT\backend"
    python -m pytest tests/ -q --no-header | Select-Object -Last 3
    Pop-Location
}

# P2 出包 + 打包面用例（A1/A2/A4/A6/H1/G1 持续化）
Step 'P2 release_oss + package tests' {
    # release_oss.sh 需要 bash + rsync/tar（本机 Git Bash 已具备）
    & 'C:\Program Files\Git\bin\bash.exe' -lc "cd /e/code/EvalShield && PYTHON=python ./scripts/release_oss.sh"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $ver = (Select-String 'APP_VERSION:' backend\app\config.py | Select-Object -First 1).Line -replace '.*"([^"]+)".*','$1'
    $env:OSS_DIR = "$ROOT\dist\oss\evalshield-oss-$ver"
    Push-Location "$ROOT\backend"
    # 完整输出直通终端：管道 Select-Object 会吞 stdout，且 bash/python 原生 stderr
    # 经 2>&1 重定向会被 $ErrorActionPreference=Stop 误抛 NativeCommandError（P2 曾因此假失败）
    python -m pytest tests/test_version_isolation_package.py -q --no-header
    $rc = $LASTEXITCODE
    Pop-Location
    if ($rc -ne 0) { exit $rc }
}

# P3 前端回归（vitest 用例 + enterprise 构建可重现）
if (-not $SkipFrontendBuild) {
    Step 'P3 frontend vitest + build' {
        Push-Location "$ROOT\frontend"
        # 同 P2：避免管道吞输出 + stderr 被 Stop 误抛
        npx vitest run
        if ($LASTEXITCODE -ne 0) { Pop-Location; exit $LASTEXITCODE }
        # §4.3-1 定稿：显式 enterprise，验证商业分支构建可重现（F1 判据交给 P4 OSS 源码 grep）
        $env:EDITION = 'enterprise'
        npm run build
        $rc = $LASTEXITCODE
        Pop-Location
        if ($rc -ne 0) { exit $rc }
    }

    # P4 F1 判据：OSS 源码树无商业字面量（strip_fe.js 在 release_oss [2b/6] 已内置 exit 1 终判，此处双保险）
    Step 'P4 OSS source residual scan (F1)' {
        $ossDirs = Get-ChildItem "$ROOT\dist\oss" -Directory | Sort-Object LastWriteTime
        if (-not $ossDirs) { Write-Host 'FAIL: dist\oss 为空，P2 未产出包'; exit 1 }
        $ossSrc = Join-Path $ossDirs[-1].FullName 'frontend\src'
        if (-not (Test-Path $ossSrc)) { Write-Host "FAIL: OSS 包缺 frontend/src：$ossSrc"; exit 1 }
        Write-Host "[P4] scanning $ossSrc"
        # 主判据：OSS 前端源码 grep 商业字面量（大小写敏感，与 strip_fe.js 终判同口径：
        # 社区版合法的 JailbreakSamples 页/pii_leakage 枚举不属于剥离面）
        $srcHits = Get-ChildItem $ossSrc -Recurse -Include *.jsx,*.js |
                   Select-String -Pattern 'JAILBREAK|PII_LEAK' -List -CaseSensitive
        if ($srcHits) { $srcHits | Select-Object -First 5; exit 1 }
        # 辅判据（§4.3-1 备注）：若出包含 frontend/dist 构建产物，则扫描 bundle
        $ossDist = Join-Path (Join-Path $ossDirs[-1].FullName 'frontend\dist') 'static'
        if (Test-Path $ossDist) {
            $pat = 'AIDiscover|SrcAudit|CostDashboard|src-audit|JailbreakReport|PIILeakReport'
            $hits = Select-String -Path "$ossDist\*.js" -Pattern $pat -List -ErrorAction SilentlyContinue
            if ($hits) { $hits | Select-Object -First 5; exit 1 }
        }
    }
}

Write-Host "`n[package-gate] ALL PASS"
