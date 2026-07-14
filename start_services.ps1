$env:PYTHONPATH = "C:\Users\rohit\Documents\msrit_chatbot\services"
$base = "C:\Users\rohit\Documents\msrit_chatbot\services"

Write-Host "Starting retrieval-service on :8001..." -ForegroundColor Green
$j1 = Start-Job -Name retrieval -ScriptBlock {
    param($d, $p) $env:PYTHONPATH = $p; Set-Location $d
    python -m uvicorn main:app --host 0.0.0.0 --port 8001 --log-level warning
} -ArgumentList "$base\retrieval-service", $env:PYTHONPATH

Write-Host "Starting session-service on :8003..." -ForegroundColor Green
$j2 = Start-Job -Name session -ScriptBlock {
    param($d, $p) $env:PYTHONPATH = $p; Set-Location $d
    python -m uvicorn main:app --host 0.0.0.0 --port 8003 --log-level warning
} -ArgumentList "$base\session-service", $env:PYTHONPATH

Write-Host "Starting llm-service on :8002..." -ForegroundColor Green
$j3 = Start-Job -Name llm -ScriptBlock {
    param($d, $p) $env:PYTHONPATH = $p; Set-Location $d
    python -m uvicorn main:app --host 0.0.0.0 --port 8002 --log-level warning
} -ArgumentList "$base\llm-service", $env:PYTHONPATH

Write-Host "Waiting 40s for retrieval (embeddings model load)..." -ForegroundColor Yellow
Start-Sleep -Seconds 40

Write-Host "Starting chat-orchestrator on :8000..." -ForegroundColor Green
$j4 = Start-Job -Name orchestrator -ScriptBlock {
    param($d, $p) $env:PYTHONPATH = $p; Set-Location $d
    python -m uvicorn main:app --host 0.0.0.0 --port 8000 --log-level warning
} -ArgumentList "$base\chat-orchestrator", $env:PYTHONPATH

Start-Sleep -Seconds 10

Write-Host "`nHealth checks:" -ForegroundColor Cyan
try { $h = Invoke-RestMethod http://localhost:8001/health -EA Stop; Write-Host "  retrieval: $($h.document_count) docs" -ForegroundColor Green } catch { Write-Host "  retrieval: FAILED" -ForegroundColor Red }
try { Invoke-RestMethod http://localhost:8002/health -EA Stop | Out-Null; Write-Host "  llm: OK" -ForegroundColor Green } catch { Write-Host "  llm: FAILED" -ForegroundColor Red }
try { Invoke-RestMethod http://localhost:8003/health -EA Stop | Out-Null; Write-Host "  session: OK" -ForegroundColor Green } catch { Write-Host "  session: FAILED" -ForegroundColor Red }
try { Invoke-RestMethod http://localhost:8000/health -EA Stop | Out-Null; Write-Host "  orchestrator: OK" -ForegroundColor Green } catch { Write-Host "  orchestrator: FAILED" -ForegroundColor Red }

Write-Host "`nDone. Run 'Get-Job | Receive-Job' to debug failures." -ForegroundColor Cyan
