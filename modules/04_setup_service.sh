#!/usr/bin/env bash

# Color definitions
COLOR_RED='\033[0;31m'
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[0;33m'
COLOR_BLUE='\033[0;34m'
COLOR_RESET='\033[0m'

# Set error handling
set -e

# Log functions
log_info() {
    echo -e "${COLOR_BLUE}[INFO]${COLOR_RESET} $1"
}

log_success() {
    echo -e "${COLOR_GREEN}[SUCCESS]${COLOR_RESET} $1"
}

log_warning() {
    echo -e "${COLOR_YELLOW}[WARNING]${COLOR_RESET} $1"
}

log_error() {
    echo -e "${COLOR_RED}[ERROR]${COLOR_RESET} $1"
}

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root"
    exit 1
fi

log_info "Setting up Neuro-Lite service"

# Get the path to the main server script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CORE_DIR="${PROJECT_ROOT}/core"
MAIN_SERVER="${CORE_DIR}/main_server.py"

# Verify main server script exists
if [ ! -f "$MAIN_SERVER" ]; then
    log_error "Main server script not found: $MAIN_SERVER"
    exit 1
fi

# Ensure the script is executable
chmod +x "$MAIN_SERVER"

# Create config.env if it doesn't exist
CONFIG_ENV="${PROJECT_ROOT}/config.env"
if [ ! -f "$CONFIG_ENV" ]; then
    log_info "Creating config.env file"
    cat > "$CONFIG_ENV" << EOF
# Neuro-Lite Configuration

# Server settings
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
LOG_LEVEL=INFO
MAX_CONNECTIONS=10

# Model settings
MODEL_PATH=/opt/neuro-lite/models/Qwen2.5-3B-Instruct-Q4_K_M.gguf
CONTEXT_LENGTH=4096
SYSTEM_PROMPT="You are a helpful AI assistant. You answer questions accurately, professionally, and with appropriate tone."

# Database settings
DB_PATH=/opt/neuro-lite/data/knowledge.db

# Security settings
ENABLE_AUTH=false
AUTH_TOKEN=

# Performance settings
THREADS=$(nproc --all)
BATCH_SIZE=512
EOF
    log_success "Created config.env file"
fi

# Copy project files to /opt/neuro-lite if not copying from there
APP_DIR="/opt/neuro-lite"

# Only copy files if we're not already in the target directory
if [[ "$PROJECT_ROOT" != "$APP_DIR" ]]; then
    log_info "Copying project files to $APP_DIR"
    
    # Create directories
    mkdir -p "${APP_DIR}/core"
    mkdir -p "${APP_DIR}/webui"
    
    # Copy core files
    cp -r "${CORE_DIR}"/* "${APP_DIR}/core/"
    cp -r "${PROJECT_ROOT}/webui"/* "${APP_DIR}/webui/"
    cp "$CONFIG_ENV" "${APP_DIR}/"
    
    log_success "Files copied to $APP_DIR"
fi

# Create systemd service file
SERVICE_FILE="/etc/systemd/system/neuro-lite.service"
log_info "Creating systemd service file: $SERVICE_FILE"

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Neuro-Lite AI Server
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/python ${APP_DIR}/core/main_server.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=neuro-lite
Environment="PYTHONUNBUFFERED=1"
# Set resource limits
LimitNOFILE=4096
# Set OOM score to avoid being killed too easily
OOMScoreAdjust=-100
# Shutdown grace period: 30s
TimeoutStopSec=30
# CPU and memory limits
CPUQuota=90%
MemoryMax=3G

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd daemon
log_info "Reloading systemd daemon"
systemctl daemon-reload

# Enable the service to start at boot
log_info "Enabling neuro-lite service"
systemctl enable neuro-lite.service

# Start the service
log_info "Starting neuro-lite service"
systemctl start neuro-lite.service || {
    log_error "Failed to start neuro-lite service"
    log_error "Check status with: systemctl status neuro-lite"
    exit 1
}

# Wait for service to start properly
log_info "Waiting for service to initialize..."
sleep 5

# Check service status
if systemctl is-active --quiet neuro-lite.service; then
    log_success "Neuro-Lite service is running"
else
    log_warning "Neuro-Lite service is not running. Check logs with: journalctl -u neuro-lite"
fi

# Create a convenience script for common operations
CONTROL_SCRIPT="/usr/local/bin/neuro-lite-ctl"
log_info "Creating control script: $CONTROL_SCRIPT"

cat > "$CONTROL_SCRIPT" << 'EOF'
#!/usr/bin/env bash

# Color definitions
COLOR_RED='\033[0;31m'
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[0;33m'
COLOR_BLUE='\033[0;34m'
COLOR_RESET='\033[0m'

# Log functions
log_info() {
    echo -e "${COLOR_BLUE}[INFO]${COLOR_RESET} $1"
}

log_success() {
    echo -e "${COLOR_GREEN}[SUCCESS]${COLOR_RESET} $1"
}

log_warning() {
    echo -e "${COLOR_YELLOW}[WARNING]${COLOR_RESET} $1"
}

log_error() {
    echo -e "${COLOR_RED}[ERROR]${COLOR_RESET} $1"
}

# Functions
show_status() {
    systemctl status neuro-lite
}

start_service() {
    log_info "Starting Neuro-Lite service"
    sudo systemctl start neuro-lite
    if [ $? -eq 0 ]; then
        log_success "Neuro-Lite service started"
    else
        log_error "Failed to start Neuro-Lite service"
    fi
}

stop_service() {
    log_info "Stopping Neuro-Lite service"
    sudo systemctl stop neuro-lite
    if [ $? -eq 0 ]; then
        log_success "Neuro-Lite service stopped"
    else
        log_error "Failed to stop Neuro-Lite service"
    fi
}

restart_service() {
    log_info "Restarting Neuro-Lite service"
    sudo systemctl restart neuro-lite
    if [ $? -eq 0 ]; then
        log_success "Neuro-Lite service restarted"
    else
        log_error "Failed to restart Neuro-Lite service"
    fi
}

show_logs() {
    sudo journalctl -u neuro-lite -f
}

edit_config() {
    sudo nano /opt/neuro-lite/config.env
    log_warning "Remember to restart the service for changes to take effect"
}

show_help() {
    echo -e "${COLOR_GREEN}Neuro-Lite Control Script${COLOR_RESET}"
    echo -e "Usage: neuro-lite-ctl COMMAND"
    echo -e ""
    echo -e "Commands:"
    echo -e "  status      Show service status"
    echo -e "  start       Start the service"
    echo -e "  stop        Stop the service"
    echo -e "  restart     Restart the service"
    echo -e "  logs        Show and follow service logs"
    echo -e "  config      Edit configuration file"
    echo -e "  help        Show this help message"
}

# Main script
if [ $# -eq 0 ]; then
    show_help
    exit 0
fi

case "$1" in
    status)
        show_status
        ;;
    start)
        start_service
        ;;
    stop)
        stop_service
        ;;
    restart)
        restart_service
        ;;
    logs)
        show_logs
        ;;
    config)
        edit_config
        ;;
    help)
        show_help
        ;;
    *)
        log_error "Unknown command: $1"
        show_help
        exit 1
        ;;
esac
EOF

# Make the control script executable
chmod +x "$CONTROL_SCRIPT"

log_success "Service setup completed successfully"
log_info "Access web interface at: http://localhost:8000"
log_info "Control the service with: neuro-lite-ctl [status|start|stop|restart|logs|config]"

exit 0
