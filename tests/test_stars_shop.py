"""Продажа звёзд: количество, получатель, счёт в TON, зачисление."""

import pytest

import database as db
import fragment
import stars
import ton
from conftest import ADMIN_ID, USER_ID, callback_update, text_update


@pytest.fixture(autouse=True)
def stars_shop(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "shop_mode", "stars")
    monkeypatch.setattr(settings, "payment_currency", "RUB")
    monkeypatch.setattr(settings, "star_price", 1.6)
    monkeypatch.setattr(settings, "min_stars", 50)
    monkeypatch.setattr(settings, "ton_wallet", "UQtest_wallet")
    monkeypatch.setattr(settings, "ton_rate_rub", 320.0)
    return settings


@pytest.fixture
def paid_transactions(monkeypatch):
    """Кошелёк, в который «падают» переводы, добавленные тестом."""
    inbox: list[dict] = []

    async def fake_incoming(limit: int = 100):
        return list(inbox)

    monkeypatch.setattr(ton, "incoming", fake_incoming)
    return inbox


@pytest.fixture
def auto_fragment(monkeypatch):
    """Шлюз, который всегда успешно продаёт."""
    calls = []

    class Stub:
        mode = "api"

        async def buy_stars(self, username, quantity, reference):
            calls.append({"username": username, "quantity": quantity,
                          "reference": reference})
            return fragment.Purchase(ok=True, reference="FRG-1")

        async def balance(self):
            return 1234.0

    monkeypatch.setattr(fragment, "get_client", Stub)
    return calls


# ------------------------------------------------------------------- цена

def test_price_follows_the_rate(stars_shop):
    assert stars.price_rub(50) == 80
    assert stars.price_rub(100) == 160
    assert stars.price_rub(1000) == 1600


@pytest.mark.parametrize("raw,expected", [
    ("100", 100), ("1 000", 1000), ("50", 50), ("⭐ 250", 250),
])
def test_quantity_accepted(stars_shop, raw, expected):
    quantity, error = stars.validate_quantity(raw)
    assert (quantity, error) == (expected, None)


@pytest.mark.parametrize("raw", ["49", "10", "0", "", "много"])
def test_quantity_rejected(stars_shop, raw):
    quantity, error = stars.validate_quantity(raw)
    assert quantity is None and error


def test_minimum_is_explained(stars_shop):
    _, error = stars.validate_quantity("49")
    assert "50" in error


@pytest.mark.parametrize("raw,expected", [
    ("@durov_ok", "durov_ok"), ("durov_ok", "durov_ok"),
    ("https://t.me/durov_ok", "durov_ok"), ("  @Durov_OK  ", "Durov_OK"),
])
def test_username_normalised(raw, expected):
    username, error = stars.normalize_username(raw)
    assert (username, error) == (expected, None)


@pytest.mark.parametrize("raw", ["", "@ab", "@длинноеимя", "@with-dash", "@1startsdigit"])
def test_username_rejected(raw):
    username, error = stars.normalize_username(raw)
    assert username is None and error


# ---------------------------------------------------------------- сценарий

async def test_menu_offers_stars(dp, bot, session, db_file):
    await dp.feed_update(bot, text_update("/start"))
    keyboard = session.named("SendMessage")[0].reply_markup
    buttons = [b.text for row in keyboard.keyboard for b in row]
    assert "⭐ Купить звёзды" in buttons


async def test_packages_show_price(dp, bot, session, db_file):
    await dp.feed_update(bot, text_update("⭐ Купить звёзды"))
    text = session.last_text()
    assert "1,60 ₽" in text or "1.60" in text.replace(",", ".")
    assert "50" in text

    buttons = [b.text for row in session.named("SendMessage")[-1].reply_markup.inline_keyboard
               for b in row]
    assert "50 ⭐ · 80 ₽" in buttons
    assert "1000 ⭐ · 1 600 ₽" in buttons


async def test_custom_quantity_below_minimum_is_refused(dp, bot, session, db_file):
    await dp.feed_update(bot, text_update("⭐ Купить звёзды"))
    await dp.feed_update(bot, callback_update("st_custom"))
    session.clear()
    await dp.feed_update(bot, text_update("49"))
    assert "Минимальный заказ" in session.last_text()
    assert await db.get_user_orders(USER_ID) == []


async def test_full_purchase_creates_ton_invoice(dp, bot, session, db_file):
    await dp.feed_update(bot, text_update("⭐ Купить звёзды"))
    await dp.feed_update(bot, callback_update("st_qty_100"))
    await dp.feed_update(bot, callback_update("st_me"))

    confirm = session.last_text()
    assert "100" in confirm and "160 ₽" in confirm and "TON" in confirm

    session.clear()
    await dp.feed_update(bot, callback_update("st_pay"))

    orders = await db.get_user_orders(USER_ID)
    assert len(orders) == 1
    order = await db.get_order(orders[0]["id"])
    assert order["status"] == "pending"
    assert order["stars_qty"] == 100
    assert order["recipient"] == f"user{USER_ID}"
    assert order["total"] == 160
    assert order["ton_comment"] == f"order_{order['id']}"
    assert order["ton_amount"] == pytest.approx(0.5, abs=0.001)   # 160 ₽ / 320 ₽ за TON

    invoice = session.last_text()
    assert "UQtest_wallet" in invoice and order["ton_comment"] in invoice


async def test_payment_is_matched_and_stars_are_bought(dp, bot, session, db_file,
                                                       paid_transactions, auto_fragment):
    await dp.feed_update(bot, text_update("⭐ Купить звёзды"))
    await dp.feed_update(bot, callback_update("st_qty_250"))
    await dp.feed_update(bot, callback_update("st_me"))
    await dp.feed_update(bot, callback_update("st_pay"))

    order = (await db.get_user_orders(USER_ID))[0]
    paid_transactions.append({"comment": order["ton_comment"], "ton": order["ton_amount"],
                              "nano": int(order["ton_amount"] * 10**9),
                              "hash": "tx_abc", "source": "UQbuyer"})

    session.clear()
    await dp.feed_update(bot, callback_update(f"st_check_{order['id']}"))

    updated = await db.get_order(order["id"])
    assert updated["status"] == "done"
    assert updated["ton_tx"] == "tx_abc"
    assert updated["fragment_ref"] == "FRG-1"
    assert updated["delivered_at"]

    assert auto_fragment == [{"username": f"user{USER_ID}", "quantity": 250,
                              "reference": f"order_{order['id']}"}]
    to_client = " ".join(c.text for c in session.named("SendMessage") if c.chat_id == USER_ID)
    assert "250 ⭐ зачислены" in to_client


async def test_unpaid_check_explains_the_comment(dp, bot, session, db_file,
                                                 paid_transactions):
    await dp.feed_update(bot, text_update("⭐ Купить звёзды"))
    await dp.feed_update(bot, callback_update("st_qty_50"))
    await dp.feed_update(bot, callback_update("st_me"))
    await dp.feed_update(bot, callback_update("st_pay"))
    order = (await db.get_user_orders(USER_ID))[0]

    session.clear()
    await dp.feed_update(bot, callback_update(f"st_check_{order['id']}"))
    assert order["ton_comment"] in session.last_text()
    assert (await db.get_order(order["id"]))["status"] == "pending"


async def test_manual_mode_asks_admin_to_buy(dp, bot, session, db_file, paid_transactions):
    await dp.feed_update(bot, text_update("⭐ Купить звёзды"))
    await dp.feed_update(bot, callback_update("st_qty_500"))
    await dp.feed_update(bot, callback_update("st_me"))
    await dp.feed_update(bot, callback_update("st_pay"))
    order = (await db.get_user_orders(USER_ID))[0]
    paid_transactions.append({"comment": order["ton_comment"], "ton": order["ton_amount"],
                              "nano": 1, "hash": "tx_manual", "source": "UQbuyer"})

    session.clear()
    await dp.feed_update(bot, callback_update(f"st_check_{order['id']}"))

    to_admin = " ".join(c.text for c in session.named("SendMessage") if c.chat_id == ADMIN_ID)
    assert "Купить вручную" in to_admin and "500 ⭐" in to_admin

    updated = await db.get_order(order["id"])
    assert updated["status"] == "paid", "деньги получены, выдача ждёт админа"
    assert updated["delivered_at"] is None


async def test_admin_confirms_manual_purchase(dp, bot, session, db_file, paid_transactions):
    await dp.feed_update(bot, text_update("⭐ Купить звёзды"))
    await dp.feed_update(bot, callback_update("st_qty_50"))
    await dp.feed_update(bot, callback_update("st_me"))
    await dp.feed_update(bot, callback_update("st_pay"))
    order = (await db.get_user_orders(USER_ID))[0]
    paid_transactions.append({"comment": order["ton_comment"], "ton": order["ton_amount"],
                              "nano": 1, "hash": "tx", "source": "UQbuyer"})
    await dp.feed_update(bot, callback_update(f"st_check_{order['id']}"))

    session.clear()
    await dp.feed_update(bot, callback_update(f"a_stdone_{order['id']}", user_id=ADMIN_ID))

    updated = await db.get_order(order["id"])
    assert updated["status"] == "done" and updated["delivered_at"]
    to_client = " ".join(c.text for c in session.named("SendMessage") if c.chat_id == USER_ID)
    assert "зачислены" in to_client


async def test_admin_sees_pending_star_orders(dp, bot, session, db_file):
    order_id = await db.create_star_order(USER_ID, 100, "buyer_one", 160, "ton",
                                          ton_amount=0.5, ton_comment="order_1")
    await db.mark_paid(order_id, "tx", "TON")
    session.clear()
    await dp.feed_update(bot, text_update("/stars", user_id=ADMIN_ID))
    text = session.last_text()
    assert f"#{order_id}" in text and "100 ⭐" in text and "buyer_one" in text


async def test_order_cannot_be_delivered_twice(dp, bot, session, db_file, auto_fragment):
    order_id = await db.create_star_order(USER_ID, 100, "buyer_one", 160, "ton")
    await db.mark_paid(order_id, "tx", "TON")

    first = await stars.fulfil(bot, order_id)
    session.clear()
    second = await stars.fulfil(bot, order_id)

    assert first.ok and second.ok
    assert len(auto_fragment) == 1, "вторая покупка не должна уйти в шлюз"
    assert not session.named("SendMessage"), "повторных сообщений быть не должно"


async def test_greeting_explains_the_price(dp, bot, session, db_file):
    await dp.feed_update(bot, text_update("/start"))
    text = session.last_text()
    assert "1,60 ₽" in text or "1.60" in text.replace(",", ".")
    assert "50 ⭐" in text and "80 ₽" in text
    assert "каталог" not in text.lower()


async def test_about_describes_ton_and_gifting(dp, bot, session, db_file):
    await dp.feed_update(bot, text_update("ℹ️ О магазине"))
    text = session.last_text()
    assert "TON" in text and "@username" in text
