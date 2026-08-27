"""Самопроверка: готов ли бот к работе на сервере.

    python doctor.py            полная проверка (в том числе связь с Telegram)
    python doctor.py --offline  без обращения к api.telegram.org
    python doctor.py --health   короткая проверка для HEALTHCHECK/мониторинга

Код возврата 0 — всё в порядке, 1 — есть блокирующая проблема.
"""

import asyncio
import sys

from config import settings

OK, WARN, FAIL = "✅", "⚠️ ", "❌"


def line(mark: str, text: str) -> None:
    print(f"{mark} {text}")


async def check_config() -> bool:
    print("\n— Настройки —")
    problems = settings.validate()
    blocking = [p for p in problems if "ADMIN_IDS" not in p]
    for problem in problems:
        line(FAIL if problem in blocking else WARN, problem)
    if not problems:
        line(OK, "Файл .env заполнен корректно")
    kind = {"stars": "продажа звёзд", "digital": "цифровой товар",
            "physical": "физический товар"}.get(settings.shop_mode, settings.shop_mode)
    line(OK, f"Магазин: {settings.shop_name} · {kind} · валюта {settings.currency} · "
             f"режим {settings.mode}")
    line(OK, f"Админы: {', '.join(map(str, settings.admin_ids)) or 'нет'}")
    return not blocking


async def check_database() -> bool:
    print("\n— База данных —")
    try:
        from database import db, get_stats, init_db
        await init_db()
        async with db() as conn:
            rows = await (await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
        tables = sorted(r["name"] for r in rows)
        stats = await get_stats()
    except Exception as e:  # noqa: BLE001
        line(FAIL, f"База недоступна ({settings.db_path}): {e}")
        return False
    line(OK, f"{settings.db_path}: таблиц {len(tables)} ({', '.join(tables)})")
    line(OK, f"Пользователей: {stats['users']} · товаров: {stats['products']} · "
             f"заказов: {stats['orders']}")
    return True


async def check_telegram() -> bool:
    print("\n— Связь с Telegram —")
    if not settings.bot_token:
        line(FAIL, "Нет BOT_TOKEN — проверить связь невозможно")
        return False

    from aiogram.exceptions import TelegramAPIError

    from bot import create_bot

    if settings.proxy:
        line(OK, f"Через прокси: {settings.proxy.split('@')[-1]}")
    bot = create_bot()
    try:
        me = await bot.get_me()
        line(OK, f"Бот @{me.username} ({me.full_name}), id {me.id}")

        info = await bot.get_webhook_info()
        if settings.mode == "webhook":
            if info.url == settings.webhook_url:
                line(OK, f"Webhook установлен: {info.url}")
            else:
                line(WARN, f"Сейчас webhook: {info.url or 'не установлен'}; "
                           f"в .env: {settings.webhook_url}. Он поставится при старте бота.")
        elif info.url:
            line(WARN, f"Режим polling, но остался webhook {info.url} — "
                       f"бот снимет его при запуске")
        else:
            line(OK, "Webhook не установлен — верно для polling")

        if info.pending_update_count:
            line(WARN, f"Необработанных апдейтов: {info.pending_update_count}")
        if info.last_error_message:
            line(WARN, f"Последняя ошибка доставки: {info.last_error_message}")
        return True
    except TelegramAPIError as e:
        line(FAIL, f"Telegram отклонил запрос: {e}")
        return False
    except Exception as e:  # noqa: BLE001 — сеть, DNS, прокси
        line(FAIL, f"Нет связи с api.telegram.org: {e}")
        return False
    finally:
        await bot.session.close()


async def check_stars_shop() -> bool:
    """Проверки, которые важны только магазину звёзд."""
    print("\n— Продажа звёзд —")
    line(OK, f"Цена: {settings.star_price} {settings.currency} за ⭐ · "
             f"минимум {settings.min_stars} ⭐")
    packages = ", ".join(str(x) for x in settings.star_packages)
    line(OK, f"Наборы: {packages or 'только своё количество'}")

    ok = True

    # --- приём оплаты
    if settings.ton_enabled:
        import ton
        if not ton.parse_address(settings.ton_wallet):
            line(FAIL, f"TON_WALLET не проходит проверку контрольной суммы: "
                       f"{settings.ton_wallet}")
            return False
        line(OK, f"Кошелёк: {settings.ton_wallet}")
        line(OK, f"Адрес: {ton.describe_address(settings.ton_wallet)}")
        if not settings.ton_rate_rub:
            line(OK, f"Источников курса: {len(ton.rate_sources())}")
        try:
            rate = await ton.rate_rub()
            source = "из .env" if settings.ton_rate_rub else "из API"
            line(OK, f"Курс: 1 TON = {rate} {settings.currency} ({source})")
            example = settings.min_stars * settings.star_price
            line(OK, f"Минимальный заказ: {settings.min_stars} ⭐ = {example} "
                     f"{settings.currency} = {ton.to_ton(example, rate)} TON")
        except Exception as e:  # noqa: BLE001
            line(FAIL, str(e))
            ok = False
    elif settings.payment_token:
        line(WARN, "TON не настроен, оплата пойдёт через платёжного провайдера")
    else:
        line(FAIL, "Принимать оплату нечем: нет ни TON_WALLET, ни токена провайдера")
        ok = False

    # --- закупка звёзд
    if settings.fragment_auto:
        line(OK, f"Закупка: шлюз {settings.fragment_url}")
        import fragment
        balance = await fragment.get_client().balance()
        if balance is None:
            line(WARN, "Шлюз не ответил на запрос баланса — проверьте адрес и токен")
        else:
            line(OK, f"Баланс шлюза: {balance}")
            if settings.fragment_min_balance and balance < settings.fragment_min_balance:
                line(WARN, f"Баланс ниже порога {settings.fragment_min_balance}")
    else:
        line(WARN, "Закупка вручную: бот пришлёт задачу админу, покупка на fragment.com. "
                   "Автозакупка — FRAGMENT_MODE=api")

    waiting = []
    try:
        waiting = await __import__("database").undelivered_star_orders()
    except Exception:  # noqa: BLE001 — база проверяется отдельно
        pass
    if waiting:
        line(WARN, f"Оплачено, но не выдано: {len(waiting)} заказ(ов). "
                   f"Список: python manage.py stars pending")
    return ok


async def check_payments() -> bool:
    if settings.stars_shop:
        return await check_stars_shop()

    print("\n— Оплата —")
    line(OK, "Всегда доступны: при получении, перевод на карту")
    if settings.pay_in_stars:
        line(OK, f"Онлайн: Telegram Stars (XTR), курс {settings.stars_rate} "
                 f"{settings.currency} за ⭐ — провайдер и договор не нужны")
    elif settings.payment_token:
        provider = settings.payment_token.split(":")[0]
        test = ":TEST:" in settings.payment_token
        line(OK, f"Онлайн: провайдер {provider}, валюта {settings.payment_currency}"
                 f"{' (ТЕСТОВЫЙ токен)' if test else ''}")
    else:
        line(WARN, "Онлайн-оплата выключена: нет PAYMENT_PROVIDER_TOKEN и не выбран XTR")
    return True


async def health() -> int:
    """Короткая проверка для HEALTHCHECK: база жива, webhook-порт отвечает."""
    try:
        from database import db
        async with db() as conn:
            await conn.execute("SELECT 1")
    except Exception as e:  # noqa: BLE001
        print(f"db: {e}")
        return 1

    if settings.mode == "webhook":
        try:
            import aiohttp
            url = f"http://127.0.0.1:{settings.port}/healthz"
            async with aiohttp.ClientSession() as http:
                async with http.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        print(f"healthz: HTTP {resp.status}")
                        return 1
        except Exception as e:  # noqa: BLE001
            print(f"healthz: {e}")
            return 1
    print("ok")
    return 0


async def main() -> int:
    if "--health" in sys.argv:
        return await health()

    print("🩺 Проверка бота")
    results = [await check_config(), await check_database()]
    if "--offline" not in sys.argv:
        results.append(await check_telegram())
    else:
        print("\n— Связь с Telegram —")
        line(WARN, "Пропущено (--offline)")
    results.append(await check_payments())

    ok = all(results)
    print("\n" + ("✅ Бот готов к запуску: python bot.py"
                  if ok else "❌ Есть блокирующие проблемы — см. выше"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
