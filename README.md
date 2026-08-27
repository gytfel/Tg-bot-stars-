# 🛍 Telegram-бот для продаж

Магазин внутри Telegram: каталог → корзина → оформление заказа → уведомление админу.
Написан на **aiogram 3** + SQLite, без внешних сервисов.

## Возможности

**Для покупателя**
- Каталог с категориями, фото, описанием и ценой
- Корзина: добавить, изменить количество, удалить, очистить
- Оформление заказа: имя, телефон (кнопкой «поделиться контактом»), адрес, комментарий
- Оплата: при получении / переводом / онлайн через Telegram Payments
- История своих заказов и уведомления о смене статуса

**Для админа**
- Категории: добавить / удалить
- Товары: добавить (пошагово, с фото), скрыть/показать, удалить
- Заказы: список, карточка заказа, смена статуса (клиенту уходит уведомление)
- Статистика: пользователи, заказы, оборот
- Рассылка по всем пользователям бота

## Установка

```bash
# 1. Зависимости
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. Настройки
cp .env.example .env            # Windows: copy .env.example .env
```

В `.env` заполните:
- `BOT_TOKEN` — получить у [@BotFather](https://t.me/BotFather) командой `/newbot`
- `ADMIN_IDS` — ваш ID, узнать у [@userinfobot](https://t.me/userinfobot)

```bash
# 3. (по желанию) демо-каталог
python seed.py

# 4. Запуск
python bot.py
```

Откройте бота в Telegram и нажмите **Start**.

## Онлайн-оплата

По умолчанию доступны оплата при получении и перевод. Чтобы включить оплату картой прямо
в боте: `@BotFather → /mybots → ваш бот → Payments`, подключите провайдера (ЮKassa, Stripe
и др.), скопируйте токен в `PAYMENT_PROVIDER_TOKEN`. Кнопка «💳 Онлайн-оплата» появится
автоматически. Для тестов у провайдеров есть тестовые токены и карта `4242 4242 4242 4242`.

## Файлы

| Файл | Назначение |
|---|---|
| `bot.py` | запуск, подключение роутеров |
| `config.py` | настройки из `.env` |
| `database.py` | SQLite: схема и все запросы |
| `keyboards.py` | клавиатуры |
| `handlers_user.py` | каталог, корзина, заказ, оплата |
| `handlers_admin.py` | админ-панель |
| `utils.py` | форматирование, статусы |
| `seed.py` | демо-данные |

## Как доработать

- **Скидки/промокоды** — таблица `promocodes` и шаг ввода кода перед выбором оплаты
  в `handlers_user.checkout_comment`.
- **Доставка** — добавьте выбор способа и стоимость к `total` в `database.create_order`.
- **Хранение FSM в Redis** — замените `MemoryStorage()` на `RedisStorage.from_url(...)`
  в `bot.py`, чтобы состояния переживали перезапуск.
- **Несколько фото у товара** — таблица `product_photos` и `send_media_group`.

## Развёртывание на сервере

```bash
sudo tee /etc/systemd/system/shopbot.service >/dev/null <<'EOF'
[Unit]
Description=Telegram Shop Bot
After=network.target

[Service]
WorkingDirectory=/opt/shopbot
ExecStart=/opt/shopbot/venv/bin/python bot.py
Restart=always
User=www-data

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable --now shopbot
```

## Важно

Не публикуйте `.env` и файл `shop.db` в git — там токен бота и персональные данные
клиентов. Если продаёте физические товары, проверьте требования к обработке
персональных данных в вашей юрисдикции.
