# DP-1 P3 G1（MMT HFSS 仲裁）HFSS 侧分离进程发射器（#157/#242，y1 同款）
Start-Process -FilePath "D:/rf_workspace\.venv\Scripts\python.exe" `
  -ArgumentList "-u", "scripts/df6_dp1p3_hfss_g1.py" `
  -WorkingDirectory "D:/rf_workspace" `
  -RedirectStandardOutput "D:/rf_workspace\runs\df6_dp1p3\logs\p3_launch.log" `
  -RedirectStandardError "D:/rf_workspace\runs\df6_dp1p3\logs\p3_launch.err.log" `
  -WindowStyle Hidden -PassThru | ForEach-Object { Write-Output "LAUNCHED_PID=$($_.Id)" }
