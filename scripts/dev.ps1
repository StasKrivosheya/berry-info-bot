param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("install", "run", "lint", "format", "test", "docker-up", "docker-down")]
    [string]$Task
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Resolve-CommandPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $venvPath = Join-Path $RepoRoot ".venv\Scripts\$Name"
    if (Test-Path $venvPath) {
        return $venvPath
    }
    return $Name
}

# Prefer repository-local virtualenv tools when available to keep behavior predictable.
$Python = Resolve-CommandPath -Name "python.exe"
$Ruff = Resolve-CommandPath -Name "ruff.exe"
$Pytest = Resolve-CommandPath -Name "pytest.exe"
$Docker = Resolve-CommandPath -Name "docker.exe"

switch ($Task) {
    "install" {
        & $Python -m pip install --upgrade pip
        & $Python -m pip install -e ".[dev]"
    }
    "run" {
        & $Python -m app.main
    }
    "lint" {
        & $Ruff check src tests
    }
    "format" {
        & $Ruff format src tests
    }
    "test" {
        & $Pytest -q
    }
    "docker-up" {
        $dockerEnv = Join-Path $RepoRoot ".env"
        if (-not (Test-Path $dockerEnv)) {
            throw ".env is missing. Create it from .env.example before running docker tasks."
        }
        & $Docker compose up --build
    }
    "docker-down" {
        & $Docker compose down
    }
}
