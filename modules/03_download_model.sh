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

# Script variables
MODEL_NAME="Qwen2.5-3B-Instruct-Q4_K_M.gguf"
MODEL_URL="https://huggingface.co/TheBloke/Qwen2.5-3B-Instruct-GGUF/resolve/main/Qwen2.5-3B-Instruct-Q4_K_M.gguf"
CHECKSUM="e65e8cbcfbbaad677a5a4e5085c4c15ec8267cfd53c5da24b2db667c049d15a5"
CHECKSUM_TYPE="sha256"
MODEL_DIR="/opt/neuro-lite/models"
MODEL_PATH="${MODEL_DIR}/${MODEL_NAME}"
TEMP_DIR="/tmp/neuro-lite-downloads"

# Create directories if they don't exist
mkdir -p "$MODEL_DIR"
mkdir -p "$TEMP_DIR"

# Function to verify checksum
verify_checksum() {
    local file=$1
    local expected_checksum=$2
    local checksum_type=$3
    
    log_info "Verifying $checksum_type checksum"
    
    if [ "$checksum_type" == "md5" ]; then
        actual_checksum=$(md5sum "$file" | awk '{print $1}')
    elif [ "$checksum_type" == "sha256" ]; then
        actual_checksum=$(sha256sum "$file" | awk '{print $1}')
    else
        log_error "Unsupported checksum type: $checksum_type"
        return 1
    fi
    
    if [ "$actual_checksum" == "$expected_checksum" ]; then
        log_success "Checksum verification passed"
        return 0
    else
        log_error "Checksum verification failed"
        log_error "Expected: $expected_checksum"
        log_error "Actual:   $actual_checksum"
        return 1
    fi
}

# Check if model already exists and is valid
if [ -f "$MODEL_PATH" ]; then
    log_info "Model file already exists: $MODEL_PATH"
    
    # Verify checksum if available
    if [ -n "$CHECKSUM" ]; then
        if verify_checksum "$MODEL_PATH" "$CHECKSUM" "$CHECKSUM_TYPE"; then
            log_success "Existing model file is valid"
            exit 0
        else
            log_warning "Existing model file is corrupt or invalid"
            log_info "Renaming existing model file to ${MODEL_NAME}.invalid"
            mv "$MODEL_PATH" "${MODEL_PATH}.invalid"
        fi
    else
        # If no checksum provided, just check if the file size is reasonable (at least 1GB)
        file_size=$(stat -c %s "$MODEL_PATH")
        if [ "$file_size" -gt 1073741824 ]; then
            log_success "Existing model file seems valid (no checksum available)"
            exit 0
        else
            log_warning "Existing model file seems too small, might be corrupt"
            log_info "Renaming existing model file to ${MODEL_NAME}.invalid"
            mv "$MODEL_PATH" "${MODEL_PATH}.invalid"
        fi
    fi
fi

# Download the model with resume capability
log_info "Downloading model: $MODEL_NAME"
log_info "URL: $MODEL_URL"
log_info "This may take a while depending on your internet speed..."

# Temporary download location
TEMP_DOWNLOAD="${TEMP_DIR}/${MODEL_NAME}.download"

# Use wget with retry and resume capability
wget_options=(
    "--continue"            # Resume download if possible
    "--retry-connrefused"   # Retry if connection refused
    "--waitretry=1"         # Wait 1 second between retries
    "--timeout=20"          # Connection timeout
    "--tries=5"             # Number of retries
    "--show-progress"       # Show progress bar
    "-O" "$TEMP_DOWNLOAD"   # Output file
)

# Start download
if wget "${wget_options[@]}" "$MODEL_URL"; then
    log_success "Download completed successfully"
else
    exit_code=$?
    log_error "Download failed with exit code $exit_code"
    exit 1
fi

# Verify checksum if available
if [ -n "$CHECKSUM" ]; then
    if ! verify_checksum "$TEMP_DOWNLOAD" "$CHECKSUM" "$CHECKSUM_TYPE"; then
        log_error "Downloaded file failed checksum verification"
        log_error "Please try downloading again"
        exit 1
    fi
fi

# Move the file to the final location
log_info "Moving model file to $MODEL_PATH"
mv "$TEMP_DOWNLOAD" "$MODEL_PATH"

# Set appropriate permissions
chmod 644 "$MODEL_PATH"

log_success "Model downloaded and verified successfully"
log_info "Model location: $MODEL_PATH"
log_info "Model size: $(du -h "$MODEL_PATH" | cut -f1)"

exit 0
