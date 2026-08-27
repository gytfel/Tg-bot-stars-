"""Оплата в TON: счёт, курс и поиск входящего перевода.

Схема простая и без приватных ключей на сервере: покупателю показывается адрес
кошелька и комментарий вида `order_42`. Бот периодически читает входящие
транзакции кошелька через публичный API (по умолчанию toncenter) и, найдя
перевод с нужным комментарием и суммой, отмечает заказ оплаченным.

Читается только публичная информация — сид-фраза и ключи боту не нужны.
"""

import asyncio
import base64
import logging
import math
import re
import time
from typing import Any

import database as db
from config import settings

log = logging.getLogger(__name__)

NANO = 1_000_000_000
RATE_TTL = 600           # курс TON кэшируем на 10 минут
RATE_STALE = 3600        # старше часа — продавать по нему уже нельзя
_rate_cache: tuple[float, float] = (0.0, 0.0)   # (курс, момент получения)


# ------------------------------------------------------------------- адрес

def _crc16(data: bytes) -> int:
    """CRC16-CCITT — им заканчивается любой TON-адрес."""
    reg = 0
    for byte in data + b"\x00\x00":
        mask = 0x80
        while mask:
            reg <<= 1
            if byte & mask:
                reg += 1
            mask >>= 1
            if reg > 0xFFFF:
                reg &= 0xFFFF
                reg ^= 0x1021
    return reg


def parse_address(address: str) -> dict | None:
    """Разобрать адрес кошелька. None — адрес битый (опечатка в символе).

    Возвращает {workchain, testnet, bounceable} — контрольная сумма уже сверена.
    """
    value = (address or "").strip()
    if len(value) != 48:
        return None
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception:  # noqa: BLE001 — не base64
        return None
    if len(raw) != 36:
        return None
    if _crc16(raw[:34]).to_bytes(2, "big") != raw[34:]:
        return None

    flags = raw[0]
    workchain = raw[1] if raw[1] < 128 else raw[1] - 256
    return {"workchain": workchain,
            "testnet": bool(flags & 0x80),
            "bounceable": not bool(flags & 0x40)}


def describe_address(address: str) -> str:
    parsed = parse_address(address)
    if not parsed:
        return "адрес не проходит проверку контрольной суммы"
    network = "testnet" if parsed["testnet"] else "mainnet"
    kind = "bounceable" if parsed["bounceable"] else "non-bounceable"
    return f"{network}, workchain {parsed['workchain']}, {kind}"


# --------------------------------------------------------------------- курс

async def rate_rub(force: bool = False) -> float:
    """Сколько рублей стоит 1 TON. Фиксированный курс из .env важнее API."""
    global _rate_cache

    if settings.ton_rate_rub:
        return settings.ton_rate_rub

    rate, fetched_at = _rate_cache
    age = time.time() - fetched_at
    if rate and not force and age < RATE_TTL:
        return rate

    fresh = await _fetch_rate()
    if fresh:
        _rate_cache = (fresh, time.time())
        return fresh
    if rate and age < RATE_STALE:
        log.warning("Курс TON не обновился, беру прошлый (%.0f мин назад): %s",
                    age / 60, rate)
        return rate
    raise RuntimeError("Курс TON недоступен: ни один источник из TON_RATE_URL не "
                       "ответил. Задайте TON_RATE_RUB в .env, чтобы продавать "
                       "по фиксированному курсу.")


def rate_sources() -> list[str]:
    """Источники курса из TON_RATE_URL: через пробел или запятую.

    Запятые внутри самого адреса (например `currencies=rub,usd`) не ломают
    разбор — разделителем считается только запятая перед следующей ссылкой.
    """
    parts = re.split(r"\s+|,(?=\s*https?://)", settings.ton_rate_url or "")
    return [part.strip().rstrip(",") for part in parts if part.strip()]


async def _fetch_rate() -> float | None:
    """Пробуем источники по очереди — первый ответивший выигрывает."""
    import aiohttp

    timeout = aiohttp.ClientTimeout(total=15)
    for url in rate_sources():
        try:
            async with aiohttp.ClientSession(timeout=timeout) as http:
                async with http.get(url) as response:
                    if response.status >= 400:
                        log.warning("Курс TON: %s ответил %s", url, response.status)
                        continue
                    data = await response.json(content_type=None)
        except Exception as e:  # noqa: BLE001 — сеть
            log.warning("Курс TON не получен из %s: %s", url, e)
            continue
        rate = _find_rate(data)
        if rate:
            log.debug("Курс TON %s из %s", rate, url)
            return rate
        log.warning("Курс TON: %s ответил без понятного числа", url)
    return None


def _find_rate(data: Any) -> float | None:
    """Достать число из ответа о курсе, не завися от формы ответа."""
    if isinstance(data, (int, float)) and data > 0:
        return float(data)
    if isinstance(data, str):
        try:
            return float(data)
        except ValueError:
            return None
    if isinstance(data, dict):
        for key in ("RUB", "rub", "price", "value", "rate"):
            if key in data:
                found = _find_rate(data[key])
                if found:
                    return found
        for value in data.values():
            found = _find_rate(value)
            if found:
                return found
    return None


# --------------------------------------------------------------------- счёт

def to_ton(price_rub: float, rate: float) -> float:
    """Рубли в TON, с округлением вверх до 0.001 — чтобы не получить недоплату."""
    if rate <= 0:
        raise ValueError("курс TON должен быть больше нуля")
    return math.ceil(price_rub / rate * 1000) / 1000


def comment_for(order_id: int) -> str:
    return f"order_{order_id}"


def invoice_text(order: dict) -> str:
    """Текст счёта с реквизитами — его видит покупатель."""
    return (f"💎 <b>К оплате: {order['ton_amount']} TON</b>\n\n"
            f"Кошелёк:\n<code>{settings.ton_wallet}</code>\n\n"
            f"Комментарий к переводу (обязательно):\n<code>{order['ton_comment']}</code>\n\n"
            f"Без комментария платёж не найдётся автоматически.\n"
            f"Оплату замечаем в течение 1–2 минут.")


# ------------------------------------------------------------- поиск платежа

async def incoming(limit: int = 100) -> list[dict]:
    """Входящие переводы кошелька: [{comment, nano, hash, source}]."""
    import aiohttp

    url = f"{settings.ton_api_url}/transactions"
    params = {"account": settings.ton_wallet, "limit": str(limit)}
    headers = {"Accept": "application/json"}
    if settings.ton_api_key:
        headers["X-API-Key"] = settings.ton_api_key

    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as http:
            async with http.get(url, params=params, headers=headers) as response:
                if response.status >= 400:
                    log.warning("TON API ответил %s", response.status)
                    return []
                data = await response.json(content_type=None)
    except Exception as e:  # noqa: BLE001 — сеть
        log.warning("TON API недоступен: %s", e)
        return []
    return parse_transactions(data)


def parse_transactions(data: Any) -> list[dict]:
    """Разбор ответа TON API. Формы toncenter и tonapi отличаются — берём обе."""
    raw = data.get("transactions", data) if isinstance(data, dict) else data
    if not isinstance(raw, list):
        return []

    found = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        message = item.get("in_msg") or item.get("inMsg")
        if not isinstance(message, dict):
            continue
        nano = _nano(message.get("value"))
        if not nano:
            continue
        found.append({
            "comment": _comment(message),
            "nano": nano,
            "ton": round(nano / NANO, 6),
            "hash": str(item.get("hash") or item.get("transaction_id") or ""),
            "source": _address(message.get("source")),
        })
    return found


def _nano(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    if isinstance(value, dict):          # у некоторых API {"grams": "..."}
        return _nano(value.get("grams") or value.get("value"))
    return 0


def _comment(message: dict) -> str:
    content = message.get("message_content")
    if isinstance(content, dict):
        decoded = content.get("decoded")
        if isinstance(decoded, dict) and decoded.get("comment"):
            return str(decoded["comment"]).strip()
    body = message.get("decoded_body")
    if isinstance(body, dict):
        for key in ("text", "comment"):
            if body.get(key):
                return str(body[key]).strip()
    for key in ("comment", "message", "decoded_comment"):
        if isinstance(message.get(key), str) and message[key]:
            return message[key].strip()
    return ""


def _address(source: Any) -> str:
    if isinstance(source, str):
        return source
    if isinstance(source, dict):
        return str(source.get("address") or "")
    return ""


def match(transactions: list[dict], comment: str, expected_ton: float) -> dict | None:
    """Перевод с нужным комментарием и суммой не ниже ожидаемой (с допуском)."""
    least = expected_ton * (1 - settings.ton_tolerance)
    for tx in transactions:
        if tx["comment"] == comment and tx["ton"] >= least:
            return tx
    return None


# ----------------------------------------------------------------- проверка

async def check_pending(bot) -> int:
    """Пройтись по неоплаченным TON-заказам. Возвращает число подтверждённых."""
    waiting = await db.pending_ton_orders()
    if not waiting:
        return 0

    transactions = await incoming()
    confirmed = 0
    for order in waiting:
        payment = match(transactions, order["ton_comment"], order["ton_amount"])
        if payment:
            await db.set_ton_payment(order["id"], payment["hash"])
            if await db.mark_paid(order["id"], payment["hash"], "TON"):
                confirmed += 1
                await _on_paid(bot, order["id"])
        elif _expired(order):
            await db.set_status(order["id"], "cancelled")
            await _tell(bot, order["user_id"],
                        f"⌛️ Счёт по заказу #{order['id']} истёк. "
                        f"Если вы уже отправили перевод — напишите нам, разберёмся.")
    return confirmed


def _expired(order: dict) -> bool:
    from datetime import datetime, timedelta
    created = datetime.fromisoformat(order["created_at"])
    return datetime.now() - created > timedelta(seconds=settings.ton_invoice_ttl)


async def _on_paid(bot, order_id: int) -> None:
    import stars

    order = await db.get_order(order_id)
    await _tell(bot, order["user_id"],
                f"✅ Оплата по заказу <b>#{order_id}</b> получена.")
    if order["stars_qty"]:
        await stars.fulfil(bot, order_id)


async def _tell(bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id, text)
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось написать %s: %s", chat_id, e)


async def watcher(bot) -> None:
    """Фоновая задача бота: раз в TON_CHECK_INTERVAL проверяет платежи."""
    log.info("Слежу за кошельком %s каждые %s с",
             settings.ton_wallet, settings.ton_check_interval)
    while True:
        try:
            confirmed = await check_pending(bot)
            if confirmed:
                log.info("Подтверждено оплат: %s", confirmed)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — цикл не должен умирать
            log.exception("Проверка платежей сорвалась: %s", e)
        await asyncio.sleep(settings.ton_check_interval)
