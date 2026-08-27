# 🛍 Telegram-бот для продаж

Магазин внутри Telegram: каталог → корзина → оплата → выдача товара.
Написан на **aiogram 3** + SQLite, без внешних сервисов.

По умолчанию бот настроен на **цифровой товар** (`SHOP_MODE=digital`): доступы,
файлы, консультации, подписки. Оплата — ⭐ Telegram Stars, доступ уходит покупателю
автоматически сразу после платежа. Для физических товаров есть режим
`SHOP_MODE=physical`: анкета с телефоном и адресом, оплата при получении.

## Возможности

**Для покупателя**
- Каталог с категориями, фото, описанием и ценой
- Корзина: добавить, изменить количество, удалить, очистить
- Цифровой товар: оформление в два тапа — корзина, оплата, доступ в чат
- Физический товар: анкета с именем, телефоном (кнопкой «поделиться контактом») и адресом
- Оплата: ⭐ Telegram Stars, карта через провайдера, перевод, при получении
- История своих заказов и уведомления о смене статуса

**Для админа**
- Категории: добавить / удалить
- Товары: добавить (пошагово, с фото), скрыть/показать, удалить
- Заказы: список, карточка заказа, смена статуса (клиенту уходит уведомление)
- Статистика: пользователи, заказы, оборот
- Рассылка по всем пользователям бота (текст, фото, видео)
- Возврат оплаты звёздами: `/refund <номер заказа>`
- Управление с сервера через терминал: `python manage.py ...` (см. ниже)

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
python seed.py                 # (по желанию) демо-каталог
python manage.py check         # проверка: .env, база, связь с Telegram, оплата
python manage.py run           # запуск (то же самое, что python bot.py)
```

Откройте бота в Telegram и нажмите **Start**.

## Цифровой товар: что бот выдаёт после оплаты

У каждого товара есть поле «что выдать после оплаты» — ссылка, ключ, инструкция
или файл. Заполняется при добавлении товара в админ-панели (шаг 5 из 5) либо из
терминала:

```bash
python manage.py product content 3 "https://example.com/course · код PY-2026"
```

Как это работает: покупатель оплачивает → Telegram подтверждает платёж → бот
отправляет содержимое в чат и переводит заказ в «✅ Выполнен». Содержимое
сохраняется в самом заказе, поэтому выдача работает даже если товар потом удалили
из каталога. Если покупатель заблокировал бота, заказ **не** помечается выданным —
повторить можно командой `python manage.py deliver <номер>`. Если у товара не
заполнено, что выдавать, покупатель получит «доступ вышлет менеджер», а админ —
предупреждение.

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
python manage.py status      # что с ботом, сервисом и базой прямо сейчас
python doctor.py             # полная диагностика, включая getMe и webhook
python doctor.py --offline   # без обращения к Telegram
python doctor.py --health    # короткая проверка для мониторинга (код возврата)
python -m pytest -q          # тесты (83 шт., без сети и без токена)

python manage.py backup      # копия базы; в cron: 0 4 * * * /opt/shopbot/deploy/backup.sh
```

Если сервер ходит в интернет только через прокси — `TELEGRAM_PROXY` в `.env`
(и `pip install aiohttp-socks`).

## Управление из терминала

Всё, что можно сделать в админ-панели бота, доступно и с сервера — по SSH,
без Telegram. `python manage.py` без аргументов покажет список команд.

```bash
# бот и сервис
python manage.py status                  # режим, оплата, состояние сервиса, сводка по базе
python manage.py check                   # полная диагностика (включая связь с Telegram)
python manage.py start | stop | restart  # systemd или docker — определяется автоматически
python manage.py logs -f                 # логи сервиса
python manage.py run                     # запустить бота прямо в этом терминале

# каталог
python manage.py catalog                 # дерево категорий и товаров
python manage.py category add "📚 Курсы"
python manage.py product add --cat 1 --title "Python с нуля" --price 2900 \
                             --desc "12 уроков" --content "https://example.com/py"
python manage.py product content 3 "https://example.com/course"
python manage.py product show 3
python manage.py product toggle 3        # скрыть или вернуть в каталог
python manage.py product rm 3

# заказы и покупатели
python manage.py orders --status new
python manage.py order show 12
python manage.py order status 12 paid    # сменит статус, уведомит клиента и выдаст товар
python manage.py deliver 12              # повторная выдача доступа
python manage.py refund 12               # возврат звёзд
python manage.py users
python manage.py stats                   # продажи, статусы, топ товаров

# прочее
python manage.py broadcast "Новый курс уже в каталоге" --dry-run
python manage.py backup --dir /var/backups/shopbot
```

Команды, которые пишут покупателям (`broadcast`, `deliver`, `refund`,
`order status`), обращаются к Telegram — им нужен рабочий `BOT_TOKEN`.
Остальные работают с базой напрямую и не требуют сети.

В Docker те же команды выполняются внутри контейнера:

```bash
docker compose exec bot python manage.py stats
```

Через systemd — от пользователя бота, чтобы не сломать права на базу:

```bash
sudo -u shopbot /opt/shopbot/venv/bin/python /opt/shopbot/manage.py orders
```

## Оплата

По умолчанию включены Telegram Stars — для цифровых товаров ничего подключать не
нужно:

```env
PAYMENT_CURRENCY_CODE=XTR
STARS_RATE=2.0                  # сколько рублей прайса в одной ⭐
```

Для физических товаров звёзды использовать нельзя — нужен провайдер:

```env
SHOP_MODE=physical
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
| `manage.py` | управление магазином из терминала |
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
