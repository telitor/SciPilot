$ErrorActionPreference = "Stop"
$backendDir = Split-Path -Parent $PSScriptRoot
$candidates = @(
    (Join-Path $backendDir ".venv-scipilot\Scripts\python.exe"),
    (Join-Path $backendDir ".venv\Scripts\python.exe")
)

$python = $null
foreach ($candidate in $candidates) {
    if (-not (Test-Path $candidate)) { continue }
    & $candidate --version *> $null
    if ($LASTEXITCODE -eq 0) {
        $python = $candidate
        break
    }
    Write-Warning "Skipping unusable Python environment: $candidate"
}

if (-not $python) {
    throw "No usable SciPilot Python environment found. Run backend\scripts\setup_dev.ps1 first."
}

& $python -c "import fastapi, uvicorn, supabase, openai, pypdf, requests"
if ($LASTEXITCODE -ne 0) {
    throw "Python is available but backend dependencies are incomplete. Run backend\scripts\setup_dev.ps1."
}

Write-Host "[OK] Python: $python"
Write-Host "[OK] Backend imports are available"

$node = Get-Command node -ErrorAction SilentlyContinue
$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $node -or -not $npm) {
    $wingetRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    $nodeRoot = Get-ChildItem $wingetRoot -Directory -Filter "OpenJS.NodeJS.LTS*" -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
    if ($nodeRoot) {
        $node = Get-ChildItem $nodeRoot -Recurse -Filter "node.exe" -ErrorAction SilentlyContinue |
            Select-Object -First 1 -ExpandProperty FullName
        $npm = Get-ChildItem $nodeRoot -Recurse -Filter "npm.cmd" -ErrorAction SilentlyContinue |
            Select-Object -First 1 -ExpandProperty FullName
    }
}
if (-not $node -or -not $npm) {
    throw "Node.js 20+ and npm are required. Install Node.js LTS and open a new PowerShell window."
}

$nodePath = if ($node -is [System.Management.Automation.CommandInfo]) { $node.Source } else { $node }
$npmPath = if ($npm -is [System.Management.Automation.CommandInfo]) { $npm.Source } else { $npm }
$nodeVersion = & $nodePath --version
$nodeMajor = [int](($nodeVersion -replace '^v', '').Split('.')[0])
if ($LASTEXITCODE -ne 0 -or $nodeMajor -lt 20) {
    throw "Node.js 20 or newer is required. Found: $nodeVersion"
}
& $npmPath --version *> $null
if ($LASTEXITCODE -ne 0) { throw "npm is not usable." }

$frontendModules = Join-Path (Split-Path $backendDir -Parent) "frontend\node_modules"
if (-not (Test-Path $frontendModules)) {
    throw "frontend\node_modules is missing. Run npm install in frontend."
}
Write-Host "[OK] Node: $nodeVersion"
Write-Host "[OK] npm and frontend dependencies are available"
