# DF6 HFSS 轨件 1（C4 端口门真机例）分离进程发射器（#157/#242）
Start-Process -FilePath "D:/rf_workspace\.venv\Scripts\python.exe" `
  -ArgumentList "-u", "scripts/df6_c4_port_gate_hfss.py" `
  -WorkingDirectory "D:/rf_workspace" `
  -RedirectStandardOutput "D:/rf_workspace\runs\df6_hfss_track\logs\c4_launch.log" `
  -RedirectStandardError "D:/rf_workspace\runs\df6_hfss_track\logs\c4_launch.err.log" `
  -WindowStyle Hidden -PassThru | ForEach-Object { Write-Output "LAUNCHED_PID=$($_.Id)" }
