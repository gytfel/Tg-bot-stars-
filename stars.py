"""Продажа Telegram Stars: цена, проверка данных и выдача заказа.

Цена считается в рублях (`STAR_PRICE` за одну ⭐), оплата принимается в TON,
закупка идёт через Fragment — см. `fragment.py` и `ton.py`.
"""

import asyncio
import logging
import re

import database as db
import fragment
import keyboards as kb
from config import settings
from utils import escape, money

log = logging.getLogger(__name__)

USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
RETRY_DELAYS = (2, 5, 15)     # пауза перед повтором, секунды


# ---------------------------------------------------------------------- цена

def price_rub(quantity: int) -> float:
    return round(quantity * settings.star_price, 2)


def price_text(quantity: int) -> str:
    return f"{quantity} ⭐ — {money(price_rub(quantity))}"


# ------------------------------------------------------------------ проверки

def validate_quantity(raw: str | int | None) -> tuple[int | None, str | None]:
    """Сколько звёзд заказывают. Возвращает (количество, текст ошибки)."""
    digits = "".join(c for c in str(raw or "") if c.isdigit())
    if not digits:
        return None, "Введите количество звёзд числом, например 100."
    quantity = int(digits)
    if quantity < settings.min_stars:
        return None, (f"Минимальный заказ — {settings.min_stars} ⭐ "
                      f"(меньше не продаёт сам Fragment).")
    if quantity > settings.max_stars:
        return None, f"За раз можно купить не больше {settings.max_stars} ⭐."
    return quantity, None


def normalize_username(raw: str | None) -> tuple[str | None, str | None]:
    """@User_name / t.me/user → user_name. Возвращает (username, текст ошибки)."""
    value = (raw or "").strip()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/", "@"):
        if value.lower().startswith(prefix):
            value = value[len(prefix):]
            break
    value = value.strip().rstrip("/")
    if not value:
        return None, "Пришлите @username получателя."
    if not USERNAME_RE.match(value):
        return None, ("Не похоже на @username. Он состоит из латинских букв, цифр "
                      "и подчёркиваний, минимум 5 символов.")
    return value, None


# ------------------------------------------------------------------- выдача

async def fulfil(bot, order_id: int) -> fragment.Purchase:
    """Купить звёзды по оплаченному заказу и зачислить получателю.

    Идемпотентно: выданный заказ второй раз не покупается. При временных сбоях
    шлюза делает несколько попыток, потом зовёт админа — деньги не теряются.
    """
    order = await db.get_order(order_id)
    if not order:
        return fragment.Purchase(ok=False, error=f"заказа #{order_id} нет")
    if order["delivered_at"]:
        return fragment.Purchase(ok=True, reference=order["fragment_ref"],
                                 error="уже выдан")
    if not order["stars_qty"]:
        return fragment.Purchase(ok=False, error="это не заказ на звёзды")

    client = fragment.get_client()
    quantity, recipient = order["stars_qty"], order["recipient"]
    result = await _buy_with_retries(client, recipient, quantity, order_id)

    if result.ok:
        await db.set_fragment_result(order_id, reference=result.reference)
        await db.mark_delivered(order_id)
        await _tell(bot, order["user_id"],
                    f"🌟 Готово! {quantity} ⭐ зачислены на @{escape(recipient)}.\n"
                    f"Заказ <b>#{order_id}</b> закрыт.")
        await _tell_admins(bot, f"✅ Заказ #{order_id}: {quantity} ⭐ → @{escape(recipient)}"
                                f"{f', операция {result.reference}' if result.reference else ''}")
        log.info("Заказ #%s выдан: %s ⭐ → @%s", order_id, quantity, recipient)
        return result

    await db.set_fragment_result(order_id, error=result.error)

    if result.manual:
        await _tell(bot, order["user_id"],
                    f"Оплата по заказу <b>#{order_id}</b> получена ✅\n"
                    f"{quantity} ⭐ зачислим на @{escape(recipient)} в ближайшее время.")
        await _tell_admins(
            bot, f"🛒 <b>Купить вручную</b>\n\nЗаказ #{order_id}: <b>{quantity} ⭐</b> "
                 f"на @{escape(recipient)}\nОплачено: {money(order['total'])}\n\n"
                 f"Купите звёзды на fragment.com и подтвердите выдачу — кнопкой ниже "
                 f"или командой <code>python manage.py stars fulfil {order_id} --manual</code>",
            markup=kb.admin_star_order_kb(order_id))
    else:
        await _tell(bot, order["user_id"],
                    f"Оплата по заказу <b>#{order_id}</b> получена ✅\n"
                    f"С зачислением возникла заминка — уже разбираемся, "
                    f"звёзды придут в ближайшее время.")
        await _tell_admins(bot, f"⚠️ Заказ #{order_id}: не удалось купить {quantity} ⭐ "
                                f"для @{escape(recipient)}.\nПричина: {escape(str(result))}",
                           markup=kb.admin_star_order_kb(order_id))
        log.error("Заказ #%s не выдан: %s", order_id, result.error)
    return result


async def _buy_with_retries(client, recipient: str, quantity: int,
                            order_id: int) -> fragment.Purchase:
    reference = f"order_{order_id}"
    attempts = max(1, settings.fragment_retries)
    result = fragment.Purchase(ok=False, error="попыток не было")

    for attempt in range(attempts):
        result = await client.buy_stars(recipient, quantity, reference)
        if result.ok or not result.retriable:
            return result
        if attempt < attempts - 1:
            delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
            log.warning("Заказ #%s: %s. Повтор через %s с", order_id, result.error, delay)
            await asyncio.sleep(delay)
    return result


async def deliver_manually(bot, order_id: int, reference: str | None = None) -> bool:
    """Админ купил звёзды сам: отметить заказ выданным и сказать покупателю."""
    order = await db.get_order(order_id)
    if not order or order["delivered_at"]:
        return False
    await db.set_fragment_result(order_id, reference=reference or "вручную")
    await db.mark_delivered(order_id)
    await _tell(bot, order["user_id"],
                f"🌟 Готово! {order['stars_qty']} ⭐ зачислены на "
                f"@{escape(order['recipient'])}.\nЗаказ <b>#{order_id}</b> закрыт.")
    return True


# ------------------------------------------------------------------ рассылка

async def _tell(bot, chat_id: int, text: str, markup=None) -> bool:
    try:
        await bot.send_message(chat_id, text, reply_markup=markup)
        return True
    except Exception as e:  # noqa: BLE001 — заблокировал бота и т.п.
        log.warning("Не удалось написать %s: %s", chat_id, e)
        return False


async def _tell_admins(bot, text: str, markup=None) -> None:
    for admin_id in settings.admin_ids:
        await _tell(bot, admin_id, text, markup)
