"""Цифровой магазин: короткое оформление и выдача товара после оплаты."""

import pytest
from aiogram.types import Document

import database as db
import keyboards as kb
from conftest import ADMIN_ID, USER_ID, callback_update, payment_update, text_update


@pytest.fixture
async def catalog(db_file):
    cat_id = await db.add_category("📚 Курсы")
    with_content = await db.add_product(
        cat_id, "Курс по Python", "12 уроков", 890, None,
        content="https://example.com/course · код доступа PY-2026")
    without = await db.add_product(cat_id, "Консультация", "60 минут", 3000, None)
    return {"cat": cat_id, "course": with_content, "call": without}


async def _buy(dp, bot, product_id, method="pay_online"):
    await dp.feed_update(bot, callback_update(f"add_{product_id}"))
    await dp.feed_update(bot, callback_update("checkout"))
    await dp.feed_update(bot, callback_update(method))
    await dp.feed_update(bot, callback_update("confirm_order"))


async def test_checkout_skips_the_form(dp, bot, session, catalog):
    """Цифровому товару не нужны телефон и адрес — сразу оплата."""
    await dp.feed_update(bot, callback_update(f"add_{catalog['course']}"))
    session.clear()
    await dp.feed_update(bot, callback_update("checkout"))

    texts = " ".join(session.texts())
    assert "Способ оплаты" in texts
    assert "зовут" not in texts and "Адрес" not in texts


async def test_cash_on_delivery_is_hidden(dp, bot, session, catalog):
    buttons = [b.callback_data for row in kb.payment_kb().inline_keyboard for b in row]
    assert "pay_cash" not in buttons
    assert "pay_online" in buttons


async def test_paid_order_is_delivered_immediately(dp, bot, session, catalog):
    await _buy(dp, bot, catalog["course"])
    order_id = (await db.get_user_orders(USER_ID))[0]["id"]

    session.clear()
    await dp.feed_update(bot, payment_update(445, currency="XTR",
                                             payload=f"order_{order_id}"))

    to_client = [c.text for c in session.named("SendMessage") if c.chat_id == USER_ID]
    assert any("PY-2026" in t for t in to_client), "покупатель должен получить доступ"

    order = await db.get_order(order_id)
    assert order["status"] == "done"
    assert order["delivered_at"]


async def test_delivery_happens_once(dp, bot, session, catalog):
    await _buy(dp, bot, catalog["course"])
    order_id = (await db.get_user_orders(USER_ID))[0]["id"]
    update = payment_update(445, currency="XTR", payload=f"order_{order_id}")

    await dp.feed_update(bot, update)
    session.clear()
    await dp.feed_update(bot, update)

    resent = [c for c in session.named("SendMessage")
              if c.chat_id == USER_ID and "PY-2026" in (c.text or "")]
    assert resent == [], "доступ не должен уходить повторно"


async def test_product_without_content_alerts_admin(dp, bot, session, catalog):
    await _buy(dp, bot, catalog["call"])
    order_id = (await db.get_user_orders(USER_ID))[0]["id"]

    session.clear()
    await dp.feed_update(bot, payment_update(1500, currency="XTR",
                                             payload=f"order_{order_id}"))

    to_client = " ".join(c.text for c in session.named("SendMessage")
                         if c.chat_id == USER_ID)
    to_admin = " ".join(c.text for c in session.named("SendMessage")
                        if c.chat_id == ADMIN_ID)
    assert "менеджер" in to_client
    assert "не заполнено" in to_admin
    assert (await db.get_order(order_id))["status"] == "paid", "заказ ждёт ручной выдачи"


async def test_transfer_is_delivered_when_admin_confirms(dp, bot, session, catalog):
    await _buy(dp, bot, catalog["course"], method="pay_transfer")
    order_id = (await db.get_user_orders(USER_ID))[0]["id"]
    assert (await db.get_order(order_id))["status"] == "new"

    session.clear()
    await dp.feed_update(bot, callback_update(f"a_status_{order_id}_paid", user_id=ADMIN_ID))

    to_client = " ".join(c.text for c in session.named("SendMessage") if c.chat_id == USER_ID)
    assert "PY-2026" in to_client
    assert (await db.get_order(order_id))["status"] == "done"


async def test_deleted_product_still_delivers(dp, bot, session, catalog):
    """Содержимое сохраняется в заказе, поэтому удаление товара выдаче не мешает."""
    await _buy(dp, bot, catalog["course"])
    order_id = (await db.get_user_orders(USER_ID))[0]["id"]
    await db.delete_product(catalog["course"])

    session.clear()
    await dp.feed_update(bot, payment_update(445, currency="XTR",
                                             payload=f"order_{order_id}"))
    to_client = " ".join(c.text for c in session.named("SendMessage") if c.chat_id == USER_ID)
    assert "PY-2026" in to_client


async def test_admin_adds_digital_product_with_content(dp, bot, session, catalog):
    await dp.feed_update(bot, callback_update(f"a_addprod_{catalog['cat']}", user_id=ADMIN_ID))
    await dp.feed_update(bot, text_update("Шаблоны", user_id=ADMIN_ID))
    await dp.feed_update(bot, text_update("30 штук", user_id=ADMIN_ID))
    await dp.feed_update(bot, text_update("500", user_id=ADMIN_ID))
    await dp.feed_update(bot, text_update("-", user_id=ADMIN_ID))
    session.clear()
    await dp.feed_update(bot, text_update("https://example.com/templates", user_id=ADMIN_ID))

    products = await db.get_products(catalog["cat"], only_active=False)
    added = next(p for p in products if p["title"] == "Шаблоны")
    assert added["content"] == "https://example.com/templates"
    assert "добавлен" in session.texts()[0]


async def test_admin_warned_when_content_skipped(dp, bot, session, catalog):
    await dp.feed_update(bot, callback_update(f"a_addprod_{catalog['cat']}", user_id=ADMIN_ID))
    await dp.feed_update(bot, text_update("Без выдачи", user_id=ADMIN_ID))
    await dp.feed_update(bot, text_update("-", user_id=ADMIN_ID))
    await dp.feed_update(bot, text_update("500", user_id=ADMIN_ID))
    await dp.feed_update(bot, text_update("-", user_id=ADMIN_ID))
    session.clear()
    await dp.feed_update(bot, text_update("-", user_id=ADMIN_ID))
    assert "Не указано, что выдавать" in session.texts()[0]


async def test_file_content_is_sent_as_document(dp, bot, session, db_file):
    cat_id = await db.add_category("📁 Файлы")
    pid = await db.add_product(cat_id, "Чек-лист", "PDF", 200, None,
                               content="Файл во вложении",
                               content_file_id="BQACAgIAAxk-file")
    await _buy(dp, bot, pid)
    order_id = (await db.get_user_orders(USER_ID))[0]["id"]

    session.clear()
    await dp.feed_update(bot, payment_update(100, currency="XTR",
                                             payload=f"order_{order_id}"))
    docs = session.named("SendDocument")
    assert docs and docs[0].document == "BQACAgIAAxk-file"


async def test_admin_attaches_file_as_content(dp, bot, session, catalog):
    document = Document(file_id="BQACAgIAAxk-new", file_unique_id="u", file_name="course.pdf")
    await dp.feed_update(bot, callback_update(f"a_addprod_{catalog['cat']}", user_id=ADMIN_ID))
    await dp.feed_update(bot, text_update("Гайд", user_id=ADMIN_ID))
    await dp.feed_update(bot, text_update("-", user_id=ADMIN_ID))
    await dp.feed_update(bot, text_update("990", user_id=ADMIN_ID))
    await dp.feed_update(bot, text_update("-", user_id=ADMIN_ID))
    await dp.feed_update(bot, text_update(None, user_id=ADMIN_ID, document=document,
                                          caption="Гайд в PDF"))

    products = await db.get_products(catalog["cat"], only_active=False)
    added = next(p for p in products if p["title"] == "Гайд")
    assert added["content_file_id"] == "BQACAgIAAxk-new"
    assert added["content"] == "Гайд в PDF"


async def test_undelivered_order_can_be_retried(dp, bot, session, catalog, monkeypatch):
    """Покупатель заблокировал бота: заказ не считается выданным, админ предупреждён."""
    await _buy(dp, bot, catalog["course"])
    order_id = (await db.get_user_orders(USER_ID))[0]["id"]

    original = bot.send_message
    failures = []

    async def blocked(chat_id, text, **kwargs):
        if chat_id == USER_ID and "доступ" in text:
            failures.append(chat_id)
            raise RuntimeError("bot was blocked by the user")
        return await original(chat_id, text, **kwargs)

    monkeypatch.setattr(bot, "send_message", blocked)
    await dp.feed_update(bot, payment_update(445, currency="XTR",
                                             payload=f"order_{order_id}"))

    assert failures, "выдача должна была попытаться уйти покупателю"
    order = await db.get_order(order_id)
    assert order["delivered_at"] is None, "заказ не должен считаться выданным"
    assert order["status"] == "paid"

    # повтор после разблокировки — обычным путём
    monkeypatch.setattr(bot, "send_message", original)
    from handlers_user import deliver_order
    assert await deliver_order(bot, order_id) is True
    assert (await db.get_order(order_id))["delivered_at"]
