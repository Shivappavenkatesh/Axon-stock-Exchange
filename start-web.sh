#!/bin/bash

# Axon Trading - Web Server Setup & Launch Script for Linux/Mac
# 
# Usage:
#   ./start-web.sh                          # Start with default settings
#   ./start-web.sh --port 8080              # Start on custom port
#   ./start-web.sh --debug                  # Start in debug mode
#   ./start-web.sh --host 127.0.0.1         # Localhost only (secure)
#   ./start-web.sh --install               # Install dependencies

# Configuration
PORT=${PORT:-5000}
HOST=${HOST:-0.0.0.0}
DEBUG=false
INSTALL=false
HELP=false

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
NC='\033[0m' # No Color

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --port)
            PORT="$2"
            shift 2
            ;;
        --host)
            HOST="$2"
            shift 2
            ;;
        --debug)
            DEBUG=true
            shift
            ;;
        --install)
            INSTALL=true
            shift
            ;;
        --help|-h)
            HELP=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            HELP=true
            shift
            ;;
    esac
done

print_banner() {
    echo ""
    echo -e "${CYAN}╔═══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║                                                               ║${NC}"
    echo -e "${CYAN}║     📈 Axon Trading - Web Based Terminal 📈              ║${NC}"
    echo -e "${CYAN}║                                                               ║${NC}"
    echo -e "${CYAN}║              Real-time Trading & Order Management              ║${NC}"
    echo -e "${CYAN}║                      v1.0 Web Edition                          ║${NC}"
    echo -e "${CYAN}║                                                               ║${NC}"
    echo -e "${CYAN}╚═══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

print_help() {
    echo ""
    echo -e "${YELLOW}╔═══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}║              AXON TRADING - WEB INTERFACE                 ║${NC}"
    echo -e "${YELLOW}╚═══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${GREEN}USAGE:${NC}"
    echo "  ./start-web.sh [OPTIONS]"
    echo ""
    echo -e "${GREEN}OPTIONS:${NC}"
    echo "  --port PORT         Port to listen on (default: 5000)"
    echo "  --host HOST         Host to bind to (default: 0.0.0.0)"
    echo "  --debug             Enable debug mode"
    echo "  --install           Install dependencies"
    echo "  --help, -h          Show this help message"
    echo ""
    echo -e "${GREEN}EXAMPLES:${NC}"
    echo "  # Start with default settings"
    echo "  ./start-web.sh"
    echo ""
    echo "  # Start on port 8080 with debug"
    echo "  ./start-web.sh --port 8080 --debug"
    echo ""
    echo "  # Install dependencies then start"
    echo "  ./start-web.sh --install"
    echo ""
    echo "  # Localhost only (secure)"
    echo "  ./start-web.sh --host 127.0.0.1"
    echo ""
    echo -e "${GREEN}ACCESS:${NC}"
    echo "  http://localhost:$PORT          (if using --host 127.0.0.1)"
    echo "  http://<your-machine-ip>:$PORT  (if using --host 0.0.0.0)"
    echo ""
    echo -e "${GREEN}FEATURES:${NC}"
    echo "  ✓ Place mock and live trades"
    echo "  ✓ Real-time order monitoring"
    echo "  ✓ Position tracking"
    echo "  ✓ Portfolio dashboard"
    echo "  ✓ WebSocket real-time updates"
    echo "  ✓ Market status indicator"
    echo ""
}

test_python() {
    if command -v python3 &> /dev/null; then
        VERSION=$(python3 --version 2>&1)
        echo -e "${GREEN}✓ Python found: $VERSION${NC}"
        return 0
    elif command -v python &> /dev/null; then
        VERSION=$(python --version 2>&1)
        echo -e "${GREEN}✓ Python found: $VERSION${NC}"
        return 0
    else
        echo -e "${RED}✗ Python not found in PATH${NC}"
        echo -e "${YELLOW}  Please install Python 3.8+ and add it to PATH${NC}"
        return 1
    fi
}

test_dependencies() {
    echo ""
    echo -e "${CYAN}Checking dependencies...${NC}"
    
    local packages=("flask" "flask_socketio" "socketio" "engineio" "eventlet")
    local missing=()
    
    local python_cmd="python3"
    if ! command -v python3 &> /dev/null; then
        python_cmd="python"
    fi
    
    for package in "${packages[@]}"; do
        if $python_cmd -c "import $package" 2>/dev/null; then
            echo -e "  ${GREEN}✓ $package${NC}"
        else
            echo -e "  ${RED}✗ $package (missing)${NC}"
            missing+=("$package")
        fi
    done
    
    if [ ${#missing[@]} -gt 0 ]; then
        echo ""
        echo -e "${YELLOW}Missing dependencies detected!${NC}"
        echo -e "${YELLOW}Run with --install flag to install: ./start-web.sh --install${NC}"
        return 1
    fi
    
    return 0
}

install_dependencies() {
    echo ""
    echo -e "${CYAN}Installing dependencies...${NC}"
    echo ""
    
    if [ -f "requirements.txt" ]; then
        echo -e "${GREEN}Found requirements.txt, installing packages...${NC}"
        
        local pip_cmd="pip3"
        if ! command -v pip3 &> /dev/null; then
            pip_cmd="pip"
        fi
        
        $pip_cmd install -r requirements.txt
        
        if [ $? -eq 0 ]; then
            echo ""
            echo -e "${GREEN}✓ Dependencies installed successfully!${NC}"
            return 0
        else
            echo ""
            echo -e "${RED}✗ Failed to install dependencies${NC}"
            return 1
        fi
    else
        echo -e "${RED}✗ requirements.txt not found${NC}"
        return 1
    fi
}

start_web_server() {
    echo ""
    echo -e "${CYAN}Starting web server...${NC}"
    echo ""
    
    local debug_flag=""
    if [ "$DEBUG" = true ]; then
        debug_flag="--debug"
    fi
    
    echo -e "${YELLOW}Configuration:${NC}"
    echo -e "  Host: $HOST"
    echo -e "  Port: $PORT"
    if [ "$DEBUG" = true ]; then
        echo -e "  Debug: Enabled"
    else
        echo -e "  Debug: Disabled"
    fi
    echo ""
    echo -e "${GREEN}Access the interface at:${NC}"
    if [ "$HOST" = "0.0.0.0" ]; then
        echo -e "  ${CYAN}• http://localhost:$PORT${NC}"
        echo -e "  ${CYAN}• http://<your-machine-ip>:$PORT${NC}"
    else
        echo -e "  ${CYAN}• http://$HOST:$PORT${NC}"
    fi
    echo ""
    echo -e "${YELLOW}Press Ctrl+C to stop the server${NC}"
    echo -e "${GRAY}$(printf '─%.0s' {1..65})${NC}"
    echo ""
    
    local python_cmd="python3"
    if ! command -v python3 &> /dev/null; then
        python_cmd="python"
    fi
    
    $python_cmd run_web.py --host "$HOST" --port "$PORT" $debug_flag
}

# Main script logic
print_banner

if [ "$HELP" = true ]; then
    print_help
    exit 0
fi

# Check Python
if ! test_python; then
    exit 1
fi

# Check/Install dependencies
if [ "$INSTALL" = true ]; then
    if ! install_dependencies; then
        exit 1
    fi
else
    if ! test_dependencies; then
        exit 1
    fi
fi

# Start the web server
start_web_server
