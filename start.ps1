# Builds the web UI if needed, then starts Field Assist at http://localhost:8000
# Ollama must be running (it starts with Windows after install).
$root = $PSScriptRoot

if (-not (Test-Path "$root\web\dist")) {
    Push-Location "$root\web"
    npm install
    npm run build
    Pop-Location
}

& "$root\.venv\Scripts\python.exe" -m uvicorn src.api:app --app-dir $root --port 8000
