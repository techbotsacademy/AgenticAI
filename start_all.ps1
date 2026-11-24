
$ErrorActionPreference = "Stop"

$root = "D:\ollama\AgenticAI-PersonA-push"
$web = "$root\Person_B\PrescriptionOCR"
$ollama = "C:\Users\Dell\AppData\Local\Programs\Ollama\ollama.exe"
$modelPath = "C:\Users\Dell\.ollama\models"

function Test-Port($port) {
    return (Test-NetConnection 127.0.0.1 -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue)
}

function Start-Terminal($command, $folder) {
    Start-Process powershell.exe -WorkingDirectory $folder -ArgumentList @(
        "-NoExit",
        "-Command",
        $command
    )
}

Write-Host "=================================="
Write-Host "       AGENTICAI STARTUP"
Write-Host "=================================="

# 1. Start Ollama
$env:OLLAMA_MODELS = $modelPath

if (!(Test-Port 11434)) {
    Write-Host "Starting Ollama..."
    Start-Terminal "`$env:OLLAMA_MODELS='$modelPath'; & '$ollama' serve" $root

    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep 2
        if (Test-Port 11434) {
            $ready = $true
            break
        }
    }

    if (!$ready) {
        throw "Ollama did not start. Check its terminal."
    }
}

# 2. Verify Qwen model
$tags = Invoke-RestMethod "http://127.0.0.1:11434/api/tags"

if ($tags.models.name -notcontains "qwen2.5-coder:7b") {
    throw "Required Qwen model is missing."
}

Write-Host "Ollama ready."

# 3. Start n8n
if (!(Test-Port 5678)) {
    Write-Host "Starting n8n..."
    Start-Terminal "n8n start" $root
} else {
    Write-Host "n8n already running."
}

# 4. Start Flask
if (!(Test-Port 5000)) {
    Write-Host "Starting Flask..."
    Start-Terminal "& '$root\.venv\Scripts\python.exe' '$root\app.py'" $root
} else {
    Write-Host "Flask already running."
}

# 5. Start webpage server
if (!(Test-Port 8000)) {
    Write-Host "Starting webpage server..."
    Start-Terminal "py -m http.server 8000" $web
} else {
    Write-Host "Webpage server already running."
}

Start-Sleep -Seconds 5
Start-Process "http://localhost:8000/basicocr.html"

Write-Host ""
Write-Host "AGENTICAI STARTED SUCCESSFULLY"
