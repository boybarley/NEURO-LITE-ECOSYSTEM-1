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

# Script variables
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULES_DIR="${SCRIPT_DIR}/modules"
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")
LOG_FILE="${SCRIPT_DIR}/install_$(date +"%Y%m%d%H%M%S").log"

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS_NAME=$NAME
    OS_VERSION=$VERSION_ID
else
    log_error "Cannot detect operating system"
    exit 1
fi

# Check if running on Ubuntu 22.04
if [[ "$OS_NAME" != *"Ubuntu"* ]] || [[ "$OS_VERSION" != "22.04" ]]; then
    log_warning "Neuro-Lite is designed for Ubuntu 22.04 LTS."
    log_warning "Current OS: $OS_NAME $OS_VERSION"
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_error "Installation aborted."
        exit 1
    fi
fi

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root"
    log_error "Please run: sudo $0"
    exit 1
fi

# Setup logging
exec > >(tee -a "$LOG_FILE") 2>&1
log_info "Starting Neuro-Lite installation at $TIMESTAMP"
log_info "Logging to $LOG_FILE"

# Check if required modules exist
required_modules=(
    "01_os_tuning.sh"
    "02_install_deps.sh"
    "03_download_model.sh"
    "04_setup_service.sh"
)

for module in "${required_modules[@]}"; do
    if [[ ! -f "${MODULES_DIR}/${module}" ]]; then
        log_error "Required module not found: ${module}"
        exit 1
    fi
    
    # Check if module is executable
    if [[ ! -x "${MODULES_DIR}/${module}" ]]; then
        log_info "Making module executable: ${module}"
        chmod +x "${MODULES_DIR}/${module}"
    fi
done

log_info "All required modules found"

# Function to run a module
run_module() {
    local module=$1
    local module_path="${MODULES_DIR}/${module}"
    local module_name=$(basename "$module" .sh)
    
    log_info "Running module: ${module_name}"
    echo -e "\n${COLOR_BLUE}===== ${module_name} =====${COLOR_RESET}\n"
    
    if [[ ! -x "$module_path" ]]; then
        log_warning "Module not executable, fixing permissions"
        chmod +x "$module_path"
    fi
    
    # Run the module and capture its exit status
    if "$module_path"; then
        log_success "Module ${module_name} completed successfully"
        return 0
    else
        local exit_code=$?
        log_error "Module ${module_name} failed with exit code ${exit_code}"
        return $exit_code
    fi
}

# Main installation flow
log_info "Starting installation process"
echo -e "\n${COLOR_GREEN}=== NEURO-LITE INSTALLATION ===${COLOR_RESET}"
echo -e "${COLOR_BLUE}This will install Neuro-Lite on your system${COLOR_RESET}\n"

# Run each module in sequence, but stop if any fails
for module in "${required_modules[@]}"; do
    if ! run_module "$module"; then
        log_error "Installation failed at module: $module"
        log_error "Please check the logs and fix the issue before retrying."
        log_error "Log file: $LOG_FILE"
        exit 1
    fi
done

# Final verification
CORE_DIR="${SCRIPT_DIR}/core"
REQUIRED_CORE_FILES=(
    "main_server.py"
    "context_manager.py"
    "post_processor.py"
    "rag_engine.py"
    "emotional_state.py"
    "llama_cpp_adapter.py"
)

for file in "${REQUIRED_CORE_FILES[@]}"; do
    if [[ ! -f "${CORE_DIR}/${file}" ]]; then
        log_error "Core file missing: ${file}"
        log_error "Installation may be corrupted"
        exit 1
    fi
done

log_success "All installation steps completed successfully"
log_success "Neuro-Lite has been installed on your system"
log_info "You can access the web interface at http://localhost:8000"
log_info "Check status with: sudo systemctl status neuro-lite"
log_info "View logs with: sudo journalctl -u neuro-lite"

exit 0
