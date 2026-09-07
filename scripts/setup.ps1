param(
    [string]$Python = "python",
    [string]$IndexUrl = "https://pypi.tuna.tsinghua.edu.cn/simple"
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
        & $Python -X utf8 -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "Cannot create .venv. Install Python 3.12 and retry." }
    }
    & .\.venv\Scripts\python.exe -X utf8 -m pip install -r requirements.txt -i $IndexUrl
    if ($LASTEXITCODE -ne 0 -and $IndexUrl -eq "https://pypi.tuna.tsinghua.edu.cn/simple") {
        Write-Host "Retrying with Aliyun mirror..."
        & .\.venv\Scripts\python.exe -X utf8 -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
    }
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed. Check your network/proxy." }
    & .\.venv\Scripts\python.exe -X utf8 -m pip check
    if ($LASTEXITCODE -ne 0) { throw "Dependency check failed." }
    Write-Host "Ready. Run start-web.cmd, then open http://127.0.0.1:8000"
}
finally { Pop-Location }
