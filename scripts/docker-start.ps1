# Guild Scroll Docker Helper Script (Windows)
# Makes it easy for users to start Docker setup on Windows

$ErrorActionPreference = "Stop"

# Colors
$colors = @{
    'Red'    = [System.ConsoleColor]::Red
    'Green'  = [System.ConsoleColor]::Green
    'Yellow' = [System.ConsoleColor]::Yellow
    'Blue'   = [System.ConsoleColor]::Blue
    'White'  = [System.ConsoleColor]::White
}

# Get script and project directories
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$projectRoot = Split-Path -Parent $scriptDir

# Output functions
function Write-Header {
    Write-Host ""
    Write-Host "╔════════════════════════════════════════════╗" -ForegroundColor $colors['Blue']
    Write-Host "║  Guild Scroll - Docker Setup Helper (Win)  ║" -ForegroundColor $colors['Blue']
    Write-Host "╚════════════════════════════════════════════╝" -ForegroundColor $colors['Blue']
    Write-Host ""
}

function Write-Success {
    Write-Host "✓ $args" -ForegroundColor $colors['Green']
}

function Write-Error-Custom {
    Write-Host "✗ $args" -ForegroundColor $colors['Red']
}

function Write-Warning-Custom {
    Write-Host "! $args" -ForegroundColor $colors['Yellow']
}

function Write-Info {
    Write-Host "ℹ $args" -ForegroundColor $colors['Blue']
}

function Check-Requirements {
    Write-Info "Checking requirements..."
    
    # Check Docker
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
        Write-Error-Custom "Docker is not installed."
        Write-Host "  Download: https://www.docker.com/products/docker-desktop"
        exit 1
    }
    $dockerVersion = docker --version
    Write-Success "Docker is installed ($dockerVersion)"
    
    # Check Docker Compose
    $compose = Get-Command docker-compose -ErrorAction SilentlyContinue
    if (-not $compose) {
        Write-Error-Custom "Docker Compose is not installed."
        Write-Host "  It should come with Docker Desktop for Windows"
        exit 1
    }
    $composeVersion = docker-compose --version
    Write-Success "Docker Compose is installed ($composeVersion)"
    
    # Check if Docker daemon is running
    try {
        docker ps | Out-Null
        Write-Success "Docker daemon is running"
    } catch {
        Write-Error-Custom "Docker daemon is not running. Start Docker Desktop first."
        exit 1
    }
}

function Show-Menu {
    Write-Host ""
    Write-Host "What would you like to do?" -ForegroundColor $colors['White']
    Write-Host ""
    Write-Host "  1) Start containers (build if needed)"
    Write-Host "  2) Stop containers"
    Write-Host "  3) Access Kali recorder shell"
    Write-Host "  4) View Guild Scroll web UI"
    Write-Host "  5) View container logs"
    Write-Host "  6) Rebuild images (no cache)"
    Write-Host "  7) Clean up everything"
    Write-Host "  8) Exit"
    Write-Host ""
    $choice = Read-Host "Choose an option (1-8)"
    return $choice
}

function Start-Containers {
    Write-Info "Building and starting containers..."
    Set-Location $projectRoot
    
    Try {
        docker-compose up -d
        Write-Success "Containers started successfully!"
        Write-Host ""
        Write-Host "Next steps:" -ForegroundColor $colors['White']
        Write-Info "Open web UI: http://localhost:8080"
        Write-Info "Kali shell: docker-compose exec kali-recorder zsh"
        Write-Info "View logs: docker-compose logs -f"
    } Catch {
        Write-Error-Custom "Failed to start containers"
        Write-Host $_.Exception.Message
        exit 1
    }
}

function Stop-Containers {
    Write-Info "Stopping containers..."
    Set-Location $projectRoot
    
    Try {
        docker-compose down
        Write-Success "Containers stopped"
    } Catch {
        Write-Error-Custom "Failed to stop containers"
        exit 1
    }
}

function Kali-Shell {
    Write-Info "Connecting to Kali recorder shell..."
    Write-Warning-Custom "Press Ctrl+C or type 'exit' to disconnect"
    Write-Host ""
    
    Set-Location $projectRoot
    
    # Check if container is running
    $running = docker-compose ps kali-recorder | Select-String "Up"
    if (-not $running) {
        Write-Error-Custom "Kali container is not running. Start it first with option 1."
        return
    }
    
    docker-compose exec kali-recorder zsh
}

function Web-UI {
    Write-Info "Opening Guild Scroll web UI..."
    Write-Info "URL: http://localhost:8080"
    
    Set-Location $projectRoot
    
    # Check if container is running
    $running = docker-compose ps guild-scroll-app | Select-String "Up"
    if (-not $running) {
        Write-Error-Custom "Guild Scroll app is not running. Start it first with option 1."
        return
    }
    
    # Open browser
    Try {
        Start-Process "http://localhost:8080"
        Write-Success "Opening browser..."
    } Catch {
        Write-Warning-Custom "Could not automatically open browser."
        Write-Info "Visit: http://localhost:8080 manually"
    }
}

function View-Logs {
    Write-Info "Showing container logs (Ctrl+C to exit)..."
    Write-Host ""
    Set-Location $projectRoot
    docker-compose logs -f
}

function Rebuild-Images {
    Write-Warning-Custom "Rebuilding images from scratch (no cache)..."
    Set-Location $projectRoot
    
    Try {
        docker-compose build --no-cache
        Write-Success "Images rebuilt successfully"
    } Catch {
        Write-Error-Custom "Failed to rebuild images"
        exit 1
    }
}

function Cleanup {
    Write-Warning-Custom "This will remove all containers and volumes!"
    $confirm = Read-Host "Are you sure? (yes/no)"
    
    if ($confirm -eq "yes") {
        Write-Info "Cleaning up..."
        Set-Location $projectRoot
        docker-compose down -v
        Write-Success "Cleanup complete"
    } else {
        Write-Info "Cleanup cancelled"
    }
}

# Main loop
function Main {
    Write-Header
    Check-Requirements
    Write-Success "All requirements met!"
    
    while ($true) {
        $choice = Show-Menu
        
        switch ($choice) {
            "1" { Start-Containers }
            "2" { Stop-Containers }
            "3" { Kali-Shell }
            "4" { Web-UI }
            "5" { View-Logs }
            "6" { Rebuild-Images }
            "7" { Cleanup }
            "8" { 
                Write-Info "Exiting"
                exit 0
            }
            default {
                Write-Error-Custom "Invalid option"
            }
        }
        
        Read-Host "Press Enter to continue"
    }
}

# Run main
Main
