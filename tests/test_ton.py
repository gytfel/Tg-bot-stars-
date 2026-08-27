"""Оплата в TON: курс, счёт, разбор транзакций и сверка платежей."""

from datetime import datetime, timedelta

import pytest

import database as db
import fragment
import ton
from conftest import USER_ID

# ответ toncenter v3
TONCENTER = {
    "transactions": [
        {"hash": "tx_toncenter",
         "in_msg": {"source": "UQbuyer", "destination": "UQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAJKZ", "value": "500000000",
                    "message_content": {"decoded": {"type": "text_comment",
                                                    "comment": "order_42"}}}},
        {"hash": "tx_outgoing", "out_msgs": [{"value": "100"}]},
    ]
}

# ответ tonapi v2
TONAPI = {
    "transactions": [
        {"hash": "tx_tonapi",
         "in_msg": {"source": {"address": "0:abc"}, "value": 1_500_000_000,
                    "decoded_op_name": "text_comment",
                    "decoded_body": {"text": "order_43"}}},
    ]
}


@pytest.fixture(autouse=True)
def ton_settings(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "shop_mode", "stars")
    monkeypatch.setattr(settings, "ton_wallet", "UQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAJKZ")
    monkeypatch.setattr(settings, "ton_rate_rub", 320.0)
    monkeypatch.setattr(settings, "ton_tolerance", 0.02)
    return settings


# ---------------------------------------------------------------------- курс

async def test_fixed_rate_wins_over_api(ton_settings, monkeypatch):
    async def boom():
        raise AssertionError("к API ходить не должны")

    monkeypatch.setattr(ton, "_fetch_rate", boom)
    assert await ton.rate_rub() == 320.0


@pytest.mark.parametrize("payload", [
    {"rates": {"TON": {"prices": {"RUB": 317.5}}}},
    {"TON": {"RUB": "317.5"}},
    {"price": 317.5},
    317.5,
])
def test_rate_parsing_shapes(payload):
    assert ton._find_rate(payload) == 317.5


def test_rate_parsing_gives_up_gracefully():
    assert ton._find_rate({"error": "not found"}) is None


async def test_api_rate_is_cached(ton_settings, monkeypatch):
    monkeypatch.setattr(ton_settings, "ton_rate_rub", 0)
    monkeypatch.setattr(ton, "_rate_cache", (0.0, 0.0))
    calls = []

    async def fetch():
        calls.append(1)
        return 300.0

    monkeypatch.setattr(ton, "_fetch_rate", fetch)
    assert await ton.rate_rub() == 300.0
    assert await ton.rate_rub() == 300.0
    assert len(calls) == 1, "второй раз курс берём из кэша"


async def test_missing_rate_is_an_explicit_error(ton_settings, monkeypatch):
    monkeypatch.setattr(ton_settings, "ton_rate_rub", 0)
    monkeypatch.setattr(ton, "_rate_cache", (0.0, 0.0))

    async def nothing():
        return None

    monkeypatch.setattr(ton, "_fetch_rate", nothing)
    with pytest.raises(RuntimeError, match="TON_RATE_RUB"):
        await ton.rate_rub()


# ---------------------------------------------------------------------- счёт

@pytest.mark.parametrize("rub,rate,expected", [
    (160, 320, 0.5),
    (80, 320, 0.25),
    (100, 320, 0.313),      # округляем вверх, чтобы не было недоплаты
    (1600, 317.5, 5.040),
])
def test_conversion_rounds_up(rub, rate, expected):
    assert ton.to_ton(rub, rate) == expected


def test_conversion_needs_a_rate():
    with pytest.raises(ValueError):
        ton.to_ton(100, 0)


def test_comment_carries_the_order_number():
    assert ton.comment_for(42) == "order_42"


def test_invoice_names_wallet_and_comment(ton_settings):
    text = ton.invoice_text({"ton_amount": 0.5, "ton_comment": "order_7"})
    assert "0.5 TON" in text and "UQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAJKZ" in text and "order_7" in text


# --------------------------------------------------------------- транзакции

def test_toncenter_shape_is_parsed():
    parsed = ton.parse_transactions(TONCENTER)
    assert len(parsed) == 1, "исходящие транзакции игнорируем"
    assert parsed[0] == {"comment": "order_42", "nano": 500_000_000, "ton": 0.5,
                         "hash": "tx_toncenter", "source": "UQbuyer"}


def test_tonapi_shape_is_parsed():
    parsed = ton.parse_transactions(TONAPI)
    assert parsed[0]["comment"] == "order_43"
    assert parsed[0]["ton"] == 1.5
    assert parsed[0]["source"] == "0:abc"


@pytest.mark.parametrize("payload", [{}, {"transactions": []}, [], None, "ошибка"])
def test_broken_answers_do_not_crash(payload):
    assert ton.parse_transactions(payload) == []


def test_transfer_without_comment_is_kept_but_unmatched():
    data = {"transactions": [{"hash": "h", "in_msg": {"value": "1000000000"}}]}
    parsed = ton.parse_transactions(data)
    assert parsed[0]["comment"] == ""
    assert ton.match(parsed, "order_1", 1.0) is None


# ------------------------------------------------------------------ сверка

def _tx(comment: str, amount: float) -> dict:
    return {"comment": comment, "ton": amount, "nano": int(amount * 10**9),
            "hash": f"tx_{comment}", "source": "UQbuyer"}


def test_exact_and_generous_payments_match(ton_settings):
    transactions = [_tx("order_1", 0.5), _tx("order_2", 0.6)]
    assert ton.match(transactions, "order_1", 0.5)["hash"] == "tx_order_1"
    assert ton.match(transactions, "order_2", 0.5)["hash"] == "tx_order_2"


def test_small_shortfall_is_tolerated(ton_settings):
    assert ton.match([_tx("order_1", 0.4901)], "order_1", 0.5) is not None


def test_real_underpayment_is_not_matched(ton_settings):
    assert ton.match([_tx("order_1", 0.3)], "order_1", 0.5) is None


def test_other_orders_are_not_confused(ton_settings):
    assert ton.match([_tx("order_11", 0.5)], "order_1", 0.5) is None


# ------------------------------------------------------- проверка заказов

@pytest.fixture
def inbox(monkeypatch):
    box: list[dict] = []

    async def fake_incoming(limit: int = 100):
        return list(box)

    monkeypatch.setattr(ton, "incoming", fake_incoming)
    return box


@pytest.fixture
def auto_fragment(monkeypatch):
    class Stub:
        async def buy_stars(self, username, quantity, reference):
            return fragment.Purchase(ok=True, reference="FRG-1")

        async def balance(self):
            return 100.0

    monkeypatch.setattr(fragment, "get_client", Stub)


async def test_paid_order_is_confirmed_and_fulfilled(bot, db_file, inbox, auto_fragment):
    await db.init_db()
    order_id = await db.create_star_order(USER_ID, 100, "buyer_one", 160, "ton",
                                          ton_amount=0.5, ton_comment="order_1")
    await db.set_ton_comment(order_id, f"order_{order_id}")
    inbox.append(_tx(f"order_{order_id}", 0.5))

    assert await ton.check_pending(bot) == 1

    order = await db.get_order(order_id)
    assert order["status"] == "done"
    assert order["ton_tx"] == f"tx_order_{order_id}"
    assert order["charge_id"] == f"tx_order_{order_id}"


async def test_unpaid_order_stays_pending(bot, db_file, inbox):
    await db.init_db()
    order_id = await db.create_star_order(USER_ID, 100, "buyer_one", 160, "ton",
                                          ton_amount=0.5, ton_comment="order_1")
    await db.set_ton_comment(order_id, f"order_{order_id}")

    assert await ton.check_pending(bot) == 0
    assert (await db.get_order(order_id))["status"] == "pending"


async def test_expired_invoice_is_cancelled(bot, db_file, inbox, monkeypatch, session):
    from config import settings
    monkeypatch.setattr(settings, "ton_invoice_ttl", 60)

    await db.init_db()
    order_id = await db.create_star_order(USER_ID, 100, "buyer_one", 160, "ton",
                                          ton_amount=0.5, ton_comment="order_1")
    await db.set_ton_comment(order_id, f"order_{order_id}")
    old = (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")
    async with db.db() as conn:
        await conn.execute("UPDATE orders SET created_at = ? WHERE id = ?", (old, order_id))

    await ton.check_pending(bot)

    assert (await db.get_order(order_id))["status"] == "cancelled"
    assert "истёк" in session.last_text()


async def test_payment_is_credited_once(bot, db_file, inbox, auto_fragment):
    await db.init_db()
    order_id = await db.create_star_order(USER_ID, 100, "buyer_one", 160, "ton",
                                          ton_amount=0.5, ton_comment="order_1")
    await db.set_ton_comment(order_id, f"order_{order_id}")
    inbox.append(_tx(f"order_{order_id}", 0.5))

    assert await ton.check_pending(bot) == 1
    assert await ton.check_pending(bot) == 0, "оплаченный заказ больше не проверяется"


# ------------------------------------------------------------------- адрес

VALID = "UQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAJKZ"
TESTNET = "0QAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACkT"
REAL = "UQDjKyZ9Do1_sYvoFcZmntJ7KDKQvVvB-Gsb-jFSezNXvUxQ"


def test_real_address_passes_checksum():
    parsed = ton.parse_address(REAL)
    assert parsed == {"workchain": 0, "testnet": False, "bounceable": False}
    assert ton.describe_address(REAL) == "mainnet, workchain 0, non-bounceable"


def test_testnet_address_is_flagged():
    assert ton.parse_address(TESTNET)["testnet"] is True


@pytest.mark.parametrize("broken", [
    "",                       # пусто
    "UQtest",                 # слишком коротко
    REAL[:-1] + "X",          # одна буква изменена — контрольная сумма не сойдётся
    REAL[:-1],                # потерян символ
    REAL + "A",               # лишний символ
    "не адрес вовсе",
    "0:e32b267d0e8d7fb18be815c6669ed27b283290bd5bc1f86b1bfa31527b3357bd",  # raw-форма
])
def test_broken_addresses_are_rejected(broken):
    assert ton.parse_address(broken) is None


def test_every_single_character_typo_is_caught():
    """Контрольная сумма должна ловить замену любого символа адреса."""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    missed = []
    for position in range(len(REAL)):
        for char in alphabet:
            if char == REAL[position]:
                continue
            candidate = REAL[:position] + char + REAL[position + 1:]
            if ton.parse_address(candidate):
                missed.append(candidate)
    assert not missed, f"опечатки прошли проверку: {missed[:3]}"


# --------------------------------------------------------- источники курса

@pytest.mark.parametrize("value,count", [
    ("https://a.example https://b.example", 2),
    ("https://a.example, https://b.example", 2),
    ("https://tonapi.io/v2/rates?tokens=ton&currencies=rub,usd", 1),
    ("https://one.example", 1),
    ("", 0),
])
def test_rate_sources_split(monkeypatch, value, count):
    from config import settings
    monkeypatch.setattr(settings, "ton_rate_url", value)
    assert len(ton.rate_sources()) == count


async def test_first_working_source_wins(ton_settings, monkeypatch):
    monkeypatch.setattr(ton_settings, "ton_rate_rub", 0)
    monkeypatch.setattr(ton, "_rate_cache", (0.0, 0.0))
    monkeypatch.setattr(ton_settings, "ton_rate_url",
                        "https://dead.example https://alive.example")
    asked = []

    class Response:
        def __init__(self, url):
            self.url = url
            self.status = 500 if "dead" in url else 200

        async def json(self, content_type=None):
            return {"rates": {"TON": {"prices": {"RUB": 305.5}}}}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

    class Session:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, url):
            asked.append(url)
            return Response(url)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

    import aiohttp
    monkeypatch.setattr(aiohttp, "ClientSession", Session)

    assert await ton.rate_rub() == 305.5
    assert asked == ["https://dead.example", "https://alive.example"]


async def test_stale_rate_is_refused(ton_settings, monkeypatch):
    """Курс двухчасовой давности — не курс: лучше не продать, чем продать в минус."""
    import time

    monkeypatch.setattr(ton_settings, "ton_rate_rub", 0)
    monkeypatch.setattr(ton, "_rate_cache", (300.0, time.time() - 7200))

    async def nothing():
        return None

    monkeypatch.setattr(ton, "_fetch_rate", nothing)
    with pytest.raises(RuntimeError, match="TON_RATE_RUB"):
        await ton.rate_rub()


async def test_recent_rate_survives_api_outage(ton_settings, monkeypatch):
    import time

    monkeypatch.setattr(ton_settings, "ton_rate_rub", 0)
    monkeypatch.setattr(ton, "_rate_cache", (300.0, time.time() - 900))

    async def nothing():
        return None

    monkeypatch.setattr(ton, "_fetch_rate", nothing)
    assert await ton.rate_rub() == 300.0


@pytest.mark.parametrize("payload,expected", [
    ({"rates": {"TON": {"prices": {"RUB": 305.5}}}}, 305.5),          # tonapi
    ({"the-open-network": {"rub": 305.5}}, 305.5),                    # coingecko
    ({"RUB": 305.5}, 305.5),                                          # cryptocompare
])
def test_rate_shapes_of_real_services(payload, expected):
    assert ton._find_rate(payload) == expected
