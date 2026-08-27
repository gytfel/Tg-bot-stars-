"""Настройки, форматирование и обработчик ошибок."""

from dataclasses import replace
from datetime import datetime

import pytest
from aiogram.types import Chat, ErrorEvent, Message, Update

from config import Settings
from utils import escape, money, to_stars


def _settings(**kwargs) -> Settings:
    base = Settings(bot_token="123:ABC", admin_ids=[1], mode="polling")
    return replace(base, **kwargs)


def test_valid_config_has_no_problems():
    assert _settings().validate() == []


def test_missing_token_is_reported():
    assert any("BOT_TOKEN" in p for p in _settings(bot_token="").validate())


def test_webhook_requires_https_url():
    assert any("WEBHOOK_URL" in p for p in _settings(mode="webhook").validate())
    assert any("https" in p for p in
               _settings(mode="webhook", webhook_base="http://shop.ru").validate())
    assert _settings(mode="webhook", webhook_base="https://shop.ru").validate() == []


def test_webhook_url_is_built_from_base_and_path():
    s = _settings(mode="webhook", webhook_base="https://shop.ru", webhook_path="/tg")
    assert s.webhook_url == "https://shop.ru/tg"


def test_stars_mode_detected_by_currency():
    assert _settings(payment_currency="XTR").stars_mode is True
    assert _settings(payment_currency="XTR").online_enabled is True
    assert _settings(payment_currency="RUB").online_enabled is False
    assert _settings(payment_currency="RUB", payment_token="t").online_enabled is True


def test_stars_mode_warns_about_useless_provider_token():
    problems = _settings(payment_currency="XTR", payment_token="t").validate()
    assert any("Stars" in p for p in problems)


def test_unknown_mode_is_reported():
    assert any("BOT_MODE" in p for p in _settings(mode="webhoook").validate())


@pytest.mark.parametrize("value,expected", [
    (1500, "1 500 ₽"), (199.5, "199.50 ₽"), (0, "0 ₽"), (1234567, "1 234 567 ₽"),
])
def test_money_formatting(value, expected):
    assert money(value) == expected


def test_stars_conversion_rounds_up_from_zero():
    from config import settings
    assert to_stars(0.5) >= 1
    assert to_stars(890) == round(890 / settings.stars_rate)


def test_escape_protects_html():
    assert escape("<b>hi</b> & <i>") == "&lt;b&gt;hi&lt;/b&gt; &amp; &lt;i&gt;"
    assert escape(None) == ""


async def test_error_handler_answers_user(bot, session):
    from bot import on_error

    message = Message(message_id=1, date=datetime.now(),
                      chat=Chat(id=2000, type="private"), text="/start").as_(bot)
    event = ErrorEvent(update=Update(update_id=1, message=message),
                       exception=RuntimeError("бум"))

    assert await on_error(event) is True
    assert "не так" in session.last_text()


def test_proxy_is_used_when_configured(monkeypatch):
    import bot as bot_module
    from config import settings

    monkeypatch.setattr(settings, "proxy", "http://127.0.0.1:3128")
    created = bot_module.create_bot()
    assert created.session.proxy == "http://127.0.0.1:3128"


def test_missing_proxy_dependency_explains_itself(monkeypatch):
    import bot as bot_module
    from config import settings

    def boom(*args, **kwargs):
        raise RuntimeError("install aiohttp-socks")

    monkeypatch.setattr(settings, "proxy", "socks5://127.0.0.1:9050")
    monkeypatch.setattr(bot_module, "AiohttpSession", boom)
    with pytest.raises(SystemExit, match="aiohttp-socks"):
        bot_module.create_bot()
