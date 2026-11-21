#!/usr/bin/env bash

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="${APP_USER:-${SUDO_USER:-$USER}}"
ENV_FILE="/etc/axon/axon.env"
ENABLE_WEB="${ENABLE_WEB:-0}"
ENABLE_NGINX="${ENABLE_NGINX:-0}"
WEB_PORT="${WEB_PORT:-5000}"
WEB_HOST="127.0.0.1"
PYTHON_BIN="${PYTHON_BIN:-python3}"

log() {
    printf '[axon] %s\n' "$1"
}

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        echo "Run this script with sudo." >&2
        exit 1
    fi
}

create_swap_if_missing() {
    if swapon --show | grep -q .; then
        log "Swap already configured; leaving it unchanged."
        return
    fi

    log "Creating 1G swap file for micro-instance headroom."
    fallocate -l 1G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
    swapon /swapfile
    if ! grep -q '^/swapfile ' /etc/fstab; then
        echo '/swapfile none swap sw 0 0' >> /etc/fstab
    fi
}

install_system_packages() {
    log "Installing system packages."
    apt-get update
    apt-get install -y python3-venv python3-pip python3-dev build-essential git curl

    if [[ "${ENABLE_NGINX}" == "1" ]]; then
        apt-get install -y nginx
    fi
}

install_python_dependencies() {
    chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"

    log "Creating virtual environment."
    sudo -u "${APP_USER}" "${PYTHON_BIN}" -m venv "${APP_DIR}/.venv"

    log "Installing Python dependencies."
    sudo -u "${APP_USER}" "${APP_DIR}/.venv/bin/pip" install --upgrade pip setuptools wheel
    sudo -u "${APP_USER}" "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"
}

write_env_file() {
    log "Preparing environment file at ${ENV_FILE}."
    mkdir -p /etc/axon

    if [[ ! -f "${ENV_FILE}" ]]; then
        cat > "${ENV_FILE}" <<EOF
AXON_DATABASE_URL=sqlite:///${APP_DIR}/axon.db
AXON_TRADE_MODE=PAPER
AXON_MARKET_SCAN_BATCH_SIZE=10
WEB_USERNAME=admin
WEB_PASSWORD=change-this-before-public-access

# Uncomment and fill these only when moving to live trading.
# ANGEL_ONE_API_KEY=
# ANGEL_ONE_CLIENT_ID=
# ANGEL_ONE_PIN=
# ANGEL_ONE_TOTP_SECRET=
EOF
    fi

    chmod 600 "${ENV_FILE}"
}

write_scheduler_service() {
    log "Writing systemd scheduler service."
    cat > /etc/systemd/system/axon-scheduler.service <<EOF
[Unit]
Description=Axon trading scheduler
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=${APP_DIR}/src
EnvironmentFile=${ENV_FILE}
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/run_trader.py --schedule
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
}

write_web_service() {
    log "Writing optional systemd web service."
    cat > /etc/systemd/system/axon-web.service <<EOF
[Unit]
Description=Axon web interface
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=${APP_DIR}/src
EnvironmentFile=${ENV_FILE}
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/run_web.py --host ${WEB_HOST} --port ${WEB_PORT}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
}

configure_nginx() {
    if [[ "${ENABLE_NGINX}" != "1" ]]; then
        return
    fi

    log "Configuring Nginx reverse proxy."
    cat > /etc/nginx/sites-available/axon <<EOF
server {
    listen 80 default_server;
    server_name _;

    location /socket.io/ {
        proxy_pass http://${WEB_HOST}:${WEB_PORT};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location / {
        proxy_pass http://${WEB_HOST}:${WEB_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

    ln -sf /etc/nginx/sites-available/axon /etc/nginx/sites-enabled/axon
    rm -f /etc/nginx/sites-enabled/default
    nginx -t
    systemctl enable --now nginx
    # Apply newly written site config even if nginx was already running.
    systemctl reload nginx || systemctl restart nginx
}

enable_services() {
    log "Reloading systemd and enabling scheduler."
    systemctl daemon-reload
    systemctl enable --now axon-scheduler

    if [[ "${ENABLE_WEB}" == "1" ]]; then
        systemctl enable --now axon-web
    else
        systemctl disable axon-web >/dev/null 2>&1 || true
        systemctl stop axon-web >/dev/null 2>&1 || true
    fi
}

print_summary() {
    log "Bootstrap complete."
    echo
    echo "Next steps:"
    echo "1. Edit ${ENV_FILE} with your actual credentials and web login."
    echo "2. Restart the scheduler: sudo systemctl restart axon-scheduler"
    echo "3. Tail logs: sudo journalctl -u axon-scheduler -f"
    echo "4. Optional web UI: sudo ENABLE_WEB=1 ENABLE_NGINX=1 bash scripts/bootstrap-aws-free-tier.sh"
}

require_root
install_system_packages
create_swap_if_missing
install_python_dependencies
write_env_file
write_scheduler_service
write_web_service
configure_nginx
enable_services
print_summary