param(
  [string]$BaseUrl = "http://localhost:8080",
  [string]$ApiKey = "gf_local_demo_key"
)

Write-Host "Health"
Invoke-RestMethod "$BaseUrl/health"
Write-Host "Proxy request"
Invoke-RestMethod "$BaseUrl/gateway/products" -Headers @{ "X-API-Key" = $ApiKey }
Write-Host "Rate-limit demonstration"
1..8 | ForEach-Object {
  try {
    $response = Invoke-WebRequest "$BaseUrl/gateway/products" -Headers @{ "X-API-Key" = $ApiKey }
    Write-Host "$($_): $($response.StatusCode) remaining=$($response.Headers['X-RateLimit-Remaining'])"
  } catch {
    Write-Host "$($_): $($_.Exception.Response.StatusCode.value__)"
  }
}
