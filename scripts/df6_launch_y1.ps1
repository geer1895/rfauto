# HFSS 轨件 2（Y1 半模型对拍）分离进程发射器（#157/#242，c4 同款）
# 路径自锚定：仓库根=本脚本上级目录（可用 RFAUTO_REPO_ROOT 覆盖）。
$repo = if ($env:RFAUTO_REPO_ROOT) { $env:RFAUTO_REPO_ROOT } else { Split-Path -Parent $PSScriptRoot }
$py = Join-Path $repo ".venv\Scripts\python.exe"
$logDir = Join-Path $repo "runs\df6_hfss_track\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Start-Process -FilePath $py `
  -ArgumentList "-u", "scripts/df6_y1_hfss_arbitration.py" `
  -WorkingDirectory $repo `
  -RedirectStandardOutput (Join-Path $logDir "y1_launch.log") `
  -RedirectStandardError (Join-Path $logDir "y1_launch.err.log") `
  -WindowStyle Hidden -PassThru | ForEach-Object { Write-Output "LAUNCHED_PID=$($_.Id)" }
