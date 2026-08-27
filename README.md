# 🛍 Telegram-бот для продаж

Магазин внутри Telegram: каталог → корзина → оформление заказа → уведомление админу.
Написан на **aiogram 3** + SQLite, без внешних сервисов.

## Возможности

**Для покупателя**
- Каталог с категориями, фото, описанием и ценой
- Корзина: добавить, изменить количество, удалить, очистить
- Оформление заказа: имя, телефон (кнопкой «поделиться контактом»), адрес, комментарий
- Оплата: при получении / переводом / онлайн — картой через провайдера или ⭐ Telegram Stars
- История своих заказов и уведомления о смене статуса

**Для админа**
- Категории: добавить / удалить
- Товары: добавить (пошагово, с фото), скрыть/показать, удалить
- Заказы: список, карточка заказа, смена статуса (клиенту уходит уведомление)
- Статистика: пользователи, заказы, оборот
- Рассылка по всем пользователям бота (текст, фото, видео)
- Возврат оплаты звёздами: `/refund <номер заказа>`

## Быстрый старт

```bash
# 1. Зависимости
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. Настройки
cp env.example .env             # Windows: copy env.example .env
```

В `.env` заполните:
- `BOT_TOKEN` — получить у [@BotFather](https://t.me/BotFather) командой `/newbot`
- `ADMIN_IDS` — ваш ID, узнать у [@userinfobot](https://t.me/userinfobot)

```bash
python seed.py        # (по желанию) демо-каталог
python doctor.py      # проверка: .env, база, связь с Telegram, оплата
python bot.py         # запуск
```

Откройте бота в Telegram и нажмите **Start**.

## Развёртывание на сервере

Бот умеет работать в двух режимах:

| Режим | Когда выбирать | Что нужно |
|---|---|---|
| `polling` (по умолчанию) | почти всегда: VPS, домашний сервер, Docker | только выход в интернет |
| `webhook` | высокая нагрузка, уже есть домен и nginx | домен + HTTPS-сертификат |

### Вариант 1. Docker (самый простой)

```bash
git clone <репозиторий> shopbot && cd shopbot
cp env.example .env && nano .env        # BOT_TOKEN, ADMIN_IDS
docker compose up -d --build
docker compose logs -f
```

База лежит в томе `shopdata` и переживает пересборку образа.
В образ встроен healthcheck (`docker ps` покажет `healthy`).

### Вариант 2. systemd на Ubuntu/Debian

```bash
git clone <репозиторий> /tmp/shopbot
sudo bash /tmp/shopbot/deploy/install.sh /tmp/shopbot
sudo nano /opt/shopbot/.env             # BOT_TOKEN, ADMIN_IDS
sudo -u shopbot /opt/shopbot/venv/bin/python /opt/shopbot/doctor.py
sudo systemctl start shopbot
```

Скрипт создаёт пользователя `shopbot`, разворачивает код в `/opt/shopbot`,
ставит зависимости в venv и включает автозапуск.

```bash
journalctl -u shopbot -f          # логи
sudo systemctl restart shopbot    # перезапуск после правки .env
```

### Вариант 3. Webhook за nginx

```env
BOT_MODE=webhook
WEBHOOK_URL=https://shop.example.com
WEBHOOK_PATH=/webhook
WEBHOOK_SECRET=<openssl rand -hex 32>
PORT=8080
```

Конфиг nginx — в [`deploy/nginx.conf.example`](deploy/nginx.conf.example),
сертификат проще всего получить через `certbot --nginx`. Telegram принимает
только HTTPS и порты 443, 80, 88, 8443. Бот сам вызывает `setWebhook` при старте
и проверяет секретный заголовок каждого запроса. Для мониторинга есть
`GET /healthz`.

### Проверка и обслуживание

```bash
python doctor.py             # полная диагностика, включая getMe и webhook
python doctor.py --offline   # без обращения к Telegram
python doctor.py --health    # короткая проверка для мониторинга (код возврата)
python -m pytest -q          # тесты (49 шт., без сети и без токена)

bash deploy/backup.sh        # бэкап базы; в cron: 0 4 * * * /opt/shopbot/deploy/backup.sh
```

Если сервер ходит в интернет только через прокси — `TELEGRAM_PROXY` в `.env`
(и `pip install aiohttp-socks`).

## Оплата

Всегда доступны оплата при получении и перевод на карту. Онлайн-оплата
включается одной настройкой:

```env
# Telegram Stars — ничего подключать не нужно (цифровые товары и услуги)
PAYMENT_CURRENCY_CODE=XTR
STARS_RATE=2.0                  # сколько рублей прайса в одной ⭐

# ...или карты через провайдера (@BotFather → Payments), для физических товаров
PAYMENT_CURRENCY_CODE=RUB
PAYMENT_PROVIDER_TOKEN=390540012:TEST:xxxxxxxx
```

Кнопка «💳 Онлайн-оплата» появляется автоматически. Заказ с онлайн-оплатой
создаётся со статусом «⏳ Ожидает оплаты»: склад и корзина не трогаются, пока
Telegram не подтвердит платёж. Возврат звёзд — `/refund <номер заказа>`.

Что выбрать, сколько это стоит и как подключить — в
[`docs/payments.md`](docs/payments.md).

## Файлы

| Файл | Назначение |
|---|---|
| `bot.py` | запуск (polling/webhook), роутеры, обработчик ошибок |
| `config.py` | настройки из `.env` и их проверка |
| `database.py` | SQLite: схема, миграции и все запросы |
| `keyboards.py` | клавиатуры |
| `handlers_user.py` | каталог, корзина, заказ, оплата |
| `handlers_admin.py` | админ-панель, рассылка, возвраты |
| `utils.py` | форматирование, статусы, пересчёт в звёзды |
| `doctor.py` | самодиагностика перед запуском |
| `seed.py` | демо-данные |
| `deploy/` | systemd-юнит, nginx, установка, бэкап |
| `tests/` | тесты сценариев на поддельной Telegram-сессии |

## Как доработать

- **Скидки/промокоды** — таблица `promocodes` и шаг ввода кода перед выбором оплаты
  в `handlers_user.checkout_comment`.
- **Доставка** — добавьте выбор способа и стоимость к `total` в `database.create_order`.
- **Хранение FSM в Redis** — замените `MemoryStorage()` на `RedisStorage.from_url(...)`
  в `bot.create_dispatcher`, чтобы незаконченные анкеты переживали перезапуск.
- **Несколько фото у товара** — таблица `product_photos` и `send_media_group`.

## Важно

`.env` и `shop.db` не должны попадать в git — там токен бота и персональные данные
клиентов (в `.gitignore` они уже перечислены). Если продаёте физические товары,
проверьте требования к обработке персональных данных и 54-ФЗ в вашей юрисдикции.
