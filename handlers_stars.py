"""Покупка Telegram Stars: количество → получатель → счёт в TON → зачисление."""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import database as db
import keyboards as kb
import stars
import ton
from config import settings
from utils import escape, money

router = Router()
log = logging.getLogger(__name__)


class Buy(StatesGroup):
    quantity = State()
    recipient = State()
    confirm = State()


# ------------------------------------------------------------------- начало

@router.message(F.text == "⭐ Купить звёзды")
@router.message(Command("buy"))
async def buy_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(_intro(), reply_markup=kb.star_packages_kb())


@router.callback_query(F.data == "st_start")
async def buy_start_cb(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await _replace(callback, _intro(), kb.star_packages_kb())
    await callback.answer()


def _intro() -> str:
    return (f"⭐ <b>Покупка звёзд</b>\n\n"
            f"Цена: <b>{money(settings.star_price)}</b> за звезду\n"
            f"Минимум: <b>{settings.min_stars} ⭐</b>\n\n"
            f"Выберите набор или введите своё количество:")


@router.callback_query(F.data.startswith("st_qty_"))
async def pick_package(callback: CallbackQuery, state: FSMContext):
    quantity = int(callback.data.rsplit("_", 1)[1])
    await _ask_recipient(callback, state, quantity)


@router.callback_query(F.data == "st_custom")
async def ask_custom(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Buy.quantity)
    await callback.message.answer(
        f"Сколько звёзд? Введите число — минимум {settings.min_stars}.",
        reply_markup=kb.cancel_kb())
    await callback.answer()


@router.message(Buy.quantity)
async def custom_quantity(message: Message, state: FSMContext):
    quantity, error = stars.validate_quantity(message.text)
    if error:
        await message.answer(error)
        return
    await _ask_recipient(message, state, quantity)


# ---------------------------------------------------------------- получатель

async def _ask_recipient(event: Message | CallbackQuery, state: FSMContext,
                         quantity: int) -> None:
    await state.update_data(quantity=quantity)
    await state.set_state(Buy.recipient)

    username = event.from_user.username
    text = (f"<b>{quantity} ⭐</b> — {money(stars.price_rub(quantity))}\n\n"
            f"Кому зачислить звёзды? Пришлите @username получателя"
            f"{' или нажмите кнопку ниже.' if username else '.'}")
    if not username:
        text += ("\n\nУ вас не задан @username — звёзды нельзя зачислить на аккаунт "
                 "без него. Задайте его в настройках Telegram или укажите чужой.")

    markup = kb.star_recipient_kb(username)
    if isinstance(event, CallbackQuery):
        await _replace(event, text, markup)
        await event.answer()
    else:
        await event.answer(text, reply_markup=markup)


@router.callback_query(Buy.recipient, F.data == "st_me")
async def recipient_me(callback: CallbackQuery, state: FSMContext):
    await _confirm(callback, state, callback.from_user.username)


@router.message(Buy.recipient)
async def recipient_typed(message: Message, state: FSMContext):
    username, error = stars.normalize_username(message.text)
    if error:
        await message.answer(error)
        return
    await _confirm(message, state, username)


# ------------------------------------------------------------- подтверждение

async def _confirm(event: Message | CallbackQuery, state: FSMContext,
                   recipient: str) -> None:
    data = await state.get_data()
    quantity = data["quantity"]
    price = stars.price_rub(quantity)
    await state.update_data(recipient=recipient)
    await state.set_state(Buy.confirm)

    text = (f"<b>Проверьте заказ</b>\n\n"
            f"⭐ Количество: <b>{quantity}</b>\n"
            f"👤 Получатель: <b>@{escape(recipient)}</b>\n"
            f"💰 К оплате: <b>{money(price)}</b>\n\n")

    if settings.ton_enabled:
        try:
            rate = await ton.rate_rub()
            text += (f"💎 В TON по курсу {money(rate)} за 1 TON: "
                     f"<b>{ton.to_ton(price, rate)} TON</b>")
        except Exception as e:  # noqa: BLE001 — курс недоступен
            log.warning("Курс TON недоступен: %s", e)
            text += "💎 Сумму в TON посчитаем при выставлении счёта."

    markup = kb.star_confirm_kb()
    if isinstance(event, CallbackQuery):
        await _replace(event, text, markup)
        await event.answer()
    else:
        await event.answer(text, reply_markup=markup)


@router.callback_query(Buy.confirm, F.data == "st_cancel")
async def cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await _replace(callback, "Заказ отменён.", None)
    await callback.message.answer(
        "Что дальше?",
        reply_markup=kb.main_menu(settings.is_admin(callback.from_user.id)))
    await callback.answer()


# ------------------------------------------------------------------- оплата

@router.callback_query(Buy.confirm, F.data == "st_pay")
async def create_invoice(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    quantity, recipient = data["quantity"], data["recipient"]
    price = stars.price_rub(quantity)

    if not settings.ton_enabled:
        await callback.answer("Оплата пока не настроена, напишите нам", show_alert=True)
        return

    try:
        rate = await ton.rate_rub()
    except Exception as e:  # noqa: BLE001
        log.error("Курс TON недоступен: %s", e)
        await callback.answer("Не удалось получить курс TON, попробуйте позже",
                              show_alert=True)
        return

    amount = ton.to_ton(price, rate)
    order_id = await db.create_star_order(
        callback.from_user.id, quantity, recipient, price, payment="ton",
        ton_amount=amount, ton_comment="")
    # комментарий содержит номер заказа, поэтому проставляем его после вставки
    await db.set_ton_comment(order_id, ton.comment_for(order_id))
    order = await db.get_order(order_id)

    await state.clear()
    await _replace(callback,
                   f"🧾 <b>Заказ #{order_id}</b>: {quantity} ⭐ на @{escape(recipient)}\n\n"
                   f"{ton.invoice_text(order)}",
                   kb.ton_invoice_kb(order_id))
    await callback.answer()


@router.callback_query(F.data.startswith("st_check_"))
async def check_payment(callback: CallbackQuery, bot: Bot):
    order_id = int(callback.data.rsplit("_", 1)[1])
    order = await db.get_order(order_id)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    if order["delivered_at"]:
        await callback.answer("Заказ уже выполнен ⭐", show_alert=True)
        return
    if order["status"] != "pending":
        await callback.answer("Оплата получена, зачисляем звёзды", show_alert=True)
        return

    await callback.answer("Проверяю переводы…")
    confirmed = await ton.check_pending(bot)
    if not confirmed:
        await callback.message.answer(
            "Перевода пока не видно. Если вы только что отправили — подождите "
            "минуту и нажмите проверку ещё раз.\n\n"
            "Частая причина: перевод ушёл без комментария "
            f"<code>{order['ton_comment']}</code>.")


@router.callback_query(F.data.startswith("st_drop_"))
async def drop_order(callback: CallbackQuery):
    order_id = int(callback.data.rsplit("_", 1)[1])
    order = await db.get_order(order_id)
    if not order or order["user_id"] != callback.from_user.id:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    if order["status"] != "pending":
        await callback.answer("Этот заказ уже оплачен", show_alert=True)
        return
    await db.set_status(order_id, "cancelled")
    await _replace(callback, f"Заказ #{order_id} отменён.", None)
    await callback.answer()


# ------------------------------------------------------------------ утилиты

async def _replace(callback: CallbackQuery, text: str, markup) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception:  # noqa: BLE001 — сообщение с фото или уже изменено
        await callback.message.answer(text, reply_markup=markup)
