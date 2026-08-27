"""Управление из терминала: python manage.py ...

Тесты синхронные: manage.main сам поднимает event loop, как при реальном запуске.
"""

import asyncio

import pytest

import database as db
import manage


@pytest.fixture(autouse=True)
def no_color(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")


@pytest.fixture
def shop(db_file):
    async def build():
        await db.init_db()
        cat = await db.add_category("📚 Курсы")
        course = await db.add_product(cat, "Python с нуля", "12 уроков", 2900, None,
                                      content="Доступ: https://example.com/py")
        await db.upsert_user(2000, "ivan", "Иван Тестов")
        order = await db.create_order(
            2000, {"name": "Иван Тестов", "payment": "online", "currency": "XTR"},
            [{"product_id": course, "title": "Python с нуля", "price": 2900,
              "quantity": 1, "content": "Доступ: https://example.com/py"}],
            status="pending", commit_stock=False, clear_cart=False)
        await db.mark_paid(order, "stars_charge_1", "XTR")
        return {"cat": cat, "course": course, "order": order}

    return asyncio.run(build())


def run(*argv: str) -> None:
    manage.main(list(argv))


def test_status_shows_mode_and_totals(shop, capsys):
    run("status")
    out = capsys.readouterr().out
    assert "цифровой товар" in out
    assert "Telegram Stars" in out
    assert "2 900 ₽" in out


def test_catalog_lists_products_with_delivery(shop, capsys):
    run("catalog")
    out = capsys.readouterr().out
    assert "Python с нуля" in out
    assert "example.com/py" in out
    assert "⭐" in out, "в режиме Stars цена показывается в звёздах"


def test_product_add_and_content(shop, capsys):
    run("product", "add", "--cat", str(shop["cat"]), "--title", "Гайд",
        "--price", "1200", "--desc", "PDF")
    out = capsys.readouterr().out
    assert "добавлен" in out
    assert "Не забудьте" in out, "без содержимого CLI должен напомнить"

    products = asyncio.run(db.get_products(shop["cat"], only_active=False))
    guide = next(p for p in products if p["title"] == "Гайд")

    run("product", "content", str(guide["id"]), "https://example.com/guide")
    updated = asyncio.run(db.get_product(guide["id"]))
    assert updated["content"] == "https://example.com/guide"


def test_product_add_rejects_unknown_category(shop, capsys):
    with pytest.raises(SystemExit):
        run("product", "add", "--cat", "999", "--title", "X", "--price", "1")
    assert "Категории 999 нет" in capsys.readouterr().out


def test_product_toggle_and_remove(shop, capsys):
    run("product", "toggle", str(shop["course"]))
    assert asyncio.run(db.get_product(shop["course"]))["is_active"] == 0
    run("product", "rm", str(shop["course"]))
    assert asyncio.run(db.get_product(shop["course"])) is None


def test_category_add_and_remove(shop, capsys):
    run("category", "add", "🧩 Шаблоны")
    cats = asyncio.run(db.get_categories(only_active=False))
    added = next(c for c in cats if c["title"] == "🧩 Шаблоны")
    run("category", "rm", str(added["id"]))
    assert all(c["id"] != added["id"] for c in asyncio.run(db.get_categories(False)))


def test_orders_and_order_card(shop, capsys):
    run("orders")
    out = capsys.readouterr().out
    assert "Оплачен" in out

    run("order", "show", str(shop["order"]))
    out = capsys.readouterr().out
    assert "Python с нуля" in out
    assert "stars_charge_1" in out
    assert "Иван Тестов" in out


def test_orders_filter_by_status(shop, capsys):
    run("orders", "--status", "new")
    assert "— пусто —" in capsys.readouterr().out


def test_order_card_of_missing_order_fails(shop, capsys):
    with pytest.raises(SystemExit):
        run("order", "show", "999")
    assert "нет" in capsys.readouterr().out


def test_stats_shows_top_products(shop, capsys):
    run("stats")
    out = capsys.readouterr().out
    assert "Топ товаров" in out and "Python с нуля" in out


def test_users_list(shop, capsys):
    run("users")
    assert "@ivan" in capsys.readouterr().out


def test_broadcast_dry_run_sends_nothing(shop, capsys):
    run("broadcast", "Новый курс уже в каталоге", "--dry-run")
    out = capsys.readouterr().out
    assert "Получателей: 1" in out
    assert "ничего не отправлено" in out


def test_backup_creates_file(shop, tmp_path, capsys):
    target = tmp_path / "backups"
    run("backup", "--dir", str(target))
    copies = list(target.glob("shop-*.db"))
    assert len(copies) == 1 and copies[0].stat().st_size > 0

    # копия читается и содержит те же данные
    import sqlite3
    with sqlite3.connect(copies[0]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1


def test_refund_of_non_stars_order_is_refused(shop, capsys):
    asyncio.run(db.create_order(
        2000, {"name": "И", "payment": "cash"},
        [{"product_id": shop["course"], "title": "Python с нуля", "price": 2900,
          "quantity": 1}]))
    with pytest.raises(SystemExit):
        run("refund", "2")
    assert "нет онлайн-платежа" in capsys.readouterr().out


def test_deliver_requires_existing_order(shop, capsys):
    with pytest.raises(SystemExit):
        run("deliver", "999")
    assert "нет" in capsys.readouterr().out


def test_service_command_shapes():
    assert manage.service_command("restart", "systemd") == [
        "sudo", "systemctl", "restart", "shopbot"]
    assert manage.service_command("start", "docker") == ["docker", "compose", "up", "-d"]
    assert manage.service_command("logs", "docker", follow=True, lines=10) == [
        "docker", "compose", "logs", "--tail", "10", "-f"]
    assert manage.service_command("logs", "systemd", lines=5) == [
        "journalctl", "-u", "shopbot", "-n", "5"]


def test_unknown_command_exits(capsys):
    with pytest.raises(SystemExit):
        run("нетакой")


@pytest.fixture
def fake_telegram(monkeypatch):
    """Подменяем реального бота поддельной сессией: команда идёт до отправки."""
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    from conftest import FakeSession

    bot = Bot("42:TEST", session=FakeSession(),
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    class Stub:
        async def __aenter__(self):
            return bot

        async def __aexit__(self, *exc_info):
            return None

    monkeypatch.setattr(manage, "telegram", Stub)
    return bot.session


def test_order_status_notifies_client_and_delivers(shop, fake_telegram, capsys):
    asyncio.run(db.set_status(shop["order"], "new"))

    run("order", "status", str(shop["order"]), "paid")

    out = capsys.readouterr().out
    assert "Оплачен" in out and "выдан покупателю" in out

    sent = [c.text for c in fake_telegram.named("SendMessage") if c.chat_id == 2000]
    assert any("Статус вашего заказа" in t for t in sent)
    assert any("example.com/py" in t for t in sent), "доступ должен уйти покупателю"
    assert asyncio.run(db.get_order(shop["order"]))["status"] == "done"


def test_deliver_command_sends_content(shop, fake_telegram, capsys):
    run("deliver", str(shop["order"]))
    assert "выдан покупателю" in capsys.readouterr().out
    sent = [c.text for c in fake_telegram.named("SendMessage") if c.chat_id == 2000]
    assert any("example.com/py" in t for t in sent)


def test_deliver_twice_is_refused(shop, fake_telegram, capsys):
    run("deliver", str(shop["order"]))
    capsys.readouterr()
    with pytest.raises(SystemExit):
        run("deliver", str(shop["order"]))
    assert "уже выдан" in capsys.readouterr().out


def test_refund_returns_stars_and_cancels(shop, fake_telegram, capsys):
    run("refund", str(shop["order"]))
    out = capsys.readouterr().out
    assert "возвращены" in out
    refunds = fake_telegram.named("RefundStarPayment")
    assert refunds and refunds[0].telegram_payment_charge_id == "stars_charge_1"
    assert asyncio.run(db.get_order(shop["order"]))["status"] == "cancelled"


def test_broadcast_sends_to_every_user(shop, fake_telegram, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)   # без вопроса «Отправить?»
    run("broadcast", "Новый курс уже в каталоге")
    out = capsys.readouterr().out
    assert "Доставлено: 1" in out
    assert any("Новый курс" in (c.text or "")
               for c in fake_telegram.named("SendMessage"))
