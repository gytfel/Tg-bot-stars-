"""Тестовый стенд: поддельная сессия Telegram вместо реального API.

Позволяет прогонять настоящие апдейты через настоящий Dispatcher,
не обращаясь к api.telegram.org и не имея боевого токена.
"""

import os
from datetime import datetime
from typing import Any, Union, get_args, get_origin

import pytest

os.environ.setdefault("BOT_TOKEN", "42:TEST")
os.environ.setdefault("ADMIN_IDS", "1000")
os.environ.setdefault("SHOP_NAME", "Тест-магазин")
os.environ.setdefault("CURRENCY", "₽")

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.methods import TelegramMethod  # noqa: E402
from aiogram.types import (CallbackQuery, Chat, Message, Update, User,  # noqa: E402
                           SuccessfulPayment)

ADMIN_ID = 1000
USER_ID = 2000


class FakeSession(BaseSession):
    """Записывает вызовы API и возвращает правдоподобные ответы."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod] = []
        self._msg_id = 100

    async def close(self) -> None:
        pass

    async def stream_content(self, *args: Any, **kwargs: Any):  # pragma: no cover
        yield b""

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        self.calls.append(method)
        return self._result_for(bot, method)

    # ---------------------------------------------------------------- helpers

    def _result_for(self, bot: Bot, method: TelegramMethod):
        returning = getattr(type(method), "__returning__", bool)
        if get_origin(returning) is Union:
            args = [a for a in get_args(returning) if a is not type(None)]
            returning = Message if Message in args else args[0]

        if returning is Message:
            self._msg_id += 1
            chat_id = getattr(method, "chat_id", None) or USER_ID
            return Message(
                message_id=self._msg_id,
                date=datetime.now(),
                chat=Chat(id=int(chat_id), type="private"),
                text=getattr(method, "text", None) or getattr(method, "caption", None),
            ).as_(bot)
        if returning is User:
            return User(id=1, is_bot=True, first_name="TestBot", username="test_bot")
        return True

    # --------------------------------------------------------------- запросы

    def named(self, name: str) -> list[TelegramMethod]:
        return [c for c in self.calls if type(c).__name__ == name]

    def texts(self) -> list[str]:
        out = []
        for c in self.calls:
            for attr in ("text", "caption"):
                value = getattr(c, attr, None)
                if isinstance(value, str):
                    out.append(value)
        return out

    def last_text(self) -> str:
        texts = self.texts()
        return texts[-1] if texts else ""

    def alerts(self) -> list[str]:
        return [c.text for c in self.named("AnswerCallbackQuery") if getattr(c, "text", None)]

    def clear(self) -> None:
        self.calls.clear()


@pytest.fixture
def db_file(tmp_path, monkeypatch):
    from config import settings
    path = tmp_path / "test_shop.db"
    monkeypatch.setattr(settings, "db_path", str(path))
    return str(path)


@pytest.fixture
async def bot() -> Bot:
    return Bot("42:TEST", session=FakeSession(),
               default=DefaultBotProperties(parse_mode=ParseMode.HTML))


@pytest.fixture
async def session(bot: Bot) -> FakeSession:
    return bot.session


@pytest.fixture
async def dp(db_file, monkeypatch) -> Dispatcher:
    import bot as bot_module
    import handlers_admin
    import handlers_stars
    import handlers_user
    from database import init_db

    await init_db()
    # роутеры — модульные синглтоны: отвязываем от диспетчера прошлого теста
    for router in (handlers_admin.router, handlers_stars.router, handlers_user.router):
        router._parent_router = None

    # ловим падения хендлеров: тест не должен «зеленеть» на съеденном исключении
    caught: list[BaseException] = []

    async def recording_error(event) -> bool:
        caught.append(event.exception)
        return True

    monkeypatch.setattr(bot_module, "on_error", recording_error)
    dispatcher = bot_module.create_dispatcher()
    yield dispatcher
    assert not caught, f"хендлеры упали с ошибками: {caught!r}"


# ------------------------------------------------------------------ фабрики

_update_id = [0]
_message_id = [1]


def _next(counter: list[int]) -> int:
    counter[0] += 1
    return counter[0]


def make_user(user_id: int = USER_ID, name: str = "Иван Тестов") -> User:
    first, _, last = name.partition(" ")
    return User(id=user_id, is_bot=False, first_name=first, last_name=last or None,
                username=f"user{user_id}")


def text_update(text: str, user_id: int = USER_ID, **kwargs) -> Update:
    user = make_user(user_id)
    message = Message(
        message_id=_next(_message_id),
        date=datetime.now(),
        chat=Chat(id=user_id, type="private"),
        from_user=user,
        text=text,
        **kwargs,
    )
    return Update(update_id=_next(_update_id), message=message)


def payment_update(amount: int, currency: str = "RUB", user_id: int = USER_ID,
                   charge_id: str = "charge_1", payload: str = "order_1") -> Update:
    user = make_user(user_id)
    message = Message(
        message_id=_next(_message_id),
        date=datetime.now(),
        chat=Chat(id=user_id, type="private"),
        from_user=user,
        successful_payment=SuccessfulPayment(
            currency=currency,
            total_amount=amount,
            invoice_payload=payload,
            telegram_payment_charge_id=charge_id,
            provider_payment_charge_id="provider_1",
        ),
    )
    return Update(update_id=_next(_update_id), message=message)


def callback_update(data: str, user_id: int = USER_ID, with_photo: bool = False) -> Update:
    user = make_user(user_id)
    message = Message(
        message_id=_next(_message_id),
        date=datetime.now(),
        chat=Chat(id=user_id, type="private"),
        from_user=User(id=1, is_bot=True, first_name="TestBot"),
        text=None if with_photo else "предыдущее сообщение",
    )
    callback = CallbackQuery(
        id=str(_next(_update_id)),
        from_user=user,
        chat_instance="chat-instance",
        message=message,
        data=data,
    )
    return Update(update_id=_next(_update_id), callback_query=callback)
