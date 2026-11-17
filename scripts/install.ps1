# One-click setup, started by setup.bat. Installs Python 3.13 for this user when no Python 3.11+
# is found, runs `tasks.py install` (.venv + desktop / Start menu icons) and starts the IDE.
# Messages are Korean: this window is what end users see. Saved as UTF-8 with BOM so that
# Windows PowerShell 5.1 reads the Korean text correctly.

$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$Host.UI.RawUI.WindowTitle = 'SV-Guard 설치'

function Stop-WithError([string]$message) {
    Write-Host ''
    Write-Host $message -ForegroundColor Red
    Read-Host 'Enter 키를 누르면 창이 닫힙니다'
    exit 1
}

# The py launcher picks the newest 3.x. A bare "python" may be the Microsoft Store stub, which
# fails the version test below. The last entry is where winget puts a per-user Python 3.13: the
# PATH of this window does not change after installing it.
$candidates = @(
    @{ Exe = 'py'; Args = @('-3') },
    @{ Exe = 'python'; Args = @() },
    @{ Exe = "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"; Args = @() }
)

function Find-Python {
    foreach ($c in $candidates) {
        $a = $c.Args
        try {
            & $c.Exe @a -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return $c }
        } catch { }
    }
    return $null
}

Write-Host '[1/2] Python 확인' -ForegroundColor Cyan
$python = Find-Python
if (-not $python) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Start-Process 'https://www.python.org/downloads/'
        Stop-WithError ("Python을 자동으로 설치할 수 없습니다 (winget 없음).`n" +
            "열린 웹페이지에서 Python을 설치하고(첫 화면의 'Add python.exe to PATH' 체크), setup.bat을 다시 실행하세요.")
    }
    Write-Host 'Python 3.13을 설치합니다. 1~2분 걸립니다.'
    winget install --exact --id Python.Python.3.13 --source winget --scope user --silent `
        --accept-package-agreements --accept-source-agreements
    $python = Find-Python
    if (-not $python) {
        Stop-WithError 'Python을 설치하지 못했습니다. 인터넷 연결을 확인하고 setup.bat을 다시 실행하세요.'
    }
}

Write-Host ''
Write-Host '[2/2] SV-Guard 설치. 처음에는 몇 분 걸릴 수 있습니다.' -ForegroundColor Cyan
$a = $python.Args
& $python.Exe @a tasks.py install
if ($LASTEXITCODE -ne 0) {
    Stop-WithError '설치하지 못했습니다. 위의 메시지를 확인하세요. 인터넷 연결을 확인한 뒤 setup.bat을 다시 실행해 보세요.'
}

Start-Process -FilePath "$root\.venv\Scripts\svguard-ide.exe"
Write-Host ''
Write-Host '설치 완료! 다음부터는 바탕화면의 SV-Guard 아이콘으로 실행하세요.' -ForegroundColor Green
Write-Host "SV-Guard는 이 폴더에서 실행되므로 지우거나 옮기지 마세요: $root" -ForegroundColor Yellow
Start-Sleep -Seconds 8
