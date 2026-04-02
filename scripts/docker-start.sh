#!/bin/bash
# Guild Scroll Docker Helper Script
# Makes it easy for users to start Docker Compose setup

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions
print_header() {
    echo -e "${BLUE}╔════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║  Guild Scroll - Docker Setup Helper        ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════╝${NC}"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}!${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

check_requirements() {
    print_info "Checking requirements..."
    
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed. Please install Docker first."
        echo "  Visit: https://docs.docker.com/get-docker/"
        exit 1
    fi
    print_success "Docker is installed ($(docker --version))"
    
    # Support both "docker compose" (v2 plugin) and legacy "docker-compose" binary
    if docker compose version &> /dev/null; then
        DOCKER_COMPOSE="docker compose"
    elif command -v docker-compose &> /dev/null; then
        DOCKER_COMPOSE="docker-compose"
    else
        print_error "Docker Compose is not installed. Please install Docker Compose."
        echo "  Visit: https://docs.docker.com/compose/install/"
        exit 1
    fi
    print_success "Docker Compose is available (${DOCKER_COMPOSE})"
    
    # Check Docker daemon
    if ! docker ps &> /dev/null; then
        print_error "Docker daemon is not running. Please start Docker first."
        exit 1
    fi
    print_success "Docker daemon is running"
}

show_menu() {
    echo ""
    echo "What would you like to do?"
    echo ""
    echo "  1) Start containers (build if needed)"
    echo "  2) Stop containers"
    echo "  3) Access Kali recorder shell"
    echo "  4) View Guild Scroll web UI"
    echo "  5) View container logs"
    echo "  6) Rebuild images (no cache)"
    echo "  7) Clean up everything"
    echo "  8) Exit"
    echo ""
    read -p "Choose an option (1-8): " choice
}

start_containers() {
    print_info "Building and starting containers..."
    cd "${PROJECT_ROOT}"
    
    if $DOCKER_COMPOSE up -d; then
        print_success "Containers started successfully!"
        echo ""
        echo "Next steps:"
        print_info "Open web UI: http://localhost:8080"
        print_info "Kali shell: $DOCKER_COMPOSE exec kali-recorder zsh"
        print_info "View logs: $DOCKER_COMPOSE logs -f"
    else
        print_error "Failed to start containers"
        exit 1
    fi
}

stop_containers() {
    print_info "Stopping containers..."
    cd "${PROJECT_ROOT}"
    
    if $DOCKER_COMPOSE down; then
        print_success "Containers stopped"
    else
        print_error "Failed to stop containers"
        exit 1
    fi
}

kali_shell() {
    print_info "Connecting to Kali recorder shell..."
    print_warning "Press Ctrl+D or type 'exit' to disconnect"
    echo ""
    
    cd "${PROJECT_ROOT}"
    
    # Check if container is running
    if ! $DOCKER_COMPOSE ps kali-recorder | grep -q "Up"; then
        print_error "Kali container is not running. Start it first with option 1."
        return 1
    fi
    
    $DOCKER_COMPOSE exec kali-recorder zsh
}

web_ui() {
    print_info "Opening Guild Scroll web UI..."
    print_info "URL: http://localhost:8080"
    
    # Check if container is running
    if ! $DOCKER_COMPOSE ps guild-scroll-app | grep -q "Up"; then
        print_error "Guild Scroll app is not running. Start it first with option 1."
        return 1
    fi
    
    # Try to open browser (varies by OS)
    if command -v xdg-open &> /dev/null; then
        xdg-open http://localhost:8080
    elif command -v open &> /dev/null; then
        open http://localhost:8080
    else
        print_warning "Could not automatically open browser."
        print_info "Visit: http://localhost:8080 manually"
    fi
}

view_logs() {
    print_info "Showing container logs (Ctrl+C to exit)..."
    echo ""
    cd "${PROJECT_ROOT}"
    $DOCKER_COMPOSE logs -f
}

rebuild_images() {
    print_warning "Rebuilding images from scratch (no cache)..."
    cd "${PROJECT_ROOT}"
    
    if $DOCKER_COMPOSE build --no-cache; then
        print_success "Images rebuilt successfully"
    else
        print_error "Failed to rebuild images"
        exit 1
    fi
}

cleanup() {
    print_warning "This will remove all containers and volumes!"
    read -p "Are you sure? (y/N): " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_info "Cleaning up..."
        cd "${PROJECT_ROOT}"
        $DOCKER_COMPOSE down -v
        print_success "Cleanup complete"
    else
        print_info "Cleanup cancelled"
    fi
}

# Main loop
main() {
    print_header
    check_requirements
    print_success "All requirements met!"
    echo ""
    
    while true; do
        show_menu
        
        case $choice in
            1) start_containers ;;
            2) stop_containers ;;
            3) kali_shell ;;
            4) web_ui ;;
            5) view_logs ;;
            6) rebuild_images ;;
            7) cleanup ;;
            8) 
                print_info "Exiting"
                exit 0
                ;;
            *)
                print_error "Invalid option"
                ;;
        esac
        
        read -p "Press Enter to continue..."
    done
}

# Run main
main "$@"
