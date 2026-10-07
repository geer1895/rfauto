# DF6 HFSS 轨件 2（Y1 半模型对拍）分离进程发射器（#157/#242）
Start-Process -FilePath "D:/rf_workspace\.venv\Scripts\python.exe" `
  -ArgumentList "-u", "scripts/df6_y1_hfss_arbitration.py" `
  -WorkingDirectory "D:/rf_workspace" `
  -RedirectStandardOutput "D:/rf_workspace\runs\df6_hfss_track\logs\y1_launch.log" `
  -RedirectStandardError "D:/rf_workspace\runs\df6_hfss_track\logs\y1_launch.err.log" `
  -WindowStyle Hidden -PassThru | ForEach-Object { Write-Output "LAUNCHED_PID=$($_.Id)" }
