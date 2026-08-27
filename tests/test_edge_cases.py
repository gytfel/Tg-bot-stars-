"""Пограничные случаи: не-текстовые сообщения, пустые данные, оплата."""

import pytest
from aiogram.types import PhotoSize

import database as db
from conftest import ADMIN_ID, USER_ID, callback_update, payment_update, text_update

PHOTO = [PhotoSize(file_id="photo_1", file_unique_id="u1", width=100, height=100)]


@pytest.fixture(autouse=True)
def physical_mode(monkeypatch):
    """Эти сценарии описывают магазин физических товаров (анкета с адресом)."""
    from config import settings
    monkeypatch.setattr(settings, "shop_mode", "physical")


@pytest.fixture
async def catalog(db_file):
    cat_id = await db.add_category("☕ Кофе")
    pid = await db.add_product(cat_id, "Эфиопия", "Цитрус", 890, None, stock=10)
    return {"cat": cat_id, "p1": pid}


async def test_sticker_instead_of_category_title(dp, bot, session):
    """Админ отправляет стикер/фото вместо названия категории — бот не должен падать."""
    await dp.feed_update(bot, callback_update("a_addcat", user_id=ADMIN_ID))
    session.clear()
    await dp.feed_update(bot, text_update(None, user_id=ADMIN_ID, photo=PHOTO))
    assert await db.get_categories(only_active=False) == []
    assert "текстом" in session.last_text()


async def test_photo_instead_of_product_description(dp, bot, session, catalog):
    await dp.feed_update(bot, callback_update(f"a_addprod_{catalog['cat']}", user_id=ADMIN_ID))
    await dp.feed_update(bot, text_update("Колумбия", user_id=ADMIN_ID))
    session.clear()
    await dp.feed_update(bot, text_update(None, user_id=ADMIN_ID, photo=PHOTO))
    assert "текстом" in session.last_text()


async def test_broadcast_with_photo_message(dp, bot, session):
    """Рассылка картинкой: раньше уходил пустой текст, теперь копируется сообщение."""
    await db.upsert_user(USER_ID, "user", "Иван")
    await dp.feed_update(bot, callback_update("a_broadcast", user_id=ADMIN_ID))
    session.clear()
    await dp.feed_update(bot, text_update(None, user_id=ADMIN_ID, photo=PHOTO))
    delivered = [c for c in session.named("CopyMessage") if c.chat_id == USER_ID]
    assert delivered, "фото должно уйти подписчику"


async def test_empty_catalog_does_not_break_cart_refresh(dp, bot, session, db_file):
    await dp.feed_update(bot, text_update("🛒 Корзина"))
    assert "пуста" in session.last_text()


async def test_online_payment_invoice_amount(dp, bot, session, catalog, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "payment_token", "test:provider:token")
    monkeypatch.setattr(settings, "payment_currency", "RUB")

    await dp.feed_update(bot, callback_update(f"add_{catalog['p1']}"))
    await dp.feed_update(bot, callback_update("checkout"))
    await dp.feed_update(bot, text_update("Иван Тестов"))
    await dp.feed_update(bot, text_update("+79991234567"))
    await dp.feed_update(bot, text_update("Москва, ул. Ленина, 1"))
    await dp.feed_update(bot, text_update("-"))
    await dp.feed_update(bot, callback_update("pay_online"))
    session.clear()
    await dp.feed_update(bot, callback_update("confirm_order"))

    invoices = session.named("SendInvoice")
    assert invoices, "должен быть выставлен счёт"
    assert sum(p.amount for p in invoices[0].prices) == 89000  # 890 ₽ в копейках
    assert invoices[0].currency == "RUB"

    # заказ висит как «ожидает оплаты»: склад и корзина не тронуты
    orders = await db.get_user_orders(USER_ID)
    assert len(orders) == 1 and orders[0]["status"] == "pending"
    assert invoices[0].payload == f"order_{orders[0]['id']}"
    assert (await db.get_product(catalog["p1"]))["stock"] == 10
    assert await db.get_cart(USER_ID)


async def test_successful_payment_creates_paid_order(dp, bot, session, catalog, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "payment_token", "test:provider:token")
    monkeypatch.setattr(settings, "payment_currency", "RUB")

    await dp.feed_update(bot, callback_update(f"add_{catalog['p1']}"))
    await dp.feed_update(bot, callback_update("checkout"))
    await dp.feed_update(bot, text_update("Иван Тестов"))
    await dp.feed_update(bot, text_update("+79991234567"))
    await dp.feed_update(bot, text_update("Москва, ул. Ленина, 1"))
    await dp.feed_update(bot, text_update("-"))
    await dp.feed_update(bot, callback_update("pay_online"))
    await dp.feed_update(bot, callback_update("confirm_order"))

    order_id = (await db.get_user_orders(USER_ID))[0]["id"]
    session.clear()
    await dp.feed_update(bot, payment_update(89000, payload=f"order_{order_id}"))

    orders = await db.get_user_orders(USER_ID)
    assert len(orders) == 1, "оплата не должна создавать второй заказ"
    order = await db.get_order(order_id)
    assert order["status"] == "paid"
    assert order["charge_id"] == "charge_1"
    assert order["name"] == "Иван Тестов", "контактные данные должны сохраниться"
    assert order["address"] == "Москва, ул. Ленина, 1"
    # только теперь списывается склад и чистится корзина
    assert (await db.get_product(catalog["p1"]))["stock"] == 9
    assert await db.get_cart(USER_ID) == []
    admin_msgs = [c for c in session.named("SendMessage") if c.chat_id == 1000]
    assert admin_msgs and "Новый заказ" in admin_msgs[-1].text


async def test_double_confirm_does_not_duplicate_order(dp, bot, session, catalog):
    await dp.feed_update(bot, callback_update(f"add_{catalog['p1']}"))
    await dp.feed_update(bot, callback_update("checkout"))
    await dp.feed_update(bot, text_update("Иван Тестов"))
    await dp.feed_update(bot, text_update("+79991234567"))
    await dp.feed_update(bot, text_update("Москва, ул. Ленина, 1"))
    await dp.feed_update(bot, text_update("-"))
    await dp.feed_update(bot, callback_update("pay_cash"))
    await dp.feed_update(bot, callback_update("confirm_order"))
    await dp.feed_update(bot, callback_update("confirm_order"))
    assert len(await db.get_user_orders(USER_ID)) == 1


async def test_stock_limit_respected(dp, bot, session, db_file):
    cat_id = await db.add_category("Тест")
    pid = await db.add_product(cat_id, "Последний", "", 100, None, stock=1)
    await dp.feed_update(bot, callback_update(f"add_{pid}"))
    await dp.feed_update(bot, callback_update(f"plus_{pid}"))
    await dp.feed_update(bot, callback_update("checkout"))
    await dp.feed_update(bot, text_update("Иван Тестов"))
    await dp.feed_update(bot, text_update("+79991234567"))
    await dp.feed_update(bot, text_update("Москва, ул. Ленина, 1"))
    await dp.feed_update(bot, text_update("-"))
    await dp.feed_update(bot, callback_update("pay_cash"))
    session.clear()
    await dp.feed_update(bot, callback_update("confirm_order"))
    orders = await db.get_user_orders(USER_ID)
    assert not orders or orders[0]["total"] <= 100, "нельзя продать больше, чем на складе"
