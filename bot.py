"""Точка входа.

Локально:            python bot.py            (режим polling)
На сервере:          BOT_MODE=webhook python bot.py
Проверка настроек:   python doctor.py
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, ErrorEvent

import handlers_admin
import handlers_user
from config import settings
from database import init_db

log = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="catalog", description="Каталог товаров"),
    BotCommand(command="cart", description="Корзина"),
    BotCommand(command="orders", description="Мои заказы"),
    BotCommand(command="help", description="О магазине"),
]


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )


def create_bot() -> Bot:
    session = None
    if settings.proxy:
        try:
            session = AiohttpSession(proxy=settings.proxy)
        except RuntimeError as e:  # aiogram просит доп. пакет для прокси
            raise SystemExit(f"TELEGRAM_PROXY задан, но прокси не поднимается: {e}\n"
                             "Установите зависимость: pip install aiohttp-socks") from e
    return Bot(settings.bot_token, session=session,
               default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def create_dispatcher() -> Dispatcher:
    """Собрать диспетчер со всеми роутерами. Используется и ботом, и тестами."""
    dp = Dispatcher(storage=MemoryStorage())
    # админский роутер идёт первым — у него приоритет
    dp.include_router(handlers_admin.router)
    dp.include_router(handlers_user.router)
    dp.errors.register(on_error)
    return dp


async def on_error(event: ErrorEvent) -> bool:
    """Любая необработанная ошибка: пишем в лог и не бросаем клиента молча."""
    log.exception("Ошибка при обработке апдейта: %s", event.exception)
    update = event.update
    message = update.message or (update.callback_query.message
                                 if update.callback_query else None)
    if message:
        try:
            await message.answer("Что-то пошло не так 😔 Попробуйте ещё раз "
                                 "или нажмите /start.")
        except Exception:  # noqa: BLE001 — сообщить не вышло, лог уже есть
            pass
    return True


async def on_startup(bot: Bot) -> None:
    await init_db()
    await bot.set_my_commands(COMMANDS)
    me = await bot.get_me()
    log.info("Бот @%s запущен в режиме %s", me.username, settings.mode)


async def run_polling(bot: Bot, dp: Dispatcher) -> None:
    await on_startup(bot)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


def build_app(bot: Bot, dp: Dispatcher):
    """aiohttp-приложение: приём апдейтов от Telegram + /healthz для мониторинга."""
    from aiohttp import web
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

    app = web.Application()
    app.router.add_get("/healthz", health)
    SimpleRequestHandler(
        dispatcher=dp, bot=bot,
        secret_token=settings.webhook_secret or None,
    ).register(app, path=settings.webhook_path)
    setup_application(app, dp, bot=bot)
    return app


async def run_webhook(bot: Bot, dp: Dispatcher) -> None:
    """HTTP-сервер для Telegram. Ставится за nginx/Caddy с валидным TLS."""
    from aiohttp import web

    await on_startup(bot)
    await bot.set_webhook(
        settings.webhook_url,
        secret_token=settings.webhook_secret or None,
        drop_pending_updates=True,
        allowed_updates=dp.resolve_used_update_types(),
    )
    log.info("Webhook установлен: %s", settings.webhook_url)

    app = build_app(bot, dp)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=settings.host, port=settings.port)
    await site.start()
    log.info("Слушаю %s:%s (healthcheck: /healthz)", settings.host, settings.port)
    try:
        await asyncio.Event().wait()          # работаем, пока не остановят
    finally:
        await runner.cleanup()


async def health(request):
    from aiohttp import web
    return web.json_response({"status": "ok", "mode": settings.mode})


async def main() -> None:
    setup_logging()

    problems = settings.validate()
    fatal = [p for p in problems if "ADMIN_IDS" not in p]
    for problem in problems:
        log.warning("Конфигурация: %s", problem)
    if fatal:
        raise SystemExit("Проверьте .env — подробности выше. Помощник: python doctor.py")

    bot = create_bot()
    dp = create_dispatcher()
    try:
        if settings.mode == "webhook":
            await run_webhook(bot, dp)
        else:
            await run_polling(bot, dp)
    except TelegramUnauthorizedError:
        raise SystemExit("Telegram отклонил токен. Проверьте BOT_TOKEN в .env "
                         "(получить заново: @BotFather → /mybots → API Token).")
    except TelegramNetworkError as e:
        raise SystemExit(f"Нет связи с api.telegram.org: {e}\n"
                         "Проверьте интернет на сервере, DNS и firewall "
                         "(нужен исходящий HTTPS/443).")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as e:
        logging.info("Бот остановлен%s", f": {e}" if str(e) else "")
