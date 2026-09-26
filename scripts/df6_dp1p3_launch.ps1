# DP-1 P3 G1（MMT HFSS 仲裁）HFSS 侧分离进程发射器（#157/#242，y1 同款）
# 路径自锚定：仓库根=本脚本上级目录（可用 RFAUTO_REPO_ROOT 覆盖）。
$repo = if ($env:RFAUTO_REPO_ROOT) { $env:RFAUTO_REPO_ROOT } else { Split-Path -Parent $PSScriptRoot }
$py = Join-Path $repo ".venv\Scripts\python.exe"
$logDir = Join-Path $repo "runs\df6_dp1p3\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Start-Process -FilePath $py `
  -ArgumentList "-u", "scripts/df6_dp1p3_hfss_g1.py" `
  -WorkingDirectory $repo `
  -RedirectStandardOutput (Join-Path $logDir "p3_launch.log") `
  -RedirectStandardError (Join-Path $logDir "p3_launch.err.log") `
  -WindowStyle Hidden -PassThru | ForEach-Object { Write-Output "LAUNCHED_PID=$($_.Id)" }
