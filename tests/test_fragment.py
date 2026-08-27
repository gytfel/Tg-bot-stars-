"""Шлюз к Fragment: разбор ответов, ошибки и повторы."""

import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

import fragment
import stars


@pytest.fixture
async def gate():
    """Поддельный шлюз: тест задаёт, что он ответит."""
    plan = {"buy": (200, {"ok": True, "id": "FRG-1"}), "balance": (200, {"balance": 42.5}),
            "delay": 0, "seen": []}

    async def buy(request):
        plan["seen"].append({"headers": dict(request.headers),
                             "body": await request.json()})
        if plan["delay"]:
            await asyncio.sleep(plan["delay"])
        status, body = plan["buy"]
        if isinstance(body, str):
            return web.Response(status=status, text=body, content_type="text/plain")
        return web.json_response(body, status=status)

    async def balance(request):
        status, body = plan["balance"]
        return web.json_response(body, status=status)

    app = web.Application()
    app.router.add_post("/buyStars", buy)
    app.router.add_get("/balance", balance)
    server = TestServer(app)
    await server.start_server()
    plan["client"] = fragment.ApiFragment(str(server.make_url("")).rstrip("/"),
                                          "secret-token", "/buyStars", "/balance", timeout=2)
    yield plan
    await server.close()


async def test_successful_purchase(gate):
    result = await gate["client"].buy_stars("buyer_one", 100, "order_1")
    assert result.ok and result.reference == "FRG-1"

    sent = gate["seen"][0]
    assert sent["body"] == {"username": "buyer_one", "quantity": 100, "reference": "order_1"}
    assert sent["headers"]["Authorization"] == "Bearer secret-token"


@pytest.mark.parametrize("body,reference", [
    ({"ok": True, "id": "A1"}, "A1"),
    ({"success": True, "order_id": 77}, "77"),
    ({"status": "completed", "transaction_id": "T-9"}, "T-9"),
    ({"result": {"id": "nested"}}, "nested"),
    ({"id": "bare"}, "bare"),
])
async def test_success_shapes(gate, body, reference):
    gate["buy"] = (200, body)
    result = await gate["client"].buy_stars("buyer_one", 50, "order_2")
    assert result.ok and result.reference == reference


@pytest.mark.parametrize("body,expected", [
    ({"ok": False, "error": "not enough balance"}, "not enough balance"),
    ({"success": False, "message": "unknown username"}, "unknown username"),
    ({"status": "failed", "detail": "limit"}, "limit"),
])
async def test_gateway_refusals_are_not_retried(gate, body, expected):
    gate["buy"] = (200, body)
    result = await gate["client"].buy_stars("buyer_one", 50, "order_3")
    assert not result.ok and not result.retriable
    assert expected in result.error


async def test_client_error_is_final(gate):
    gate["buy"] = (400, {"error": "bad username"})
    result = await gate["client"].buy_stars("bad", 50, "order_4")
    assert not result.ok and not result.retriable
    assert "400" in result.error and "bad username" in result.error


@pytest.mark.parametrize("status", [500, 502, 429])
async def test_server_errors_are_retriable(gate, status):
    gate["buy"] = (status, {"error": "try later"})
    result = await gate["client"].buy_stars("buyer_one", 50, "order_5")
    assert not result.ok and result.retriable


async def test_non_json_answer_is_reported(gate):
    gate["buy"] = (200, "<html>gateway down</html>")
    result = await gate["client"].buy_stars("buyer_one", 50, "order_6")
    assert not result.ok
    assert "gateway down" in result.error


async def test_timeout_is_retriable(gate):
    gate["delay"] = 3          # клиент ждёт 2 секунды
    result = await gate["client"].buy_stars("buyer_one", 50, "order_7")
    assert not result.ok and result.retriable
    assert "не ответил" in result.error


async def test_unreachable_gateway_is_retriable():
    client = fragment.ApiFragment("http://127.0.0.1:1", "t", "/buyStars", "/balance", 2)
    result = await client.buy_stars("buyer_one", 50, "order_8")
    assert not result.ok and result.retriable


@pytest.mark.parametrize("body,expected", [
    ({"balance": 42.5}, 42.5), ({"result": {"ton": "3.75"}}, 3.75),
    ({"available": 10}, 10.0),
])
async def test_balance_shapes(gate, body, expected):
    gate["balance"] = (200, body)
    assert await gate["client"].balance() == expected


async def test_balance_failure_is_quiet(gate):
    gate["balance"] = (503, {"error": "down"})
    assert await gate["client"].balance() is None


async def test_manual_client_asks_for_a_human():
    result = await fragment.ManualFragment().buy_stars("buyer_one", 50, "order_9")
    assert not result.ok and result.manual and not result.retriable


def test_client_choice_follows_settings(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "fragment_mode", "manual")
    assert isinstance(fragment.get_client(), fragment.ManualFragment)

    monkeypatch.setattr(settings, "fragment_mode", "api")
    monkeypatch.setattr(settings, "fragment_url", "https://gate.example")
    assert isinstance(fragment.get_client(), fragment.ApiFragment)


# ------------------------------------------------------------------ повторы

def _no_delay(monkeypatch):
    """Убрать паузы между повторами, не трогая сам event loop."""
    real_sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda *args, **kwargs: real_sleep(0))

async def test_retries_stop_after_success(monkeypatch):
    _no_delay(monkeypatch)
    answers = [fragment.Purchase(ok=False, retriable=True, error="503"),
               fragment.Purchase(ok=True, reference="FRG-2")]

    class Flaky:
        async def buy_stars(self, *args):
            return answers.pop(0)

    result = await stars._buy_with_retries(Flaky(), "buyer_one", 50, 1)
    assert result.ok and result.reference == "FRG-2"
    assert answers == []


async def test_retries_give_up_and_report(monkeypatch):
    _no_delay(monkeypatch)
    from config import settings
    monkeypatch.setattr(settings, "fragment_retries", 3)
    attempts = []

    class Broken:
        async def buy_stars(self, *args):
            attempts.append(1)
            return fragment.Purchase(ok=False, retriable=True, error="шлюз молчит")

    result = await stars._buy_with_retries(Broken(), "buyer_one", 50, 1)
    assert not result.ok and len(attempts) == 3


async def test_final_error_is_not_retried(monkeypatch):
    attempts = []

    class Refuses:
        async def buy_stars(self, *args):
            attempts.append(1)
            return fragment.Purchase(ok=False, retriable=False, error="нет такого username")

    result = await stars._buy_with_retries(Refuses(), "bad", 50, 1)
    assert not result.ok and len(attempts) == 1
