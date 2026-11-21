# Axon Trading - Web Server Setup & Launch Script for Windows PowerShell
# 
# Usage:
#   .\start-web.ps1                         # Start with default settings
#   .\start-web.ps1 -Port 8080              # Start on custom port
#   .\start-web.ps1 -Debug                  # Start in debug mode
#   .\start-web.ps1 -Host "127.0.0.1"       # Localhost only (secure)

param(
    [string]$Port = "5000",
    [string]$Host = "0.0.0.0",
    [switch]$Debug = $false,
    [switch]$Help = $false,
    [switch]$Install = $false,
    [switch]$Https = $false,
    [string]$CertFile = "",
    [string]$KeyFile = ""
)

$ErrorActionPreference = "Continue"

function Print-Banner {
    Write-Host ""
    Write-Host "╔═══════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║                                                               ║" -ForegroundColor Cyan
    Write-Host "║     📈 Axon Trading - Web Based Terminal 📈              ║" -ForegroundColor Cyan
    Write-Host "║                                                               ║" -ForegroundColor Cyan
    Write-Host "║              Real-time Trading & Order Management              ║" -ForegroundColor Cyan
    Write-Host "║                      v1.0 Web Edition                          ║" -ForegroundColor Cyan
    Write-Host "║                                                               ║" -ForegroundColor Cyan
    Write-Host "╚═══════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
}

function Print-Help {
    Write-Host ""
    Write-Host "╔═══════════════════════════════════════════════════════════════╗" -ForegroundColor Yellow
    Write-Host "║              AXON TRADING - WEB INTERFACE                 ║" -ForegroundColor Yellow
    Write-Host "╚═══════════════════════════════════════════════════════════════╝" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "USAGE:" -ForegroundColor Green
    Write-Host "  .\start-web.ps1 [OPTIONS]"
    Write-Host ""
    Write-Host "OPTIONS:" -ForegroundColor Green
    Write-Host "  -Port <PORT>        Port to listen on (default: 5000)"
    Write-Host "  -Host <HOST>        Host to bind to (default: 0.0.0.0)"
    Write-Host "  -Debug              Enable debug mode"
    Write-Host "  -Https              Enable HTTPS (TLS)" 
    Write-Host "  -CertFile <PATH>    TLS certificate file (PEM) for HTTPS" 
    Write-Host "  -KeyFile <PATH>     TLS private key file (PEM) for HTTPS" 
    Write-Host "  -Install            Install dependencies"
    Write-Host "  -Help               Show this help message"
    Write-Host ""
    Write-Host "EXAMPLES:" -ForegroundColor Green
    Write-Host "  # Start with default settings"
    Write-Host "  .\start-web.ps1"
    Write-Host ""
    Write-Host "  # Start on port 8080 with debug"
    Write-Host "  .\start-web.ps1 -Port 8080 -Debug"
    Write-Host ""
    Write-Host "  # Start with HTTPS using self-signed cert" 
    Write-Host "  .\start-web.ps1 -Https" 
    Write-Host "" 
    Write-Host "  # Start with HTTPS using your own cert and key" 
    Write-Host "  .\start-web.ps1 -Https -CertFile cert.pem -KeyFile key.pem" 
    Write-Host "" 
    Write-Host "  # Install dependencies then start"
    Write-Host "  .\start-web.ps1 -Install"
    Write-Host ""
    Write-Host "  # Localhost only (secure)"
    Write-Host "  .\start-web.ps1 -Host '127.0.0.1'"
    Write-Host ""
    Write-Host "ACCESS:" -ForegroundColor Green
    Write-Host "  http(s)://localhost:$Port          (if using -Host 127.0.0.1)"
    Write-Host "  http(s)://<your-machine-ip>:$Port  (if using -Host 0.0.0.0)"
    Write-Host ""
    Write-Host "FEATURES:" -ForegroundColor Green
    Write-Host "  ✓ Place mock and live trades"
    Write-Host "  ✓ Real-time order monitoring"
    Write-Host "  ✓ Position tracking"
    Write-Host "  ✓ Portfolio dashboard"
    Write-Host "  ✓ WebSocket real-time updates"
    Write-Host "  ✓ Market status indicator"
    Write-Host ""
}

function Test-Python {
    try {
        $version = python --version 2>&1
        Write-Host "✓ Python found: $version" -ForegroundColor Green
        return $true
    } catch {
        Write-Host "✗ Python not found in PATH" -ForegroundColor Red
        Write-Host "  Please install Python 3.8+ and add it to PATH" -ForegroundColor Yellow
        return $false
    }
}

function Test-Dependencies {
    Write-Host ""
    Write-Host "Checking dependencies..." -ForegroundColor Cyan
    
    $packages = @("flask", "flask_socketio", "socketio", "engineio", "eventlet")
    $missing = @()
    
    foreach ($package in $packages) {
        try {
            python -c "import $package" 2>&1 | Out-Null
            Write-Host "  ✓ $package" -ForegroundColor Green
        } catch {
            Write-Host "  ✗ $package (missing)" -ForegroundColor Red
            $missing += $package
        }
    }
    
    if ($missing.Count -gt 0) {
        Write-Host ""
        Write-Host "Missing dependencies detected!" -ForegroundColor Yellow
        Write-Host "Run with -Install flag to install: .\start-web.ps1 -Install" -ForegroundColor Yellow
        return $false
    }
    
    return $true
}

function Install-Dependencies {
    Write-Host ""
    Write-Host "Installing dependencies..." -ForegroundColor Cyan
    Write-Host ""
    
    # Check if requirements.txt exists
    if (Test-Path "requirements.txt") {
        Write-Host "Found requirements.txt, installing packages..." -ForegroundColor Green
        pip install -r requirements.txt
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host ""
            Write-Host "✓ Dependencies installed successfully!" -ForegroundColor Green
            return $true
        } else {
            Write-Host ""
            Write-Host "✗ Failed to install dependencies" -ForegroundColor Red
            return $false
        }
    } else {
        Write-Host "✗ requirements.txt not found" -ForegroundColor Red
        return $false
    }
}

function Start-WebServer {
    param(
        [string]$Port,
        [string]$Host,
        [bool]$Debug,
        [bool]$Https,
        [string]$CertFile,
        [string]$KeyFile
    )
    
    Write-Host ""
    Write-Host "Starting web server..." -ForegroundColor Cyan
    Write-Host ""
    
    $debugFlag = if ($Debug) { "--debug" } else { "" }
    $httpsFlag = if ($Https) { "--https" } else { "" }

    $certArg = ""
    $keyArg = ""
    if ($Https -and $CertFile -ne "" -and $KeyFile -ne "") {
        $certArg = "--certfile `"$CertFile`""
        $keyArg = "--keyfile `"$KeyFile`""
    }
    
    $scheme = if ($Https) { "https" } else { "http" }

    Write-Host "Configuration:" -ForegroundColor Yellow
    Write-Host "  Host: $Host" -ForegroundColor White
    Write-Host "  Port: $Port" -ForegroundColor White
    Write-Host "  Debug: $(if ($Debug) { 'Enabled' } else { 'Disabled' })" -ForegroundColor White
    Write-Host "  HTTPS: $(if ($Https) { 'Enabled' } else { 'Disabled' })" -ForegroundColor White
    Write-Host ""
    Write-Host "Access the interface at:" -ForegroundColor Green
    if ($Host -eq "0.0.0.0") {
        Write-Host "  • $scheme://localhost:$Port" -ForegroundColor Cyan
        Write-Host "  • $scheme://<your-machine-ip>:$Port" -ForegroundColor Cyan
    } else {
        Write-Host "  • $scheme://$Host`:$Port" -ForegroundColor Cyan
    }
    Write-Host ""
    Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Yellow
    Write-Host ("`" + "─" * 63) -ForegroundColor Gray
    Write-Host ""
    
    # Run the web server (uses currently active Python/venv)
    & python run_web.py --host $Host --port $Port $debugFlag $httpsFlag $certArg $keyArg
}

# Main script logic
Print-Banner

if ($Help) {
    Print-Help
    exit 0
}

# Check Python
if (-not (Test-Python)) {
    exit 1
}

# Check/Install dependencies
if ($Install) {
    if (-not (Install-Dependencies)) {
        exit 1
    }
} else {
    if (-not (Test-Dependencies)) {
        exit 1
    }
}

# Start the web server
Start-WebServer -Port $Port -Host $Host -Debug $Debug -Https $Https -CertFile $CertFile -KeyFile $KeyFile
