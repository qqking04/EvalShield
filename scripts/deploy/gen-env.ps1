param([string]$Out = 'backend\.env')

# ES7-K-1 修复：原 `&( $rand 48 )` 括号内是表达式模式（非调用模式），
# PS5.1（客户干净机默认 shell）直接 ParserError: Unexpected token '48'。
# 改为显式函数调用；随机源用 RandomNumberGenerator 保证不可预测。
function New-RandToken {
    param([ValidateRange(8, 128)][int]$Length = 48)
    $chars = [char[]](48..57 + 65..90 + 97..122)
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $bytes = New-Object byte[] $Length
        $out = New-Object char[] $Length
        $rng.GetBytes($bytes)
        for ($i = 0; $i -lt $Length; $i++) {
            $out[$i] = $chars[[int]$bytes[$i] % $chars.Length]
        }
        return (-join $out)
    } finally {
        $rng.Dispose()
    }
}

$lines = @(
    ('SECRET_KEY=' + (New-RandToken 48)),
    ('WEBHOOK_SECRET=' + (New-RandToken 40)),
    'DATABASE_URL=postgresql+asyncpg://evalshield:CHANGE_ME@127.0.0.1:5432/evalshield',
    'EDITION=enterprise',
    'DEEPSEEK_API_KEY='
)

# .env 必须无 BOM（PS5.1 的 Set-Content -Encoding UTF8 会写 BOM，
# dotenv 会把首键读成 \ufeffSECRET_KEY 致配置失效）
# $Out 支持相对（基于当前目录）与绝对两种形态
$full = if ([System.IO.Path]::IsPathRooted($Out)) {
    [System.IO.Path]::GetFullPath($Out)
} else {
    [System.IO.Path]::GetFullPath((Join-Path (Get-Location -Provider FileSystem).Path $Out))
}
$dir = Split-Path $full
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
[System.IO.File]::WriteAllLines($full, $lines, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "generated $Out - fill DATABASE_URL password and DEEPSEEK_API_KEY before start"
# check-ignore self-proof (product must never be visible to git)
git check-ignore -v $Out 2>$null
if ($LASTEXITCODE -ne 0) { Write-Warning "$Out is NOT git-ignored - add to .gitignore before committing" }
