"""Проверка админ-панели: каталог, заказы, статусы, рассылка."""

import pytest

import database as db
from conftest import ADMIN_ID, USER_ID, callback_update, text_update


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


async def test_admin_panel_opens_for_admin_only(dp, bot, session):
    await dp.feed_update(bot, text_update("/admin", user_id=USER_ID))
    assert "Админ-панель" not in session.last_text()

    session.clear()
    await dp.feed_update(bot, text_update("/admin", user_id=ADMIN_ID))
    assert "Админ-панель" in session.last_text()


async def test_admin_adds_category(dp, bot, session):
    await dp.feed_update(bot, callback_update("a_addcat", user_id=ADMIN_ID))
    await dp.feed_update(bot, text_update("🍫 Сладкое", user_id=ADMIN_ID))
    cats = await db.get_categories(only_active=False)
    assert [c["title"] for c in cats] == ["🍫 Сладкое"]


async def test_admin_adds_product_step_by_step(dp, bot, session, catalog):
    await dp.feed_update(bot, callback_update(f"a_addprod_{catalog['cat']}", user_id=ADMIN_ID))
    await dp.feed_update(bot, text_update("Колумбия", user_id=ADMIN_ID))
    await dp.feed_update(bot, text_update("Карамель", user_id=ADMIN_ID))
    await dp.feed_update(bot, text_update("1 990", user_id=ADMIN_ID))
    await dp.feed_update(bot, text_update("-", user_id=ADMIN_ID))

    products = await db.get_products(catalog["cat"], only_active=False)
    added = [p for p in products if p["title"] == "Колумбия"]
    assert added and added[0]["price"] == 1990


async def test_admin_price_validation(dp, bot, session, catalog):
    await dp.feed_update(bot, callback_update(f"a_addprod_{catalog['cat']}", user_id=ADMIN_ID))
    await dp.feed_update(bot, text_update("Колумбия", user_id=ADMIN_ID))
    await dp.feed_update(bot, text_update("-", user_id=ADMIN_ID))
    session.clear()
    await dp.feed_update(bot, text_update("дорого", user_id=ADMIN_ID))
    assert "числом" in session.last_text()


async def test_admin_changes_status_and_client_is_notified(dp, bot, session, catalog):
    order_id = await db.create_order(
        USER_ID, {"name": "И", "phone": "+7", "address": "а", "payment": "cash"},
        [{"product_id": catalog["p1"], "title": "Эфиопия", "price": 890, "quantity": 1}])

    session.clear()
    await dp.feed_update(bot, callback_update(f"a_status_{order_id}_shipped", user_id=ADMIN_ID))

    assert (await db.get_order(order_id))["status"] == "shipped"
    to_client = [c for c in session.named("SendMessage") if c.chat_id == USER_ID]
    assert to_client and "Отправлен" in to_client[-1].text


async def test_admin_stats(dp, bot, session, catalog):
    await db.create_order(
        USER_ID, {"name": "И", "phone": "+7", "address": "а", "payment": "cash"},
        [{"product_id": catalog["p1"], "title": "Эфиопия", "price": 890, "quantity": 2}])
    session.clear()
    await dp.feed_update(bot, callback_update("a_stats", user_id=ADMIN_ID))
    text = session.last_text()
    assert "Статистика" in text and "1 780" in text


async def test_broadcast_reaches_users(dp, bot, session, catalog):
    await db.upsert_user(USER_ID, "user", "Иван")
    await dp.feed_update(bot, callback_update("a_broadcast", user_id=ADMIN_ID))
    session.clear()
    await dp.feed_update(bot, text_update("Скидка 20%!", user_id=ADMIN_ID))
    delivered = [c for c in session.named("CopyMessage") if c.chat_id == USER_ID]
    assert delivered, "сообщение должно быть скопировано подписчику"
