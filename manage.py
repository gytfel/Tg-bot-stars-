"""Управление ботом из терминала.

    python manage.py                    список команд
    python manage.py status             жив ли бот, что в базе
    python manage.py catalog            каталог целиком
    python manage.py orders --status new
    python manage.py broadcast "Новый курс уже в каталоге"

Команды, которые пишут покупателям (broadcast, deliver, refund, order status),
обращаются к Telegram — им нужен рабочий BOT_TOKEN. Остальные работают
с базой напрямую и не требуют сети.
"""

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
from datetime import datetime

import database as db
from config import settings
from utils import MANUAL_STATUSES, PAYMENTS, STATUSES, money, stars, to_stars

# ------------------------------------------------------------------- оформление

COLORS = {"grey": "90", "red": "31", "green": "32", "yellow": "33", "blue": "34", "bold": "1"}


def paint(text: str, color: str) -> str:
    if not sys.stdout.isatty() or os.getenv("NO_COLOR"):
        return text
    return f"\033[{COLORS[color]}m{text}\033[0m"


def title(text: str) -> None:
    print(f"\n{paint(text, 'bold')}")


def table(headers: list[str], rows: list[list[str]]) -> None:
    """Простая выровненная таблица."""
    if not rows:
        print(paint("  — пусто —", "grey"))
        return
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    print("  " + paint("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)), "grey"))
    for row in rows:
        print("  " + "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)))


def price_of(value: float) -> str:
    """Цена в валюте магазина, а для Stars — ещё и в звёздах."""
    if settings.pay_in_stars:
        return f"{stars(to_stars(value))} ({money(value)})"
    return money(value)


def short(text: str | None, limit: int = 46) -> str:
    if not text:
        return "—"
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit - 1] + "…"


def fail(message: str) -> None:
    print(paint(f"✖ {message}", "red"))
    raise SystemExit(1)


def done(message: str) -> None:
    print(paint(f"✔ {message}", "green"))


# ------------------------------------------------------------ сервис и процесс

def detect_service() -> str:
    """Как именно запущен бот: systemd, docker или вручную."""
    if shutil.which("systemctl"):
        result = subprocess.run(["systemctl", "list-unit-files", "shopbot.service"],
                                capture_output=True, text=True)
        if "shopbot.service" in result.stdout:
            return "systemd"
    if shutil.which("docker") and os.path.exists("docker-compose.yml"):
        return "docker"
    return "none"


def service_command(action: str, service: str, follow: bool = False, lines: int = 80) -> list[str]:
    if service == "systemd":
        if action == "logs":
            return ["journalctl", "-u", "shopbot", "-n", str(lines)] + (["-f"] if follow else [])
        return ["sudo", "systemctl", action, "shopbot"]
    mapping = {"start": ["up", "-d"], "stop": ["down"], "restart": ["restart"]}
    if action == "logs":
        return ["docker", "compose", "logs", "--tail", str(lines)] + (["-f"] if follow else [])
    return ["docker", "compose"] + mapping[action]


def run_service(action: str, args) -> None:
    service = args.service if args.service != "auto" else detect_service()
    if service == "none":
        fail("Не нашёл ни systemd-юнит shopbot, ни docker-compose.yml.\n"
             "  Запустить вручную: python manage.py run\n"
             "  Установить как сервис: sudo bash deploy/install.sh")
    command = service_command(action, service,
                              follow=getattr(args, "follow", False),
                              lines=getattr(args, "lines", 80))
    print(paint(f"$ {' '.join(command)}", "grey"))
    raise SystemExit(subprocess.run(command).returncode)


def service_state() -> str:
    service = detect_service()
    if service == "systemd":
        result = subprocess.run(["systemctl", "is-active", "shopbot"],
                                capture_output=True, text=True)
        state = result.stdout.strip() or "unknown"
        return f"systemd: {paint(state, 'green' if state == 'active' else 'yellow')}"
    if service == "docker":
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "{{.Name}} {{.State}}"],
            capture_output=True, text=True)
        return f"docker: {result.stdout.strip() or paint('не запущен', 'yellow')}"
    return paint("не установлен как сервис (запуск вручную)", "grey")


# --------------------------------------------------------------------- команды

KIND = {"stars": "продажа звёзд", "digital": "цифровой товар",
        "physical": "физический товар"}


async def cmd_status(args) -> None:
    title("Бот")
    print(f"  Магазин:  {settings.shop_name} · {KIND.get(settings.shop_mode, '—')}")
    print(f"  Режим:    {settings.mode} · логи {settings.log_level}")
    print(f"  Оплата:   {payment_summary()}")
    print(f"  Сервис:   {service_state()}")
    if settings.stars_shop:
        print(f"  Звёзды:   {money(settings.star_price)} за ⭐ · минимум "
              f"{settings.min_stars} ⭐ · закупка "
              f"{'через шлюз' if settings.fragment_auto else 'вручную'}")

    problems = settings.validate()
    if problems:
        title("Проблемы в настройках")
        for problem in problems:
            print(f"  {paint('!', 'yellow')} {problem}")

    await db.init_db()
    stats = await db.get_stats()
    title("База")
    print(f"  {settings.db_path}")
    table(["пользователей", "товаров", "заказов", "новых", "оборот"],
          [[stats["users"], stats["products"], stats["orders"], stats["new_orders"],
            money(stats["revenue"])]])
    print(paint("\n  Полная диагностика со связью с Telegram: python manage.py check", "grey"))


def payment_summary() -> str:
    if settings.stars_shop and settings.ton_enabled:
        return f"TON на {settings.ton_wallet[:12]}…"
    if settings.pay_in_stars:
        return f"Telegram Stars, {settings.stars_rate} {settings.currency} за ⭐"
    if settings.payment_token:
        return f"провайдер {settings.payment_token.split(':')[0]}, {settings.payment_currency}"
    return paint("онлайн-оплата выключена", "yellow")


async def cmd_check(args) -> None:
    import doctor
    sys.argv = ["doctor.py"] + (["--offline"] if args.offline else [])
    raise SystemExit(await doctor.main())


async def cmd_catalog(args) -> None:
    await db.init_db()
    categories = await db.get_categories(only_active=False)
    if not categories:
        print(paint("Каталог пуст. Демо-товары: python seed.py", "grey"))
        return
    for category in categories:
        products = await db.get_products(category["id"], only_active=False)
        title(f"{category['title']}  (id {category['id']})")
        rows = []
        for p in products:
            content = p["content"] or ("файл" if p["content_file_id"] else None)
            rows.append([p["id"], "🟢" if p["is_active"] else "🔴", short(p["title"], 30),
                         price_of(p["price"]), p["stock"],
                         short(content, 34) if settings.digital else "—"])
        table(["id", "", "товар", "цена", "остаток", "выдаётся"], rows)


async def cmd_category(args) -> None:
    await db.init_db()
    if args.action == "add":
        cat_id = await db.add_category(args.value)
        done(f"Категория «{args.value}» добавлена, id {cat_id}")
    else:
        category = await db.get_category(int(args.value))
        if not category:
            fail(f"Категории {args.value} нет")
        await db.delete_category(int(args.value))
        done(f"Категория «{category['title']}» удалена вместе с товарами")


async def cmd_product(args) -> None:
    await db.init_db()

    if args.action == "add":
        if not await db.get_category(args.cat):
            fail(f"Категории {args.cat} нет. Список: python manage.py catalog")
        product_id = await db.add_product(args.cat, args.title, args.desc or "",
                                          args.price, None, stock=args.stock,
                                          content=args.content)
        done(f"Товар «{args.title}» добавлен, id {product_id}")
        if settings.digital and not args.content:
            print(paint(f"  Не забудьте: python manage.py product content {product_id} "
                        f"\"ссылка или ключ\"", "yellow"))
        return

    product = await db.get_product(args.id)
    if not product:
        fail(f"Товара {args.id} нет")

    if args.action == "show":
        title(f"{product['title']}  (id {product['id']})")
        print(f"  Категория:  {product['category_id']}")
        print(f"  Цена:       {price_of(product['price'])}")
        print(f"  Остаток:    {product['stock']}")
        print(f"  В каталоге: {'да' if product['is_active'] else 'нет'}")
        print(f"  Описание:   {short(product['description'], 70)}")
        print(f"  Выдаётся:   {product['content'] or '—'}")
        if product["content_file_id"]:
            print(f"  Файл:       {product['content_file_id']}")
    elif args.action == "content":
        await db.set_product_content(args.id, args.value)
        done(f"«{product['title']}»: после оплаты будет выдаваться «{short(args.value)}»")
    elif args.action == "toggle":
        await db.toggle_product(args.id)
        state = "скрыт" if product["is_active"] else "показан"
        done(f"Товар «{product['title']}» {state}")
    elif args.action == "rm":
        await db.delete_product(args.id)
        done(f"Товар «{product['title']}» удалён")


async def cmd_orders(args) -> None:
    await db.init_db()
    orders = await db.get_orders(limit=args.limit)
    if args.status:
        orders = [o for o in orders if o["status"] == args.status]
    title(f"Заказы ({len(orders)})")
    if settings.stars_shop:
        table(["id", "дата", "звёзд", "получатель", "сумма", "статус"],
              [[o["id"], o["created_at"][:16].replace("T", " "), o["stars_qty"] or "—",
                f"@{o['recipient']}" if o["recipient"] else "—", money(o["total"]),
                STATUSES.get(o["status"], o["status"])] for o in orders])
        return
    table(["id", "дата", "сумма", "статус", "оплата", "клиент"],
          [[o["id"], o["created_at"][:16].replace("T", " "), money(o["total"]),
            STATUSES.get(o["status"], o["status"]),
            PAYMENTS.get(o["payment_method"], "—"), o["user_id"]] for o in orders])


async def cmd_order(args) -> None:
    await db.init_db()
    order = await db.get_order(args.id)
    if not order:
        fail(f"Заказа #{args.id} нет")
    title(f"Заказ #{order['id']} · {STATUSES.get(order['status'], order['status'])}")
    table(["товар", "кол-во", "сумма"],
          [[short(i["title"], 34), i["quantity"], money(i["price"] * i["quantity"])]
           for i in order["items"]])
    print(f"\n  Итого:    {money(order['total'])}")
    print(f"  Создан:   {order['created_at'].replace('T', ' ')}")
    print(f"  Оплата:   {PAYMENTS.get(order['payment_method'], '—')}"
          f"{' · ' + order['charge_id'] if order['charge_id'] else ''}")
    if order["paid_at"]:
        print(f"  Оплачен:  {order['paid_at'].replace('T', ' ')}")
    if order["delivered_at"]:
        print(f"  Выдан:    {order['delivered_at'].replace('T', ' ')}")
    if order["stars_qty"]:
        print(f"  Звёзды:   {order['stars_qty']} ⭐ → @{order['recipient']}")
        print(f"  Fragment: {order['fragment_ref'] or '—'}"
              f"{'  ⚠️ ' + order['fragment_error'] if order['fragment_error'] else ''}"
              f" · попыток {order['attempts']}")
    if order["ton_amount"]:
        print(f"  TON:      {order['ton_amount']} с комментарием {order['ton_comment']}"
              f"{' · ' + order['ton_tx'] if order['ton_tx'] else ''}")
    print(f"  Клиент:   {order['name'] or '—'} · id {order['user_id']}")
    for label, key in (("Телефон", "phone"), ("Адрес", "address"), ("Комментарий", "comment")):
        if order[key]:
            print(f"  {label + ':':10}{order[key]}")


async def cmd_status_set(args) -> None:
    if args.status not in MANUAL_STATUSES:
        fail(f"Статус должен быть одним из: {', '.join(MANUAL_STATUSES)}")
    await db.init_db()
    order = await db.get_order(args.id)
    if not order:
        fail(f"Заказа #{args.id} нет")

    await db.set_status(args.id, args.status)
    done(f"Заказ #{args.id}: {STATUSES[args.status]}")

    async with telegram() as bot:
        await notify(bot, order["user_id"],
                     f"Статус вашего заказа #{args.id}: <b>{STATUSES[args.status]}</b>")
        if args.status == "paid" and settings.digital:
            from handlers_user import deliver_order
            if await deliver_order(bot, args.id):
                done("Цифровой товар выдан покупателю")


async def cmd_deliver(args) -> None:
    await db.init_db()
    if not await db.get_order(args.id):
        fail(f"Заказа #{args.id} нет")
    from handlers_user import deliver_order
    async with telegram() as bot:
        if await deliver_order(bot, args.id):
            done(f"Заказ #{args.id} выдан покупателю")
        else:
            fail("Выдать не удалось: заказ уже выдан или у товара не заполнено содержимое")


async def cmd_refund(args) -> None:
    await db.init_db()
    order = await db.get_order(args.id)
    if not order:
        fail(f"Заказа #{args.id} нет")
    if not order["charge_id"]:
        fail("По заказу нет онлайн-платежа — возврат делается вручную")
    if order["currency"] != "XTR":
        fail("Автовозврат есть только для Telegram Stars; платежи провайдера "
             "возвращаются в его личном кабинете")

    async with telegram() as bot:
        await bot.refund_star_payment(user_id=order["user_id"],
                                      telegram_payment_charge_id=order["charge_id"])
        await db.set_status(args.id, "cancelled")
        await notify(bot, order["user_id"], f"Оплата по заказу #{args.id} возвращена ⭐")
    done(f"Звёзды по заказу #{args.id} возвращены")


async def cmd_users(args) -> None:
    await db.init_db()
    async with db.db() as conn:
        rows = await (await conn.execute(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT ?", (args.limit,))).fetchall()
    title(f"Пользователи ({len(rows)})")
    table(["tg_id", "username", "имя", "первый запуск"],
          [[r["tg_id"], f"@{r['username']}" if r["username"] else "—",
            short(r["full_name"], 24), r["created_at"][:10]] for r in rows])


async def cmd_stats(args) -> None:
    await db.init_db()
    stats = await db.get_stats()
    async with db.db() as conn:
        by_status = await (await conn.execute(
            "SELECT status, COUNT(*) c, SUM(total) s FROM orders GROUP BY status")).fetchall()
        top = await (await conn.execute(
            """SELECT title, SUM(quantity) q, SUM(price * quantity) s
               FROM order_items GROUP BY title ORDER BY s DESC LIMIT 5""")).fetchall()

    title("Итого")
    table(["пользователей", "товаров", "заказов", "оборот"],
          [[stats["users"], stats["products"], stats["orders"], money(stats["revenue"])]])
    title("По статусам")
    table(["статус", "заказов", "сумма"],
          [[STATUSES.get(r["status"], r["status"]), r["c"], money(r["s"] or 0)]
           for r in by_status])
    title("Топ товаров")
    table(["товар", "продано", "сумма"],
          [[short(r["title"], 34), r["q"], money(r["s"])] for r in top])


async def cmd_broadcast(args) -> None:
    await db.init_db()
    user_ids = await db.all_user_ids()
    print(f"Получателей: {len(user_ids)}")
    print(paint("─" * 40, "grey"))
    print(args.text)
    print(paint("─" * 40, "grey"))

    if args.dry_run:
        print(paint("Пробный прогон: ничего не отправлено (уберите --dry-run)", "yellow"))
        return
    if sys.stdin.isatty() and input("Отправить? [y/N] ").strip().lower() not in {"y", "д"}:
        print("Отменено.")
        return

    sent = failed = 0
    async with telegram() as bot:
        for user_id in user_ids:
            try:
                await bot.send_message(user_id, args.text)
                sent += 1
            except Exception:  # noqa: BLE001 — заблокировал бота, удалил аккаунт
                failed += 1
            await asyncio.sleep(0.05)  # лимит Telegram ~30 сообщений/сек
    done(f"Доставлено: {sent}, ошибок: {failed}")


async def cmd_backup(args) -> None:
    import sqlite3
    os.makedirs(args.dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = os.path.join(args.dir, f"shop-{stamp}.db")
    source = sqlite3.connect(settings.db_path)
    try:
        with sqlite3.connect(target) as copy:
            source.backup(copy)      # горячий бэкап, бота останавливать не нужно
    finally:
        source.close()
    size = os.path.getsize(target) / 1024
    done(f"{target} ({size:.0f} КБ)")


def cmd_run(args) -> None:
    import bot as bot_module
    asyncio.run(bot_module.main())


async def cmd_stars(args) -> None:
    await db.init_db()

    if args.action == "price":
        title("Прайс")
        rate = await _ton_rate_or_none()
        rows = []
        for quantity in (settings.star_packages or [settings.min_stars]):
            price = quantity * settings.star_price
            rows.append([f"{quantity} ⭐", money(price),
                         f"{__import__('ton').to_ton(price, rate)} TON" if rate else "—"])
        table(["набор", "цена", "в TON"], rows)
        print(paint(f"\n  {money(settings.star_price)} за ⭐ · минимум "
                    f"{settings.min_stars} ⭐", "grey"))
        return

    if args.action == "rate":
        import ton
        try:
            rate = await ton.rate_rub(force=True)
        except Exception as e:  # noqa: BLE001
            fail(f"Курс TON недоступен: {e}")
        source = "из .env" if settings.ton_rate_rub else "из API"
        done(f"1 TON = {money(rate)} ({source})")
        return

    if args.action == "balance":
        import fragment
        client = fragment.get_client()
        if client.mode == "manual":
            fail("Шлюз не подключён: FRAGMENT_MODE=manual. Баланс смотрите на fragment.com")
        balance = await client.balance()
        if balance is None:
            fail("Шлюз не ответил на запрос баланса")
        done(f"Баланс шлюза: {balance}")
        return

    if args.action == "pending":
        waiting = await db.undelivered_star_orders()
        title(f"Оплачено, но не выдано ({len(waiting)})")
        table(["id", "звёзд", "получатель", "сумма", "попыток", "ошибка"],
              [[o["id"], o["stars_qty"], f"@{o['recipient']}", money(o["total"]),
                o["attempts"], short(o["fragment_error"], 40)] for o in waiting])
        return

    if args.action == "check":
        import ton
        if not settings.ton_enabled:
            fail("TON_WALLET не задан — проверять нечего")
        async with telegram() as bot:
            confirmed = await ton.check_pending(bot)
        done(f"Подтверждено оплат: {confirmed}")
        return

    if args.action == "fulfil":
        import stars as stars_module
        order = await db.get_order(args.id)
        if not order:
            fail(f"Заказа #{args.id} нет")
        if not order["stars_qty"]:
            fail(f"Заказ #{args.id} — не про звёзды")
        if order["delivered_at"]:
            fail(f"Заказ #{args.id} уже выдан ({order['delivered_at']})")

        async with telegram() as bot:
            if args.manual:
                if await stars_module.deliver_manually(bot, args.id, args.ref):
                    done(f"Заказ #{args.id} закрыт: {order['stars_qty']} ⭐ "
                         f"на @{order['recipient']}")
                else:
                    fail("Заказ уже закрыт")
                return
            result = await stars_module.fulfil(bot, args.id)
        if result.ok:
            done(f"Заказ #{args.id}: {result}")
        else:
            fail(f"Заказ #{args.id}: {result}")


async def _ton_rate_or_none() -> float | None:
    import ton
    try:
        return await ton.rate_rub()
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------- Telegram

class telegram:
    """Бот с закрытием сессии: async with telegram() as bot."""

    async def __aenter__(self):
        if not settings.bot_token:
            fail("BOT_TOKEN не задан — команда обращается к Telegram")
        from bot import create_bot
        self.bot = create_bot()
        return self.bot

    async def __aexit__(self, *exc_info) -> None:
        await self.bot.session.close()


async def notify(bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id, text)
    except Exception as e:  # noqa: BLE001
        print(paint(f"  Покупателю сообщить не вышло: {e}", "yellow"))


# --------------------------------------------------------------------- разбор

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manage.py", description="Управление Telegram-магазином из терминала",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Примеры:\n"
               "  python manage.py status\n"
               "  python manage.py catalog\n"
               "  python manage.py product content 3 \"https://example.com/course\"\n"
               "  python manage.py orders --status new\n"
               "  python manage.py order status 12 paid\n"
               "  python manage.py stars pending\n"
               "  python manage.py stars fulfil 12 --manual\n"
               "  python manage.py broadcast \"Новый курс уже в каталоге\" --dry-run\n")
    sub = parser.add_subparsers(dest="command", required=True, metavar="команда")

    # --- сервис
    status = sub.add_parser("status", help="состояние бота, сервиса и базы")
    status.set_defaults(func=cmd_status)

    check = sub.add_parser("check", help="полная диагностика, в том числе связь с Telegram")
    check.add_argument("--offline", action="store_true", help="не обращаться к Telegram")
    check.set_defaults(func=cmd_check)

    run = sub.add_parser("run", help="запустить бота в этом терминале")
    run.set_defaults(func=cmd_run, sync=True)

    for action, help_text in (("start", "запустить сервис"), ("stop", "остановить сервис"),
                              ("restart", "перезапустить сервис")):
        service = sub.add_parser(action, help=help_text)
        service.add_argument("--service", choices=["auto", "systemd", "docker"], default="auto")
        service.set_defaults(func=lambda a, act=action: run_service(act, a), sync=True)

    logs = sub.add_parser("logs", help="логи сервиса")
    logs.add_argument("-n", "--lines", type=int, default=80)
    logs.add_argument("-f", "--follow", action="store_true", help="следить в реальном времени")
    logs.add_argument("--service", choices=["auto", "systemd", "docker"], default="auto")
    logs.set_defaults(func=lambda a: run_service("logs", a), sync=True)

    # --- каталог
    catalog = sub.add_parser("catalog", help="категории и товары")
    catalog.set_defaults(func=cmd_catalog)

    category = sub.add_parser("category", help="категории: add, rm")
    category.add_argument("action", choices=["add", "rm"])
    category.add_argument("value", help="название для add, id для rm")
    category.set_defaults(func=cmd_category)

    product = sub.add_parser("product", help="товары: add, show, content, toggle, rm")
    product_sub = product.add_subparsers(dest="action", required=True, metavar="действие")

    add = product_sub.add_parser("add", help="добавить товар")
    add.add_argument("--cat", type=int, required=True, help="id категории")
    add.add_argument("--title", required=True)
    add.add_argument("--price", type=float, required=True)
    add.add_argument("--desc", default="")
    add.add_argument("--content", help="что выдать после оплаты (цифровой товар)")
    add.add_argument("--stock", type=int, default=999)
    add.set_defaults(func=cmd_product, action="add")

    for name, help_text in (("show", "карточка товара"), ("toggle", "скрыть или показать"),
                            ("rm", "удалить")):
        item = product_sub.add_parser(name, help=help_text)
        item.add_argument("id", type=int)
        item.set_defaults(func=cmd_product, action=name)

    content = product_sub.add_parser("content", help="что выдавать после оплаты")
    content.add_argument("id", type=int)
    content.add_argument("value", help="ссылка, ключ или инструкция")
    content.set_defaults(func=cmd_product, action="content")

    # --- заказы
    orders = sub.add_parser("orders", help="список заказов")
    orders.add_argument("--status", choices=list(STATUSES))
    orders.add_argument("--limit", type=int, default=20)
    orders.set_defaults(func=cmd_orders)

    order = sub.add_parser("order", help="заказ: show, status")
    order_sub = order.add_subparsers(dest="action", required=True, metavar="действие")
    order_show = order_sub.add_parser("show", help="карточка заказа")
    order_show.add_argument("id", type=int)
    order_show.set_defaults(func=cmd_order)
    order_status = order_sub.add_parser("status", help="сменить статус и уведомить клиента")
    order_status.add_argument("id", type=int)
    order_status.add_argument("status", choices=list(MANUAL_STATUSES))
    order_status.set_defaults(func=cmd_status_set)

    deliver = sub.add_parser("deliver", help="выдать цифровой товар по заказу")
    deliver.add_argument("id", type=int)
    deliver.set_defaults(func=cmd_deliver)

    refund = sub.add_parser("refund", help="вернуть оплату звёздами")
    refund.add_argument("id", type=int)
    refund.set_defaults(func=cmd_refund)

    # --- звёзды
    stars_cmd = sub.add_parser(
        "stars", help="звёзды: price, rate, balance, pending, check, fulfil")
    stars_sub = stars_cmd.add_subparsers(dest="action", required=True, metavar="действие")
    for name, help_text in (("price", "прайс по наборам"),
                            ("rate", "текущий курс TON"),
                            ("balance", "баланс шлюза Fragment"),
                            ("pending", "оплачено, но не выдано"),
                            ("check", "разово проверить входящие переводы")):
        item = stars_sub.add_parser(name, help=help_text)
        item.set_defaults(func=cmd_stars, action=name)

    fulfil = stars_sub.add_parser("fulfil", help="выдать звёзды по заказу")
    fulfil.add_argument("id", type=int)
    fulfil.add_argument("--manual", action="store_true",
                        help="звёзды куплены вручную — просто закрыть заказ")
    fulfil.add_argument("--ref", help="номер операции для истории")
    fulfil.set_defaults(func=cmd_stars, action="fulfil")

    # --- прочее
    users = sub.add_parser("users", help="кто пользуется ботом")
    users.add_argument("--limit", type=int, default=30)
    users.set_defaults(func=cmd_users)

    stats = sub.add_parser("stats", help="продажи и топ товаров")
    stats.set_defaults(func=cmd_stats)

    broadcast = sub.add_parser("broadcast", help="рассылка всем пользователям")
    broadcast.add_argument("text", help="текст, поддерживается HTML-разметка")
    broadcast.add_argument("--dry-run", action="store_true", help="показать, но не отправлять")
    broadcast.set_defaults(func=cmd_broadcast)

    backup = sub.add_parser("backup", help="копия базы без остановки бота")
    backup.add_argument("--dir", default="backups")
    backup.set_defaults(func=cmd_backup)

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        if getattr(args, "sync", False):
            args.func(args)
        else:
            asyncio.run(args.func(args))
    except KeyboardInterrupt:
        print("\nПрервано.")


if __name__ == "__main__":
    main()
