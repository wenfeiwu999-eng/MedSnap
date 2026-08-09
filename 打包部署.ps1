# MedSnap 打包脚本 (PowerShell)
# 右键此文件 → 使用 PowerShell 运行
# 或在 PowerShell 中执行: .\打包部署.ps1

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectName = "MedSnap"
$OutputDir = Split-Path -Parent $SourceDir
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$ZipFileName = "${ProjectName}_部署包_${Timestamp}.zip"
$ZipPath = Join-Path $OutputDir $ZipFileName

# 排除规则
$ExcludeDirs = @('__pycache__', '.git', 'venv', '.venv', 'node_modules', '.idea', '.vscode', 'env')
$ExcludeExts = @('.pyc', '.pyo', '.pyd')
$ExcludeFiles = @('.DS_Store', 'Thumbs.db', '.secret_key', 'nul', '打包部署.py', '打包部署.ps1')

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  MedSnap 打包工具 (PowerShell)" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  源目录: $SourceDir"
Write-Host "  输出文件: $ZipPath"
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# 创建临时目录用于组织文件
$TempDir = Join-Path $env:TEMP "MedSnap_pack_$Timestamp"
$TempProjectDir = Join-Path $TempDir $ProjectName

if (Test-Path $TempDir) { Remove-Item $TempDir -Recurse -Force }
New-Item -ItemType Directory -Path $TempProjectDir -Force | Out-Null

# 复制文件（排除不需要的）
$FileCount = 0
$TotalSize = 0

Get-ChildItem -Path $SourceDir -Recurse -File | ForEach-Object {
    $relativePath = $_.FullName.Substring($SourceDir.Length + 1)
    $skip = $false

    # 检查是否在排除目录中
    foreach ($dir in $ExcludeDirs) {
        if ($relativePath -like "$dir\*" -or $relativePath -like "*\$dir\*") {
            $skip = $true
            break
        }
    }

    # 检查扩展名
    if (-not $skip -and $_.Extension -in $ExcludeExts) {
        $skip = $true
    }

    # 检查文件名
    if (-not $skip -and $_.Name -in $ExcludeFiles) {
        $skip = $true
    }

    if (-not $skip) {
        $destPath = Join-Path $TempProjectDir $relativePath
        $destDir = Split-Path -Parent $destPath
        if (-not (Test-Path $destDir)) {
            New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        }
        Copy-Item $_.FullName -Destination $destPath
        $FileCount++
        $TotalSize += $_.Length
    }
}

# 压缩为 ZIP
Write-Host "  正在压缩..." -ForegroundColor Yellow
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path $TempProjectDir -DestinationPath $ZipPath -CompressionLevel Optimal

# 清理临时目录
Remove-Item $TempDir -Recurse -Force

# 输出结果
$ZipSize = (Get-Item $ZipPath).Length
Write-Host ""
Write-Host "  打包完成！" -ForegroundColor Green
Write-Host "  - 文件数量: $FileCount 个"
Write-Host ("  - 原始大小: {0:N1} MB" -f ($TotalSize / 1MB))
Write-Host ("  - 压缩后大小: {0:N1} MB" -f ($ZipSize / 1MB))
Write-Host "  - 输出位置: $ZipPath" -ForegroundColor Green
Write-Host ""
Write-Host "  将此 ZIP 文件拷贝给对方，解压后双击「安装并启动.bat」即可运行" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "按任意键退出..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
