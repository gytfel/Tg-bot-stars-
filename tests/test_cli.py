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


@pytest.fixture(autouse=True)
def digital_mode(monkeypatch):
    """Каталожные команды проверяем на магазине цифровых товаров."""
    from config import settings
    monkeypatch.setattr(settings, "shop_mode", "digital")
    monkeypatch.setattr(settings, "payment_currency", "XTR")


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



# --------------------------------------------------------------- звёзды

@pytest.fixture
def stars_mode(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "shop_mode", "stars")
    monkeypatch.setattr(settings, "payment_currency", "RUB")
    monkeypatch.setattr(settings, "star_price", 1.6)
    monkeypatch.setattr(settings, "min_stars", 50)
    monkeypatch.setattr(settings, "star_packages", [50, 100, 1000])
    monkeypatch.setattr(settings, "ton_wallet", "UQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAJKZ")
    monkeypatch.setattr(settings, "ton_rate_rub", 320.0)
    return settings


@pytest.fixture
def star_order(db_file, stars_mode):
    async def build():
        await db.init_db()
        await db.upsert_user(2000, "ivan", "Иван")
        order_id = await db.create_star_order(2000, 500, "buyer_one", 800, "ton",
                                              ton_amount=2.5, ton_comment="order_1")
        await db.set_ton_comment(order_id, f"order_{order_id}")
        await db.mark_paid(order_id, "tx_1", "TON")
        return order_id

    return asyncio.run(build())


def test_stars_price_list(stars_mode, db_file, capsys):
    run("stars", "price")
    out = capsys.readouterr().out
    assert "50 ⭐" in out and "80 ₽" in out
    assert "1000 ⭐" in out and "1 600 ₽" in out
    assert "0.25 TON" in out
    assert "минимум 50" in out


def test_stars_rate_from_env(stars_mode, db_file, capsys):
    run("stars", "rate")
    assert "320 ₽" in capsys.readouterr().out


def test_stars_pending_lists_unfulfilled(star_order, capsys):
    run("stars", "pending")
    out = capsys.readouterr().out
    assert f"{star_order}" in out and "500" in out and "buyer_one" in out


def test_stars_balance_needs_a_gateway(stars_mode, db_file, capsys):
    with pytest.raises(SystemExit):
        run("stars", "balance")
    assert "manual" in capsys.readouterr().out


def test_stars_fulfil_manual_closes_order(star_order, fake_telegram, capsys):
    run("stars", "fulfil", str(star_order), "--manual", "--ref", "FRG-manual")
    assert "закрыт" in capsys.readouterr().out

    order = asyncio.run(db.get_order(star_order))
    assert order["status"] == "done"
    assert order["fragment_ref"] == "FRG-manual"
    sent = [c.text for c in fake_telegram.named("SendMessage") if c.chat_id == 2000]
    assert any("зачислены" in t for t in sent)


def test_stars_fulfil_twice_is_refused(star_order, fake_telegram, capsys):
    run("stars", "fulfil", str(star_order), "--manual")
    capsys.readouterr()
    with pytest.raises(SystemExit):
        run("stars", "fulfil", str(star_order), "--manual")
    assert "уже выдан" in capsys.readouterr().out


def test_stars_fulfil_uses_the_gateway(star_order, fake_telegram, monkeypatch, capsys):
    import fragment

    class Stub:
        mode = "api"

        async def buy_stars(self, username, quantity, reference):
            assert (username, quantity) == ("buyer_one", 500)
            return fragment.Purchase(ok=True, reference="FRG-77")

        async def balance(self):
            return 1.0

    monkeypatch.setattr(fragment, "get_client", Stub)
    run("stars", "fulfil", str(star_order))
    assert "FRG-77" in capsys.readouterr().out
    assert asyncio.run(db.get_order(star_order))["fragment_ref"] == "FRG-77"


def test_stars_check_confirms_payment(stars_mode, db_file, fake_telegram, monkeypatch, capsys):
    import ton

    async def build():
        await db.init_db()
        order_id = await db.create_star_order(2000, 100, "buyer_one", 160, "ton",
                                              ton_amount=0.5, ton_comment="x")
        await db.set_ton_comment(order_id, f"order_{order_id}")
        return order_id

    order_id = asyncio.run(build())

    async def incoming(limit=100):
        return [{"comment": f"order_{order_id}", "ton": 0.5, "nano": 5 * 10**8,
                 "hash": "tx_ok", "source": "UQbuyer"}]

    monkeypatch.setattr(ton, "incoming", incoming)
    run("stars", "check")
    assert "Подтверждено оплат: 1" in capsys.readouterr().out
    assert asyncio.run(db.get_order(order_id))["ton_tx"] == "tx_ok"


def test_orders_table_shows_recipient(star_order, capsys):
    run("orders")
    out = capsys.readouterr().out
    assert "@buyer_one" in out and "500" in out


def test_order_card_shows_ton_details(star_order, capsys):
    run("order", "show", str(star_order))
    out = capsys.readouterr().out
    assert "500 ⭐ → @buyer_one" in out
    assert "2.5" in out and f"order_{star_order}" in out


def _answer(value):
    """Подменить сетевой вызов готовым ответом."""
    async def answer():
        return value

    return answer


def test_gate_explains_manual_mode(stars_mode, db_file, capsys):
    run("stars", "gate")
    out = capsys.readouterr().out
    assert "ручной" in out and "FRAGMENT_MODE=api" in out


def test_gate_checks_the_connection(stars_mode, db_file, monkeypatch, capsys):
    import fragment
    from config import settings

    monkeypatch.setattr(settings, "fragment_mode", "api")
    monkeypatch.setattr(settings, "fragment_url", "https://gate.example")
    monkeypatch.setattr(settings, "fragment_token", "secret")

    def stub():
        client = fragment.ApiFragment("https://gate.example", "secret",
                                      "/buyStars", "/balance", timeout=5)
        client.balance = _answer(12.5)
        return client

    monkeypatch.setattr(fragment, "get_client", stub)
    run("stars", "gate")
    out = capsys.readouterr().out
    assert "https://gate.example/buyStars" in out
    assert '"quantity": 50' in out, "должно быть видно, что именно уйдёт в шлюз"
    assert "баланс: 12.5" in out


def test_gate_reports_a_silent_gateway(stars_mode, db_file, monkeypatch, capsys):
    import fragment
    from config import settings

    monkeypatch.setattr(settings, "fragment_mode", "api")
    monkeypatch.setattr(settings, "fragment_url", "https://gate.example")
    monkeypatch.setattr(settings, "fragment_token", "secret")

    def stub():
        client = fragment.ApiFragment("https://gate.example", "secret",
                                      "/buyStars", "/balance", timeout=5)
        client.balance = _answer(None)
        return client

    monkeypatch.setattr(fragment, "get_client", stub)
    with pytest.raises(SystemExit):
        run("stars", "gate")
    assert "не ответил" in capsys.readouterr().out


def test_wallet_shows_address_and_transfers(stars_mode, db_file, monkeypatch, capsys):
    import ton

    async def incoming(limit=100):
        return [{"ton": 2.5, "comment": "order_42", "hash": "h", "source": "UQbuyer"},
                {"ton": 0.5, "comment": "", "hash": "h2", "source": "UQother"}]

    monkeypatch.setattr(ton, "incoming", incoming)
    run("stars", "wallet")
    out = capsys.readouterr().out
    assert "mainnet, workchain 0" in out
    assert "order_42" in out
    assert "без комментария" in out


def test_wallet_rejects_a_typo(stars_mode, db_file, monkeypatch, capsys):
    from config import settings
    from test_config import VALID_WALLET

    monkeypatch.setattr(settings, "ton_wallet", VALID_WALLET[:-1] + "X")
    with pytest.raises(SystemExit):
        run("stars", "wallet")
    assert "контрольной суммы" in capsys.readouterr().out
