"""Хендлеры покупателя: каталог, корзина, оформление и оплата заказа."""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, LabeledPrice, Message,
                           PreCheckoutQuery, ReplyKeyboardRemove)

import database as db
import keyboards as kb
from config import settings
from utils import PAYMENTS, STATUSES, escape, money, stars, to_stars

router = Router()
log = logging.getLogger(__name__)


class Checkout(StatesGroup):
    name = State()
    phone = State()
    address = State()
    comment = State()
    payment = State()
    confirm = State()


# --------------------------------------------------------------------- старт

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await db.upsert_user(message.from_user.id, message.from_user.username,
                         message.from_user.full_name)
    await message.answer(
        f"👋 Привет, {escape(message.from_user.first_name)}!\n\n"
        f"Добро пожаловать в <b>{escape(settings.shop_name)}</b>.\n"
        f"Выберите товар в каталоге и оформите заказ прямо здесь.",
        reply_markup=kb.main_menu(settings.is_admin(message.from_user.id)),
    )


@router.message(Command("help"))
@router.message(F.text == "ℹ️ О магазине")
async def about(message: Message):
    text = (f"<b>{escape(settings.shop_name)}</b>\n\n"
            "🛍 «Каталог» — выбрать товары\n"
            "🛒 «Корзина» — оформить заказ\n"
            "📦 «Мои заказы» — статус ваших заказов\n")
    if settings.support:
        text += f"\n💬 Связь с нами: {escape(settings.support)}"
    await message.answer(text)


@router.message(F.text == "❌ Отмена")
async def cancel_any(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.",
                         reply_markup=kb.main_menu(settings.is_admin(message.from_user.id)))


# ------------------------------------------------------------------- каталог

@router.message(F.text == "🛍 Каталог")
@router.message(Command("catalog"))
async def catalog_msg(message: Message):
    cats = await db.get_categories()
    if not cats:
        await message.answer("Каталог пока пуст 🙁")
        return
    await message.answer("Выберите категорию:", reply_markup=kb.categories_kb(cats))


@router.callback_query(F.data == "catalog")
async def catalog_cb(callback: CallbackQuery):
    cats = await db.get_categories()
    await _replace(callback, "Выберите категорию:", kb.categories_kb(cats))
    await callback.answer()


@router.callback_query(F.data.startswith("cat_"))
async def show_products(callback: CallbackQuery):
    cat_id = int(callback.data.split("_")[1])
    category = await db.get_category(cat_id)
    products = await db.get_products(cat_id)
    if not products:
        await callback.answer("В этой категории пока нет товаров", show_alert=True)
        return
    title = escape(category["title"]) if category else "Товары"
    await _replace(callback, f"<b>{title}</b>\nВыберите товар:",
                   kb.products_kb(products))
    await callback.answer()


@router.callback_query(F.data.startswith("prod_"))
async def show_product(callback: CallbackQuery):
    product = await db.get_product(int(callback.data.split("_")[1]))
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    caption = (f"<b>{escape(product['title'])}</b>\n\n"
               f"{escape(product['description'])}\n\n"
               f"💰 Цена: <b>{money(product['price'])}</b>\n"
               f"📦 В наличии: {product['stock']} шт.")

    try:
        await callback.message.delete()
    except Exception:
        pass

    if product["photo_id"]:
        await callback.message.answer_photo(product["photo_id"], caption=caption,
                                            reply_markup=kb.product_kb(product))
    else:
        await callback.message.answer(caption, reply_markup=kb.product_kb(product))
    await callback.answer()


@router.callback_query(F.data.startswith("add_"))
async def add_to_cart(callback: CallbackQuery):
    product_id = int(callback.data.split("_")[1])
    product = await db.get_product(product_id)
    if not product or not product["is_active"] or product["stock"] <= 0:
        await callback.answer("Товара нет в наличии", show_alert=True)
        return
    await db.add_to_cart(callback.from_user.id, product_id)
    await callback.answer(f"✅ «{product['title']}» добавлен в корзину", show_alert=False)


# ------------------------------------------------------------------- корзина

def _cart_text(items: list[dict]) -> str:
    lines = ["<b>🛒 Ваша корзина</b>\n"]
    for i in items:
        lines.append(f"• {escape(i['title'])} — {i['quantity']} × {money(i['price'])} "
                     f"= <b>{money(i['price'] * i['quantity'])}</b>")
    lines.append(f"\n<b>Итого: {money(db.cart_total(items))}</b>")
    return "\n".join(lines)


@router.message(F.text == "🛒 Корзина")
@router.message(Command("cart"))
async def cart_msg(message: Message):
    items = await db.get_cart(message.from_user.id)
    if not items:
        await message.answer("Корзина пуста 🛒\nЗагляните в каталог!")
        return
    await message.answer(_cart_text(items), reply_markup=kb.cart_kb(items))


async def _refresh_cart(callback: CallbackQuery):
    items = await db.get_cart(callback.from_user.id)
    if not items:
        await _replace(callback, "Корзина пуста 🛒", kb.categories_kb(
            await db.get_categories()))
        return
    await _replace(callback, _cart_text(items), kb.cart_kb(items))


@router.callback_query(F.data.startswith(("plus_", "minus_", "del_")))
async def cart_edit(callback: CallbackQuery):
    action, pid = callback.data.split("_")
    pid = int(pid)
    if action == "plus":
        product = await db.get_product(pid)
        current = next((i["quantity"] for i in await db.get_cart(callback.from_user.id)
                        if i["product_id"] == pid), 0)
        if product and current >= product["stock"]:
            await callback.answer(f"Больше нет в наличии: осталось {product['stock']} шт.",
                                  show_alert=True)
            return
        await db.change_qty(callback.from_user.id, pid, +1)
    elif action == "minus":
        await db.change_qty(callback.from_user.id, pid, -1)
    else:
        await db.remove_from_cart(callback.from_user.id, pid)
    await _refresh_cart(callback)
    await callback.answer()


@router.callback_query(F.data == "clear_cart")
async def cart_clear(callback: CallbackQuery):
    await db.clear_cart(callback.from_user.id)
    await _refresh_cart(callback)
    await callback.answer("Корзина очищена")


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    await callback.answer()


# ---------------------------------------------------------- оформление заказа

@router.callback_query(F.data == "checkout")
async def checkout_start(callback: CallbackQuery, state: FSMContext):
    items = await db.get_cart(callback.from_user.id)
    if not items:
        await callback.answer("Корзина пуста", show_alert=True)
        return
    await state.set_state(Checkout.name)
    await callback.message.answer("👤 Как вас зовут? (имя и фамилия)",
                                  reply_markup=kb.cancel_kb())
    await callback.answer()


@router.message(Checkout.name)
async def checkout_name(message: Message, state: FSMContext):
    if len(message.text or "") < 2:
        await message.answer("Введите, пожалуйста, имя текстом.")
        return
    await state.update_data(name=message.text.strip())
    await state.set_state(Checkout.phone)
    await message.answer("📱 Укажите номер телефона:", reply_markup=kb.phone_request())


@router.message(Checkout.phone, F.contact)
async def checkout_phone_contact(message: Message, state: FSMContext):
    await state.update_data(phone=message.contact.phone_number)
    await state.set_state(Checkout.address)
    await message.answer("🏠 Адрес доставки (город, улица, дом, квартира):",
                         reply_markup=kb.cancel_kb())


@router.message(Checkout.phone)
async def checkout_phone_text(message: Message, state: FSMContext):
    digits = "".join(c for c in (message.text or "") if c.isdigit())
    if len(digits) < 10:
        await message.answer("Похоже, номер неполный. Введите ещё раз, например +79991234567")
        return
    await state.update_data(phone=message.text.strip())
    await state.set_state(Checkout.address)
    await message.answer("🏠 Адрес доставки (город, улица, дом, квартира):",
                         reply_markup=kb.cancel_kb())


@router.message(Checkout.address)
async def checkout_address(message: Message, state: FSMContext):
    if len(message.text or "") < 5:
        await message.answer("Введите адрес подробнее.")
        return
    await state.update_data(address=message.text.strip())
    await state.set_state(Checkout.comment)
    await message.answer("💬 Комментарий к заказу? Если не нужен — напишите «-».")


@router.message(Checkout.comment)
async def checkout_comment(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    await state.update_data(comment="" if text in {"-", "нет", "Нет"} else text)
    await state.set_state(Checkout.payment)
    await message.answer("💳 Выберите способ оплаты:", reply_markup=ReplyKeyboardRemove())
    await message.answer("Способ оплаты:", reply_markup=kb.payment_kb())


@router.callback_query(Checkout.payment, F.data.startswith("pay_"))
async def checkout_payment(callback: CallbackQuery, state: FSMContext):
    method = callback.data.split("_")[1]
    await state.update_data(payment=method)
    data = await state.get_data()
    items = await db.get_cart(callback.from_user.id)
    if not items:
        await state.clear()
        await callback.answer("Корзина пуста", show_alert=True)
        return

    summary = "\n".join(
        f"• {escape(i['title'])} ×{i['quantity']} — {money(i['price'] * i['quantity'])}"
        for i in items)
    text = (f"<b>Проверьте заказ</b>\n\n{summary}\n\n"
            f"<b>Итого: {money(db.cart_total(items))}</b>\n\n"
            f"👤 {escape(data['name'])}\n"
            f"📱 {escape(data['phone'])}\n"
            f"🏠 {escape(data['address'])}\n"
            f"💳 {PAYMENTS[method]}")
    if method == "online" and settings.stars_mode:
        text += f"\n\n⭐ К оплате: <b>{stars(to_stars(db.cart_total(items)))}</b>"
    if data.get("comment"):
        text += f"\n💬 {escape(data['comment'])}"

    await state.set_state(Checkout.confirm)
    await _replace(callback, text, kb.confirm_kb())
    await callback.answer()


@router.callback_query(Checkout.confirm, F.data == "cancel_order")
async def order_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await _replace(callback, "Заказ отменён. Товары остались в корзине.", None)
    await callback.answer()


@router.callback_query(Checkout.confirm, F.data == "confirm_order")
async def order_confirm(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    items = await db.get_cart(callback.from_user.id)
    if not items:
        await state.clear()
        await callback.answer("Корзина пуста", show_alert=True)
        return

    # товар мог закончиться, пока покупатель заполнял анкету
    problems = await db.out_of_stock(items)
    if problems:
        lines = "\n".join(f"• {escape(p['title'])}: осталось {p['available']} шт."
                           for p in problems)
        await state.clear()
        await _replace(callback,
                       f"😔 Пока вы оформляли заказ, наличие изменилось:\n\n{lines}\n\n"
                       f"Поправьте корзину и попробуйте снова.", kb.cart_kb(items))
        await callback.answer()
        return

    # Онлайн-оплата: заказ создаётся со статусом «ожидает оплаты»,
    # склад и корзина не трогаются, пока Telegram не подтвердит платёж.
    if data.get("payment") == "online" and settings.online_enabled:
        order_id = await db.create_order(
            callback.from_user.id, {**data, "currency": settings.payment_currency}, items,
            status="pending", commit_stock=False, clear_cart=False)
        try:
            await bot.send_invoice(
                chat_id=callback.from_user.id,
                title=f"Заказ №{order_id} в {settings.shop_name}"[:32],
                description=", ".join(i["title"] for i in items)[:255],
                payload=f"order_{order_id}",
                provider_token=settings.payment_token or None,
                currency=settings.payment_currency,
                prices=invoice_prices(items),
            )
        except Exception as e:
            log.exception("Не удалось выставить счёт по заказу #%s: %s", order_id, e)
            await db.set_status(order_id, "cancelled")
            await callback.message.answer(
                "Не получилось выставить счёт 😔 Попробуйте другой способ оплаты "
                "или напишите нам.")
            await state.clear()
            await callback.answer()
            return
        await state.clear()
        await callback.message.answer("Счёт выставлен — оплатите его в этом чате ⬆️")
        await callback.answer()
        return

    order_id = await db.create_order(callback.from_user.id, data, items)
    await state.clear()
    await _replace(callback,
                   f"✅ Заказ <b>#{order_id}</b> принят!\n\n"
                   f"Сумма: <b>{money(db.cart_total(items))}</b>\n"
                   f"Мы свяжемся с вами по указанному номеру.", None)
    await callback.message.answer("Что дальше?",
                                  reply_markup=kb.main_menu(settings.is_admin(callback.from_user.id)))
    await notify_admins(bot, order_id)
    await callback.answer()


def invoice_prices(items: list[dict]) -> list[LabeledPrice]:
    """Позиции счёта.

    Telegram Stars (XTR): ровно одна позиция, сумма — целое число звёзд.
    Обычная валюта: сумма в минимальных единицах (копейках/центах).
    """
    total = db.cart_total(items)
    if settings.stars_mode:
        return [LabeledPrice(label=f"Заказ ({len(items)} поз.)", amount=to_stars(total))]
    return [LabeledPrice(label=f"{i['title']} ×{i['quantity']}"[:32],
                         amount=int(round(i["price"] * i["quantity"] * 100)))
            for i in items]


def order_id_from_payload(payload: str | None) -> int | None:
    if payload and payload.startswith("order_") and payload[6:].isdigit():
        return int(payload[6:])
    return None


# ------------------------------------------------------------- онлайн-оплата

@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery, bot: Bot):
    """Последняя проверка перед списанием денег: заказ есть и ещё не оплачен."""
    order_id = order_id_from_payload(query.invoice_payload)
    order = await db.get_order(order_id) if order_id else None

    if order_id and not order:
        await bot.answer_pre_checkout_query(
            query.id, ok=False, error_message="Заказ не найден, оформите его заново.")
        return
    if order and order["status"] not in {"pending", "new"}:
        await bot.answer_pre_checkout_query(
            query.id, ok=False, error_message="Этот заказ уже оплачен или отменён.")
        return
    await bot.answer_pre_checkout_query(query.id, ok=True)


@router.message(F.successful_payment)
async def on_paid(message: Message, state: FSMContext, bot: Bot):
    payment = message.successful_payment
    order_id = order_id_from_payload(payment.invoice_payload)

    if order_id and await db.get_order(order_id):
        is_new = await db.mark_paid(order_id, payment.telegram_payment_charge_id,
                                    payment.currency)
    else:
        # счёт из старой версии бота: собираем заказ из текущей корзины
        items = await db.get_cart(message.from_user.id)
        if not items:
            await message.answer("Оплата получена ✅")
            return
        data = await state.get_data()
        order_id = await db.create_order(
            message.from_user.id, {**data, "payment": "online",
                                   "currency": payment.currency}, items)
        await db.mark_paid(order_id, payment.telegram_payment_charge_id, payment.currency)
        is_new = True

    await state.clear()
    await message.answer(f"✅ Оплата получена. Заказ <b>#{order_id}</b> оформлен!",
                         reply_markup=kb.main_menu(settings.is_admin(message.from_user.id)))
    if is_new:
        await notify_admins(bot, order_id)


# ---------------------------------------------------------------- мои заказы

@router.message(F.text == "📦 Мои заказы")
@router.message(Command("orders"))
async def my_orders(message: Message):
    orders = await db.get_user_orders(message.from_user.id)
    if not orders:
        await message.answer("У вас пока нет заказов.")
        return
    lines = ["<b>📦 Ваши заказы</b>\n"]
    for o in orders:
        lines.append(f"#{o['id']} от {o['created_at'][:10]} — {money(o['total'])} — "
                     f"{STATUSES.get(o['status'], o['status'])}")
    await message.answer("\n".join(lines))


# ------------------------------------------------------------------ утилиты

async def notify_admins(bot: Bot, order_id: int) -> None:
    order = await db.get_order(order_id)
    if not order:
        return
    items = "\n".join(f"• {escape(i['title'])} ×{i['quantity']} — "
                      f"{money(i['price'] * i['quantity'])}" for i in order["items"])
    text = (f"🔔 <b>Новый заказ #{order['id']}</b>\n\n{items}\n\n"
            f"<b>Итого: {money(order['total'])}</b>\n\n"
            f"👤 {escape(order['name'])}\n"
            f"📱 {escape(order['phone'])}\n"
            f"🏠 {escape(order['address'])}\n"
            f"💳 {PAYMENTS.get(order['payment_method'], '—')}\n"
            f"💬 {escape(order['comment']) or '—'}\n"
            f"🆔 Клиент: <code>{order['user_id']}</code>")
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception as e:  # админ не запускал бота и т.п.
            log.warning("Не удалось уведомить админа %s: %s", admin_id, e)


async def _replace(callback: CallbackQuery, text: str, markup) -> None:
    """Обновить сообщение; если это фото — удалить и отправить новое."""
    if callback.message.photo:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=markup)
    else:
        try:
            await callback.message.edit_text(text, reply_markup=markup)
        except Exception:
            await callback.message.answer(text, reply_markup=markup)
