#!/usr/bin/env bash
# Установка бота на чистый Ubuntu/Debian-сервер.
#
#   git clone <репозиторий> /tmp/shopbot && sudo bash /tmp/shopbot/deploy/install.sh /tmp/shopbot
#
# Скрипт: ставит python-venv, создаёт пользователя shopbot, разворачивает код
# в /opt/shopbot, ставит зависимости и systemd-юнит. Токен вписывается в .env.

set -euo pipefail

SRC="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
APP_DIR=/opt/shopbot
APP_USER=shopbot

if [[ $EUID -ne 0 ]]; then
    echo "Запустите через sudo: sudo bash deploy/install.sh" >&2
    exit 1
fi

echo "→ Пакеты"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip rsync

echo "→ Пользователь $APP_USER"
id -u "$APP_USER" &>/dev/null || useradd --system --create-home --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
mkdir -p "$APP_DIR"

echo "→ Код в $APP_DIR"
rsync -a --delete \
    --exclude '.git' --exclude 'venv' --exclude '.env' --exclude '*.db*' \
    --exclude '__pycache__' --exclude '.pytest_cache' \
    "$SRC"/ "$APP_DIR"/

echo "→ Виртуальное окружение"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

if [[ ! -f "$APP_DIR/.env" ]]; then
    cp "$APP_DIR/env.example" "$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env"
    echo "→ Создан $APP_DIR/.env — впишите BOT_TOKEN и ADMIN_IDS"
fi

chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "→ systemd"
cp "$APP_DIR/deploy/shopbot.service" /etc/systemd/system/shopbot.service
systemctl daemon-reload
systemctl enable shopbot >/dev/null

cat <<TXT

Готово. Осталось два шага:

  1. sudo nano $APP_DIR/.env          # BOT_TOKEN, ADMIN_IDS
  2. sudo -u $APP_USER $APP_DIR/venv/bin/python $APP_DIR/doctor.py   # проверка
     sudo systemctl start shopbot     # запуск

Логи:      journalctl -u shopbot -f
Перезапуск: sudo systemctl restart shopbot
TXT
