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

log_info "Starting OS tuning for Neuro-Lite"

# 1. Set vm.swappiness to 10 for better memory management
log_info "Setting vm.swappiness to 10"
if grep -q "vm.swappiness" /etc/sysctl.conf; then
    # Update existing setting
    sed -i 's/^vm.swappiness=.*/vm.swappiness=10/' /etc/sysctl.conf
    log_info "Updated existing vm.swappiness setting"
else
    # Add new setting
    echo "vm.swappiness=10" >> /etc/sysctl.conf
    log_info "Added vm.swappiness=10 to sysctl.conf"
fi

# Apply the setting immediately
sysctl -w vm.swappiness=10
log_success "Applied vm.swappiness=10"

# 2. Set CPU governor to performance
if [ -d "/sys/devices/system/cpu/cpu0/cpufreq" ]; then
    log_info "Setting CPU governor to performance"
    
    # Check if cpufrequtils is installed, if not, install it
    if ! command -v cpufreq-set &> /dev/null; then
        log_info "Installing cpufrequtils"
        apt-get update -qq && apt-get install -y cpufrequtils > /dev/null 2>&1
    fi
    
    # Set governor for all CPUs
    CPUS=$(ls -d /sys/devices/system/cpu/cpu[0-9]* | grep -o 'cpu[0-9]*$')
    for cpu in $CPUS; do
        if [ -f "/sys/devices/system/cpu/$cpu/cpufreq/scaling_governor" ]; then
            echo "performance" > "/sys/devices/system/cpu/$cpu/cpufreq/scaling_governor" || true
        fi
    done
    
    # Ensure it persists across reboots
    if [ ! -f "/etc/default/cpufrequtils" ]; then
        echo 'GOVERNOR="performance"' > /etc/default/cpufrequtils
    else
        sed -i 's/^GOVERNOR=.*/GOVERNOR="performance"/' /etc/default/cpufrequtils
    fi
    
    log_success "CPU governor set to performance"
else
    log_warning "CPU frequency scaling not available on this system"
fi

# 3. Configure Huge Pages for better memory performance
log_info "Configuring Huge Pages"
if [ -d "/sys/kernel/mm/transparent_hugepage" ]; then
    # Check current setting
    current_thp=$(cat /sys/kernel/mm/transparent_hugepage/enabled | grep -o '\[[a-z]*\]' | tr -d '[]')
    
    if [ "$current_thp" != "always" ]; then
        # Create a systemd service to configure hugepages at boot
        cat > /etc/systemd/system/transparent-hugepage.service << EOF
[Unit]
Description=Configure Transparent Hugepage
After=network.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'echo always > /sys/kernel/mm/transparent_hugepage/enabled'
RemainAfterExit=true

[Install]
WantedBy=multi-user.target
EOF
        
        # Enable and start the service
        systemctl daemon-reload
        systemctl enable transparent-hugepage.service
        
        # Apply the setting now
        echo always > /sys/kernel/mm/transparent_hugepage/enabled
        
        log_success "Huge Pages configured to 'always'"
    else
        log_info "Huge Pages already configured optimally"
    fi
else
    log_warning "Transparent Huge Pages not available on this system"
fi

# 4. Check and create swap if necessary
log_info "Checking swap configuration"
SWAP_SIZE="2G"
SWAP_FILE="/swapfile"

# Get current swap size in MB
current_swap_kb=$(grep SwapTotal /proc/meminfo | awk '{print $2}')
current_swap_mb=$((current_swap_kb / 1024))

if [ "$current_swap_mb" -lt 2000 ]; then
    if [ -f "$SWAP_FILE" ]; then
        log_warning "Swap file exists but is smaller than 2GB. Keeping existing swap."
    else
        log_info "Creating 2GB swap file"
        # Create swap file
        fallocate -l $SWAP_SIZE $SWAP_FILE
        chmod 600 $SWAP_FILE
        mkswap $SWAP_FILE
        swapon $SWAP_FILE
        
        # Add to fstab if not already there
        if ! grep -q "$SWAP_FILE" /etc/fstab; then
            echo "$SWAP_FILE none swap sw 0 0" >> /etc/fstab
            log_info "Added swap to fstab"
        fi
        
        log_success "2GB swap file created and enabled"
    fi
else
    log_info "Sufficient swap already configured (${current_swap_mb}MB)"
fi

# 5. Disable unnecessary services to save resources
log_info "Disabling unnecessary services"

SERVICES_TO_DISABLE=(
    "snapd.service"
    "snapd.socket"
    "bluetooth.service"
    "cups.service"
    "avahi-daemon.service"
)

for service in "${SERVICES_TO_DISABLE[@]}"; do
    if systemctl is-active --quiet "$service"; then
        systemctl stop "$service" || true
        systemctl disable "$service" || true
        log_info "Disabled $service"
    else
        log_info "$service already inactive"
    fi
done

# Apply all sysctl settings
log_info "Applying all sysctl settings"
sysctl -p

log_success "OS tuning completed successfully"
exit 0
