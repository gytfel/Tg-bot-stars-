"""Закупка Telegram Stars через Fragment.

У Fragment нет официального публичного API: автозакупка делается через сторонний
шлюз, который сам ходит на fragment.com с вашим TON-кошельком. Поэтому здесь два
режима, они переключаются в `.env`:

* `FRAGMENT_MODE=manual` — бот только ставит задачу админу («выдать 500 ⭐ @user»),
  покупку админ делает руками на fragment.com и подтверждает выдачу. Работает
  сразу и ничего не требует.
* `FRAGMENT_MODE=api` — бот сам вызывает шлюз. Адрес, токен и пути настраиваются,
  потому что у разных шлюзов они отличаются.

Ответы шлюзов тоже отличаются, поэтому разбор терпимый: успех определяется по
HTTP-коду и по типичным полям (`ok`, `success`, `status`), идентификатор
операции — по `id` / `order_id` / `transaction_id`.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from config import settings

log = logging.getLogger(__name__)

OK_KEYS = ("ok", "success", "result")
ID_KEYS = ("id", "order_id", "orderId", "transaction_id", "transactionId", "reference")
ERROR_KEYS = ("error", "message", "detail", "description", "error_message")
BALANCE_KEYS = ("balance", "amount", "available", "stars", "ton")


@dataclass(slots=True)
class Purchase:
    """Результат попытки купить звёзды."""

    ok: bool
    reference: str | None = None      # номер операции на стороне шлюза
    error: str | None = None
    retriable: bool = False           # есть ли смысл повторить
    manual: bool = False              # нужна ручная выдача

    def __str__(self) -> str:
        if self.ok:
            return f"куплено, операция {self.reference or '—'}"
        return self.error or "неизвестная ошибка"


class ManualFragment:
    """Ручной режим: покупку делает человек."""

    mode = "manual"

    async def buy_stars(self, username: str, quantity: int, reference: str) -> Purchase:
        return Purchase(ok=False, manual=True,
                        error="ручной режим: закупку подтверждает админ")

    async def balance(self) -> float | None:
        return None


class ApiFragment:
    """Автозакупка через сторонний шлюз к Fragment."""

    mode = "api"

    def __init__(self, url: str, token: str, buy_path: str, balance_path: str,
                 timeout: int) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.buy_path = buy_path
        self.balance_path = balance_path
        self.timeout = timeout

    # --------------------------------------------------------------- запросы

    async def buy_stars(self, username: str, quantity: int, reference: str) -> Purchase:
        payload = {"username": username, "quantity": quantity, "reference": reference}
        status, data, error = await self._request("POST", self.buy_path, json=payload)

        if error:
            return Purchase(ok=False, error=error, retriable=True)
        if status >= 500 or status == 429:
            return Purchase(ok=False, retriable=True,
                            error=f"шлюз ответил {status}: {_error_of(data)}")
        if status >= 400:
            return Purchase(ok=False, retriable=False,
                            error=f"шлюз отклонил запрос ({status}): {_error_of(data)}")
        if not _is_ok(data):
            return Purchase(ok=False, retriable=False,
                            error=_error_of(data) or "шлюз не подтвердил покупку")
        return Purchase(ok=True, reference=_id_of(data))

    async def balance(self) -> float | None:
        status, data, error = await self._request("GET", self.balance_path)
        if error or status >= 400:
            log.warning("Баланс Fragment недоступен: %s", error or status)
            return None
        return _number_of(data)

    async def _request(self, method: str, path: str,
                       json: dict | None = None) -> tuple[int, Any, str | None]:
        import aiohttp

        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        timeout = aiohttp.ClientTimeout(total=self.timeout)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as http:
                async with http.request(method, f"{self.url}{path}",
                                        json=json, headers=headers) as response:
                    body = await _read(response)
                    return response.status, body, None
        except asyncio.TimeoutError:
            return 0, None, f"шлюз не ответил за {self.timeout} с"
        except Exception as e:  # noqa: BLE001 — сеть, DNS, TLS
            return 0, None, f"не достучались до шлюза: {e}"


# ------------------------------------------------------------------ разбор

async def _read(response) -> Any:
    try:
        return await response.json(content_type=None)
    except Exception:  # noqa: BLE001 — шлюз ответил не JSON
        return (await response.text())[:300]


def _is_ok(data: Any) -> bool:
    if isinstance(data, bool):
        return data
    if isinstance(data, str):
        # шлюз ответил не JSON: подтверждением считаем только явное «ок»
        return data.strip().lower() in {"ok", "success", "true", "done"}
    if not isinstance(data, dict):
        return False
    for key in OK_KEYS:
        if key in data:
            value = data[key]
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in {"ok", "success", "completed", "done", "true"}
            if isinstance(value, dict):
                return True
    if isinstance(data.get("status"), str):
        return data["status"].lower() in {"ok", "success", "completed", "done", "paid"}
    # шлюз вернул только идентификатор операции — считаем это успехом
    return _id_of(data) is not None and not _error_of(data)


def _id_of(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in ID_KEYS:
        if data.get(key) not in (None, ""):
            return str(data[key])
    nested = data.get("result") or data.get("data")
    return _id_of(nested) if isinstance(nested, dict) else None


def _error_of(data: Any) -> str:
    if isinstance(data, str):
        return data.strip()
    if not isinstance(data, dict):
        return ""
    for key in ERROR_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            return _error_of(value)
    return ""


def _number_of(data: Any) -> float | None:
    if isinstance(data, (int, float)):
        return float(data)
    if not isinstance(data, dict):
        return None
    for key in BALANCE_KEYS:
        value = data.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                continue
    nested = data.get("result") or data.get("data")
    return _number_of(nested) if isinstance(nested, dict) else None


# ------------------------------------------------------------------- фабрика

def get_client():
    """Клиент по текущим настройкам."""
    if settings.fragment_auto:
        return ApiFragment(settings.fragment_url, settings.fragment_token,
                           settings.fragment_buy_path, settings.fragment_balance_path,
                           settings.fragment_timeout)
    return ManualFragment()
