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

log_info "Installing dependencies for Neuro-Lite"

# Set environment variable to avoid interactive prompts
export DEBIAN_FRONTEND=noninteractive

# Add retry mechanism for apt operations
apt_install_with_retry() {
    local packages=("$@")
    local max_attempts=3
    local attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        log_info "Installing packages (attempt $attempt/$max_attempts): ${packages[*]}"
        
        if apt-get install -y "${packages[@]}" > /dev/null 2>&1; then
            log_success "Successfully installed packages: ${packages[*]}"
            return 0
        else
            log_warning "Failed to install packages (attempt $attempt/$max_attempts)"
            attempt=$((attempt + 1))
            
            if [ $attempt -le $max_attempts ]; then
                log_info "Retrying in 5 seconds..."
                sleep 5
                apt-get update -qq
            fi
        fi
    done
    
    log_error "Failed to install packages after $max_attempts attempts: ${packages[*]}"
    return 1
}

# 1. Update package repositories
log_info "Updating package lists"
apt-get update -qq

# 2. Install base dependencies
log_info "Installing base dependencies"
base_deps=(
    "python3-venv"
    "python3-pip"
    "sqlite3"
    "git"
    "curl"
    "wget"
    "unzip"
    "build-essential" # Needed for llama.cpp compilation
)

apt_install_with_retry "${base_deps[@]}"

# 3. Create Python virtual environment
log_info "Setting up Python virtual environment"
APP_DIR="/opt/neuro-lite"
VENV_DIR="${APP_DIR}/venv"

# Create app directory if it doesn't exist
mkdir -p "$APP_DIR"

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    log_success "Created virtual environment at $VENV_DIR"
else
    log_info "Virtual environment already exists at $VENV_DIR"
fi

# Upgrade pip in the virtual environment
log_info "Upgrading pip in virtual environment"
"$VENV_DIR/bin/python" -m pip install --upgrade pip > /dev/null 2>&1

# 4. Install required Python packages
log_info "Installing required Python packages"
python_deps=(
    "fastapi==0.104.1"
    "uvicorn==0.23.2"
    "pydantic==2.4.2" 
    "aiohttp==3.8.6"
    "aiosqlite==0.19.0"
    "python-multipart==0.0.6"
    "jinja2==3.1.2"
    "pyyaml==6.0.1"
    "llama-cpp-python==0.2.19" # Fixed version for stability
)

"$VENV_DIR/bin/pip" install "${python_deps[@]}" > /dev/null 2>&1
log_success "Installed Python dependencies"

# 5. Check if llama-cpp-python was installed properly
if ! "$VENV_DIR/bin/python" -c "import llama_cpp; print('llama-cpp imported successfully')" > /dev/null 2>&1; then
    log_warning "llama-cpp-python not installed properly, trying to build from source"
    
    # Install with specific build options for better CPU performance
    CMAKE_ARGS="-DLLAMA_NATIVE=ON -DLLAMA_AVX2=ON" "$VENV_DIR/bin/pip" install --force-reinstall --no-cache-dir llama-cpp-python==0.2.19 > /dev/null 2>&1
    
    if ! "$VENV_DIR/bin/python" -c "import llama_cpp; print('llama-cpp imported successfully')" > /dev/null 2>&1; then
        log_error "Failed to install llama-cpp-python"
        exit 1
    else
        log_success "Successfully built llama-cpp-python from source"
    fi
fi

# 6. Create necessary directories
log_info "Creating necessary directories"
mkdir -p "${APP_DIR}/models"
mkdir -p "${APP_DIR}/data"
mkdir -p "${APP_DIR}/logs"

# 7. Set appropriate permissions
log_info "Setting appropriate permissions"
chown -R root:root "$APP_DIR"
chmod -R 755 "$APP_DIR"
chmod -R 777 "${APP_DIR}/logs" # Writable logs directory

# 8. Create a symlink to the Python binary
ln -sf "$VENV_DIR/bin/python" "/usr/local/bin/neuro-lite-python"
ln -sf "$VENV_DIR/bin/pip" "/usr/local/bin/neuro-lite-pip"

log_success "All dependencies installed successfully"
exit 0
