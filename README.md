# ⭐ Telegram-бот для продажи звёзд

Продажа Telegram Stars прямо в чате: покупатель выбирает количество, платит в TON,
бот закупает звёзды через Fragment и зачисляет их получателю.
Написан на **aiogram 3** + SQLite.

```
выбрал 500 ⭐  →  счёт 2,5 TON  →  перевёл  →  бот увидел платёж  →  звёзды у получателя
```

Тот же бот умеет работать обычным магазином — режим переключается одной
настройкой `SHOP_MODE`:

| Режим | Что продаём | Как оформляется |
|---|---|---|
| `stars` (по умолчанию) | Telegram Stars | количество → @username → оплата в TON |
| `digital` | доступы, файлы, консультации | каталог → корзина → оплата → выдача в чат |
| `physical` | физические товары | каталог → корзина → анкета с адресом → доставка |

## Возможности

**Продажа звёзд**
- Готовые наборы (50 / 100 / 250 / 500 / 1000 ⭐) и своё количество
- Минимум 50 ⭐ — столько же минимум у самого Fragment
- Получатель — свой аккаунт в одно нажатие или чужой @username
- Счёт в TON по актуальному курсу, оплата подтверждается автоматически
- Закупка через Fragment: автоматически по API-шлюзу или вручную с задачей админу
- Повторы при сбоях шлюза, ни один оплаченный заказ не теряется

**Обычный магазин (digital / physical)**
- Каталог с категориями, фото, описанием и ценой
- Корзина: добавить, изменить количество, удалить, очистить
- Цифровой товар: оформление в два тапа и выдача доступа в чат
- Физический товар: анкета с именем, телефоном и адресом
- Оплата: ⭐ Telegram Stars, карта через провайдера, перевод, при получении
- История своих заказов и уведомления о смене статуса

**Для админа**
- Категории: добавить / удалить
- Товары: добавить (пошагово, с фото), скрыть/показать, удалить
- Заказы: список, карточка заказа, смена статуса (клиенту уходит уведомление)
- Статистика: пользователи, заказы, оборот
- Рассылка по всем пользователям бота (текст, фото, видео)
- `/stars` — оплаченные, но не выданные заказы; кнопки «Купил, зачислено» и «Повторить»
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

## Продажа звёзд

Минимальная настройка — цена, минимум и кошелёк для приёма TON:

```env
SHOP_MODE=stars
STAR_PRICE=1.6                 # рублей за одну ⭐
MIN_STARS=50                   # меньше не продаёт сам Fragment
STAR_PACKAGES=50,100,250,500,1000
TON_WALLET=UQ...               # нужен только адрес, ключи боту не нужны
TON_RATE_RUB=0                 # 0 — курс из API, иначе фиксированный
```

Прайс и суммы в TON: `python manage.py stars price`.

**Как приходит оплата.** Покупателю показывается адрес кошелька и обязательный
комментарий вида `order_42`. Бот раз в минуту читает входящие переводы через
публичный TON API и, найдя нужный, отмечает заказ оплаченным. Приватные ключи
для этого не нужны — читается только публичная история кошелька.

**Как закупаются звёзды.** У Fragment нет официального публичного API, поэтому
есть два режима:

```env
FRAGMENT_MODE=manual           # бот присылает админу задачу купить вручную
# или
FRAGMENT_MODE=api              # автозакупка через сторонний шлюз
FRAGMENT_API_URL=https://шлюз.example
FRAGMENT_API_TOKEN=токен
```

В ручном режиме бот всё равно принимает деньги и ведёт заказ: админ получает
задачу «купить 500 ⭐ для @username» с кнопкой «Купил, зачислено». В режиме `api`
бот покупает сам, при временных сбоях шлюза повторяет попытки, а если не вышло —
зовёт админа. Оплаченные, но не выданные заказы всегда видно:
`python manage.py stars pending`.

Подробности, контракт шлюза и разбор сбоев — в
[`docs/fragment.md`](docs/fragment.md).

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
python -m pytest -q          # тесты (187 шт., без сети и без токена)

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

# звёзды
python manage.py stars price              # прайс по наборам и суммы в TON
python manage.py stars rate               # текущий курс TON
python manage.py stars balance            # баланс шлюза Fragment
python manage.py stars pending            # оплачено, но не выдано
python manage.py stars check              # разово проверить входящие переводы
python manage.py stars fulfil 12          # выдать через шлюз
python manage.py stars fulfil 12 --manual # звёзды куплены вручную, закрыть заказ

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
[`docs/payments.md`](docs/payments.md), а про закупку звёзд и TON —
в [`docs/fragment.md`](docs/fragment.md).

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
| `handlers_stars.py` | покупка звёзд: количество, получатель, счёт |
| `stars.py` | цена, проверки и выдача заказа на звёзды |
| `fragment.py` | закупка звёзд: шлюз или ручной режим |
| `ton.py` | оплата в TON: курс, счёт, поиск перевода |
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
