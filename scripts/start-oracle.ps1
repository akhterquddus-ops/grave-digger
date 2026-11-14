# Start the local Oracle and wait until it accepts connections.
docker compose up -d
Write-Host "Waiting for Oracle..." -NoNewline
while ((docker inspect -f "{{.State.Health.Status}}" gd-oracle) -ne "healthy") { Start-Sleep 3; Write-Host "." -NoNewline }
Write-Host " healthy"