$root = Split-Path -Parent $PSScriptRoot
$destDir = Join-Path $root "dist"
$dest = Join-Path $destDir "router.zip"
New-Item -ItemType Directory -Force -Path $destDir | Out-Null
if (Test-Path $dest) { Remove-Item $dest }
Compress-Archive -Path (Join-Path $root "src\router.py") -DestinationPath $dest
Write-Output $dest
