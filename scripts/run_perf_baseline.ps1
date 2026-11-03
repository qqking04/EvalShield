# ES8-BUG-009 性能基线采集脚本（短压）
# 用法:
#   powershell -File scripts/run_perf_baseline.ps1                       # 全部 4 场景
#   powershell -File scripts/run_perf_baseline.ps1 -Scenario quality     # 单场景
# 参数:
#   -Scenario  quality|platform|ingest|retention|all (默认 all)
#   -Host_     目标地址 (默认 http://localhost:8000)
#   -Duration  locust -t 时长 (默认 10s)
#   -Users     并发用户 (默认 5)  -SpawnRate 孵化速率 (默认 5)
# 结果 JSON 落 verification/perf-baselines/<scenario>-<date>.json
param(
    [string]$Scenario = "all",
    [string]$Host_ = "http://localhost:8000",
    [string]$Duration = "10s",
    [int]$Users = 5,
    [int]$SpawnRate = 5
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$outDir = Join-Path $repoRoot "verification\perf-baselines"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

# locust 可用性检查（未安装则明确报错退出，不静默）
# 注意：locust --version 退出时 gevent 会向 stderr 打印无害清理噪音，
# 在 $ErrorActionPreference=Stop 下会被 PowerShell 当作 NativeCommandError 抛出。
# 这里临时降级错误处理，只采集 stdout 判定版本可用性。
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$locustVer = (& python -m locust --version 2>$null) | Out-String
$locustExit = $LASTEXITCODE
$ErrorActionPreference = $prevEAP
if ($locustExit -ne 0 -or -not $locustVer.Trim()) {
    Write-Host "未找到 locust（python -m locust 不可用），请先安装：pip install locust" -ForegroundColor Red
    exit 2
}
Write-Host "locust: $($locustVer.Trim())"

$locustfile = Join-Path $PSScriptRoot "locustfile_es8.py"
$scenarios = if ($Scenario -eq "all") { @("quality", "platform", "ingest", "retention") } else { @($Scenario) }
$date = Get-Date -Format "yyyyMMdd"

foreach ($s in $scenarios) {
    Write-Host "`n=== 采集场景: $s (tag=$s, -t $Duration, -u $Users) ===" -ForegroundColor Cyan
    $csvPrefix = Join-Path $env:TEMP ("es8perf_{0}_{1}" -f $s, (Get-Date -Format "HHmmss"))
    & python -m locust -f $locustfile --headless -t $Duration -u $Users -r $SpawnRate `
        --tags $s --host $Host_ --csv $csvPrefix
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "场景 $s locust 退出码 $LASTEXITCODE（目标服务不可达或鉴权失败？），跳过落盘"
        continue
    }
    $statsCsv = Get-ChildItem -Path "$csvPrefix*.csv" | Where-Object { $_.Name -notmatch "failures|exceptions" } | Select-Object -First 1
    if (-not $statsCsv) {
        Write-Warning "场景 $s 未生成 stats CSV，跳过落盘"
        continue
    }
    # 取 Aggregated 行（或单端点行）汇总为基线 JSON
    $rows = Import-Csv -Path $statsCsv.FullName
    $agg = $rows | Where-Object { $_.'Name' -eq 'Aggregated' } | Select-Object -First 1
    if (-not $agg) { $agg = $rows | Select-Object -Last 1 }
    $baseline = [ordered]@{
        scenario      = $s
        collected_at  = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss")
        host          = $Host_
        duration      = $Duration
        users         = $Users
        locust_version = $locustVer.Trim()
        # 判据口径（对齐 backend/tests/test_es8_perf_baseline.py）
        p95_ms        = [double]$agg.'95%'
        p50_ms        = [double]$agg.'50%'
        avg_ms        = [double]$agg.'Average Response Time'
        max_ms        = [double]$agg.'Max Response Time'
        request_count = [int]$agg.'Request Count'
        failure_count = [int]$agg.'Failure Count'
        rps           = [double]$agg.'Requests/s'
        endpoints    = ($rows | Where-Object { $_.'Name' -ne 'Aggregated' } | ForEach-Object {
            @{ name = $_.'Name'; p95_ms = [double]$_.'95%'; count = [int]$_.'Request Count' }
        })
    }
    $outFile = Join-Path $outDir ("{0}-{1}.json" -f $s, $date)
    $baseline | ConvertTo-Json -Depth 5 | Set-Content -Path $outFile -Encoding UTF8
    Write-Host "基线已写入 $outFile (P95=$($baseline.p95_ms)ms, n=$($baseline.request_count))" -ForegroundColor Green
    Get-ChildItem -Path "$csvPrefix*.csv" | Remove-Item -Force -ErrorAction SilentlyContinue
}
