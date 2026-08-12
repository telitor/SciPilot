param(
    [string]$Python = "py -3.11",
    [string]$VenvName = ".venv-scipilot"
)

$ErrorActionPreference = "Stop"
$backendDir = Split-Path -Parent $PSScriptRoot
$venvDir = Join-Path $backendDir $VenvName
$venvPython = Join-Path $venvDir "Scripts\python.exe"

function Invoke-PythonCommand {
    param([string[]]$Arguments)
    $parts = $Python -split "\s+"
    $prefixArguments = if ($parts.Length -gt 1) { $parts[1..($parts.Length - 1)] } else { @() }
    & $parts[0] @prefixArguments @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE"
    }
}

if (-not (Test-Path $venvPython)) {
    Write-Host "[SciPilot] Creating isolated Python environment: $VenvName"
    Invoke-PythonCommand -Arguments @("-m", "venv", $venvDir)
}

& $venvPython --version
if ($LASTEXITCODE -ne 0) {
    throw "The environment at $venvDir is not usable. Choose another -VenvName."
}

Write-Host "[SciPilot] Installing backend dependencies..."
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $backendDir "requirements-dev.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed."
}

Write-Host "[SciPilot] Verifying imports..."
& $venvPython -c "import fastapi, uvicorn, supabase, openai, pypdf, requests"
if ($LASTEXITCODE -ne 0) {
    throw "Backend dependency verification failed."
}

Write-Host "[SciPilot] Backend environment is ready: $venvPython"
