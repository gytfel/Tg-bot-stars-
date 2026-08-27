"""Настройки, форматирование и обработчик ошибок."""

from dataclasses import replace
from datetime import datetime

import pytest
from aiogram.types import Chat, ErrorEvent, Message, Update

from config import Settings

VALID_WALLET = "UQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAJKZ"
TESTNET_WALLET = "0QAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACkT"
from utils import escape, money, to_stars


def _settings(**kwargs) -> Settings:
    """Рабочая конфигурация магазина звёзд — от неё пляшут остальные проверки."""
    base = Settings(bot_token="123:ABC", admin_ids=[1], mode="polling",
                    shop_mode="stars", payment_currency="RUB",
                    ton_wallet=VALID_WALLET, ton_rate_rub=300)
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


def test_pay_in_stars_detected_by_currency():
    assert _settings(payment_currency="XTR").pay_in_stars is True
    assert _settings(payment_currency="XTR").online_enabled is True
    assert _settings(payment_currency="RUB").online_enabled is False
    assert _settings(payment_currency="RUB", payment_token="t").online_enabled is True


def test_pay_in_stars_warns_about_useless_provider_token():
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


# ------------------------------------------------------- магазин звёзд

def test_stars_shop_needs_a_way_to_get_paid():
    problems = _settings(ton_wallet="", payment_token="").validate()
    assert any("Принимать оплату нечем" in p for p in problems)


def test_paying_for_stars_with_stars_is_rejected():
    problems = _settings(payment_currency="XTR").validate()
    assert any("платить за них звёздами нельзя" in p for p in problems)


def test_minimum_below_fragment_limit_is_rejected():
    problems = _settings(min_stars=10, star_packages=[10, 50]).validate()
    assert any("Fragment не продаёт меньше 50" in p for p in problems)


def test_packages_below_minimum_are_reported():
    problems = _settings(min_stars=50, star_packages=[25, 100]).validate()
    assert any("STAR_PACKAGES" in p for p in problems)


def test_fragment_api_mode_requires_credentials():
    problems = _settings(fragment_mode="api").validate()
    assert any("FRAGMENT_API_URL" in p for p in problems)
    assert _settings(fragment_mode="api", fragment_url="https://gate",
                     fragment_token="t").validate() == []


def test_fragment_auto_flag():
    assert _settings().fragment_auto is False
    assert _settings(fragment_mode="api", fragment_url="https://gate",
                     fragment_token="t").fragment_auto is True


def test_physical_shop_cannot_use_stars_as_payment():
    problems = _settings(shop_mode="physical", payment_currency="XTR",
                         payment_token="").validate()
    assert any("физических товаров" in p for p in problems)


def test_delivery_form_only_for_physical():
    assert _settings(shop_mode="stars").digital is True
    assert _settings(shop_mode="digital").digital is True
    assert _settings(shop_mode="physical").digital is False


def test_broken_wallet_is_reported():
    problems = _settings(ton_wallet=VALID_WALLET[:-1] + "X").validate()
    assert any("контрольной суммы" in p for p in problems)


def test_testnet_wallet_is_reported():
    problems = _settings(ton_wallet=TESTNET_WALLET).validate()
    assert any("тестовой сети" in p for p in problems)


def test_valid_wallet_passes():
    assert _settings(ton_wallet=VALID_WALLET).validate() == []
