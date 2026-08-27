"""Оплата: Telegram Stars, счета через провайдера, возвраты."""

import pytest

import database as db
from conftest import ADMIN_ID, USER_ID, callback_update, payment_update, text_update


@pytest.fixture
async def catalog(db_file):
    cat_id = await db.add_category("☕ Кофе")
    pid = await db.add_product(cat_id, "Эфиопия", "Цитрус", 890, None, stock=10)
    return {"cat": cat_id, "p1": pid}


@pytest.fixture
def stars_mode(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "payment_currency", "XTR")
    monkeypatch.setattr(settings, "payment_token", "")
    monkeypatch.setattr(settings, "stars_rate", 2.0)
    return settings


async def _checkout(dp, bot, product_id, method="pay_online"):
    await dp.feed_update(bot, callback_update(f"add_{product_id}"))
    await dp.feed_update(bot, callback_update("checkout"))
    await dp.feed_update(bot, text_update("Иван Тестов"))
    await dp.feed_update(bot, text_update("+79991234567"))
    await dp.feed_update(bot, text_update("Москва, ул. Ленина, 1"))
    await dp.feed_update(bot, text_update("-"))
    await dp.feed_update(bot, callback_update(method))
    await dp.feed_update(bot, callback_update("confirm_order"))


async def test_online_button_hidden_without_payment_setup(dp, bot, session, catalog,
                                                          monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "payment_token", "")
    monkeypatch.setattr(settings, "payment_currency", "RUB")
    assert settings.online_enabled is False
    buttons = [b.callback_data for row in
               __import__("keyboards").payment_kb().inline_keyboard for b in row]
    assert "pay_online" not in buttons


async def test_stars_invoice_is_single_item_in_xtr(dp, bot, session, catalog, stars_mode):
    await _checkout(dp, bot, catalog["p1"])
    invoice = session.named("SendInvoice")[0]

    assert invoice.currency == "XTR"
    assert len(invoice.prices) == 1, "для Stars нужна ровно одна позиция"
    assert invoice.prices[0].amount == 445  # 890 ₽ / 2 ₽ за звезду
    assert not invoice.provider_token, "для Stars токен провайдера не нужен"


async def test_stars_payment_marks_order_paid(dp, bot, session, catalog, stars_mode):
    await _checkout(dp, bot, catalog["p1"])
    order_id = (await db.get_user_orders(USER_ID))[0]["id"]

    await dp.feed_update(bot, payment_update(445, currency="XTR",
                                             payload=f"order_{order_id}",
                                             charge_id="stars_charge_1"))
    order = await db.get_order(order_id)
    assert order["status"] == "paid"
    assert order["currency"] == "XTR"
    assert order["charge_id"] == "stars_charge_1"


async def test_double_payment_notification_does_not_duplicate_admin_alert(
        dp, bot, session, catalog, stars_mode):
    await _checkout(dp, bot, catalog["p1"])
    order_id = (await db.get_user_orders(USER_ID))[0]["id"]
    update = payment_update(445, currency="XTR", payload=f"order_{order_id}")

    session.clear()
    await dp.feed_update(bot, update)
    await dp.feed_update(bot, update)

    alerts = [c for c in session.named("SendMessage")
              if c.chat_id == ADMIN_ID and "Новый заказ" in (c.text or "")]
    assert len(alerts) == 1
    assert (await db.get_product(catalog["p1"]))["stock"] == 9, "склад списан один раз"


async def test_pre_checkout_rejects_unknown_order(dp, bot, session, catalog):
    from aiogram.types import PreCheckoutQuery, Update
    from conftest import make_user

    query = PreCheckoutQuery(id="q1", from_user=make_user(), currency="XTR",
                             total_amount=445, invoice_payload="order_9999")
    await dp.feed_update(bot, Update(update_id=999, pre_checkout_query=query))

    answer = session.named("AnswerPreCheckoutQuery")[0]
    assert answer.ok is False
    assert "не найден" in answer.error_message


async def test_pre_checkout_accepts_pending_order(dp, bot, session, catalog, stars_mode):
    from aiogram.types import PreCheckoutQuery, Update
    from conftest import make_user

    await _checkout(dp, bot, catalog["p1"])
    order_id = (await db.get_user_orders(USER_ID))[0]["id"]
    session.clear()

    query = PreCheckoutQuery(id="q2", from_user=make_user(), currency="XTR",
                             total_amount=445, invoice_payload=f"order_{order_id}")
    await dp.feed_update(bot, Update(update_id=998, pre_checkout_query=query))
    assert session.named("AnswerPreCheckoutQuery")[0].ok is True


async def test_admin_refunds_stars(dp, bot, session, catalog, stars_mode):
    await _checkout(dp, bot, catalog["p1"])
    order_id = (await db.get_user_orders(USER_ID))[0]["id"]
    await dp.feed_update(bot, payment_update(445, currency="XTR",
                                             payload=f"order_{order_id}",
                                             charge_id="stars_charge_1"))
    session.clear()
    await dp.feed_update(bot, text_update(f"/refund {order_id}", user_id=ADMIN_ID))

    refunds = session.named("RefundStarPayment")
    assert refunds and refunds[0].telegram_payment_charge_id == "stars_charge_1"
    assert (await db.get_order(order_id))["status"] == "cancelled"


async def test_refund_requires_order_number(dp, bot, session, catalog):
    await dp.feed_update(bot, text_update("/refund", user_id=ADMIN_ID))
    assert "Формат" in session.last_text()


async def test_refund_of_cash_order_is_refused(dp, bot, session, catalog):
    order_id = await db.create_order(
        USER_ID, {"name": "И", "phone": "+7", "address": "а", "payment": "cash"},
        [{"product_id": catalog["p1"], "title": "Эфиопия", "price": 890, "quantity": 1}])
    session.clear()
    await dp.feed_update(bot, text_update(f"/refund {order_id}", user_id=ADMIN_ID))
    assert "вручную" in session.last_text()
    assert not session.named("RefundStarPayment")
