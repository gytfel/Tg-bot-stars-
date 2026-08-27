"""Режим webhook: сервер поднимается, healthcheck отвечает, апдейты доходят."""

import asyncio
import json

from aiohttp.test_utils import TestClient, TestServer

from bot import build_app
from conftest import USER_ID, text_update


async def _client(bot, dp) -> TestClient:
    client = TestClient(TestServer(build_app(bot, dp)))
    await client.start_server()
    return client


async def test_healthz_reports_ok(bot, dp):
    client = await _client(bot, dp)
    try:
        response = await client.get("/healthz")
        assert response.status == 200
        assert (await response.json())["status"] == "ok"
    finally:
        await client.close()


async def test_update_over_webhook_reaches_handler(bot, dp, session, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "webhook_secret", "")

    client = await _client(bot, dp)
    try:
        update = text_update("/start")
        response = await client.post(
            "/webhook", data=update.model_dump_json(exclude_none=True),
            headers={"Content-Type": "application/json"})
        assert response.status == 200
    finally:
        await client.close()

    # SimpleRequestHandler отвечает Telegram сразу, а апдейт обрабатывает фоном
    import database as db
    for _ in range(50):
        if USER_ID in await db.all_user_ids():
            break
        await asyncio.sleep(0.02)
    assert USER_ID in await db.all_user_ids()


async def test_webhook_rejects_wrong_secret(bot, dp, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "webhook_secret", "s3cret")

    client = await _client(bot, dp)
    try:
        response = await client.post(
            "/webhook", data=json.dumps({"update_id": 1}),
            headers={"Content-Type": "application/json",
                     "X-Telegram-Bot-Api-Secret-Token": "wrong"})
        assert response.status == 401
    finally:
        await client.close()
