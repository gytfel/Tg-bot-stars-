"""Админ-панель: управление каталогом, заказами, рассылка."""

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.filters import BaseFilter, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import database as db
import keyboards as kb
from config import STARS_CURRENCY, settings
from utils import PAYMENTS, STATUSES, escape, money

router = Router()
log = logging.getLogger(__name__)


class IsAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return settings.is_admin(event.from_user.id)


router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


class AddCategory(StatesGroup):
    title = State()


class AddProduct(StatesGroup):
    title = State()
    description = State()
    price = State()
    photo = State()


class Broadcast(StatesGroup):
    text = State()


# ---------------------------------------------------------------- главное меню

@router.message(Command("admin"))
@router.message(F.text == "⚙️ Админ-панель")
async def admin_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("⚙️ <b>Админ-панель</b>", reply_markup=kb.admin_menu())


@router.callback_query(F.data == "a_menu")
async def admin_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("⚙️ <b>Админ-панель</b>", reply_markup=kb.admin_menu())
    await callback.answer()


# ------------------------------------------------------------------ категории

@router.callback_query(F.data == "a_cats")
async def admin_cats(callback: CallbackQuery):
    cats = await db.get_categories(only_active=False)
    await callback.message.edit_text("📂 <b>Категории</b>", reply_markup=kb.admin_cats_kb(cats))
    await callback.answer()


@router.callback_query(F.data == "a_addcat")
async def admin_addcat(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddCategory.title)
    await callback.message.answer("Введите название категории:", reply_markup=kb.cancel_kb())
    await callback.answer()


@router.message(AddCategory.title)
async def admin_addcat_save(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=kb.main_menu(True))
        return
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название нужно прислать текстом.")
        return
    await db.add_category(title)
    await state.clear()
    await message.answer(f"✅ Категория «{escape(title)}» добавлена.",
                         reply_markup=kb.main_menu(True))
    cats = await db.get_categories(only_active=False)
    await message.answer("📂 <b>Категории</b>", reply_markup=kb.admin_cats_kb(cats))


@router.callback_query(F.data.startswith("a_delcat_"))
async def admin_delcat(callback: CallbackQuery):
    await db.delete_category(int(callback.data.split("_")[-1]))
    cats = await db.get_categories(only_active=False)
    await callback.message.edit_text("📂 <b>Категории</b>", reply_markup=kb.admin_cats_kb(cats))
    await callback.answer("Удалено")


# --------------------------------------------------------------------- товары

@router.callback_query(F.data == "a_prods")
async def admin_prods(callback: CallbackQuery):
    cats = await db.get_categories(only_active=False)
    if not cats:
        await callback.answer("Сначала создайте категорию", show_alert=True)
        return
    await callback.message.edit_text("📦 Выберите категорию:",
                                     reply_markup=kb.admin_pick_cat_kb(cats, "a_cprods"))
    await callback.answer()


@router.callback_query(F.data.startswith("a_cprods_"))
async def admin_prods_list(callback: CallbackQuery):
    cat_id = int(callback.data.split("_")[-1])
    products = await db.get_products(cat_id, only_active=False)
    await callback.message.edit_text(
        "📦 <b>Товары</b>\nНажмите на товар, чтобы скрыть/показать его в каталоге.",
        reply_markup=kb.admin_prods_kb(products, cat_id))
    await callback.answer()


@router.callback_query(F.data.startswith("a_toggle_"))
async def admin_toggle(callback: CallbackQuery):
    pid = int(callback.data.split("_")[-1])
    await db.toggle_product(pid)
    product = await db.get_product(pid)
    if not product:
        await callback.answer("Товар уже удалён", show_alert=True)
        return
    products = await db.get_products(product["category_id"], only_active=False)
    await callback.message.edit_reply_markup(
        reply_markup=kb.admin_prods_kb(products, product["category_id"]))
    await callback.answer("Статус изменён")


@router.callback_query(F.data.startswith("a_delprod_"))
async def admin_delprod(callback: CallbackQuery):
    pid = int(callback.data.split("_")[-1])
    product = await db.get_product(pid)
    cat_id = product["category_id"] if product else 0
    await db.delete_product(pid)
    products = await db.get_products(cat_id, only_active=False)
    await callback.message.edit_reply_markup(reply_markup=kb.admin_prods_kb(products, cat_id))
    await callback.answer("Товар удалён")


@router.callback_query(F.data.startswith("a_addprod_"))
async def admin_addprod(callback: CallbackQuery, state: FSMContext):
    await state.update_data(category_id=int(callback.data.split("_")[-1]))
    await state.set_state(AddProduct.title)
    await callback.message.answer("1/4 — Название товара:", reply_markup=kb.cancel_kb())
    await callback.answer()


@router.message(AddProduct.title)
async def addprod_title(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=kb.main_menu(True))
        return
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название нужно прислать текстом.")
        return
    await state.update_data(title=title)
    await state.set_state(AddProduct.description)
    await message.answer("2/4 — Описание товара (или «-» чтобы пропустить):")


@router.message(AddProduct.description)
async def addprod_desc(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        await message.answer("Описание нужно прислать текстом (или «-», чтобы пропустить).")
        return
    await state.update_data(description="" if text == "-" else text)
    await state.set_state(AddProduct.price)
    await message.answer("3/4 — Цена (только число, например 1990):")


@router.message(AddProduct.price)
async def addprod_price(message: Message, state: FSMContext):
    raw = (message.text or "").replace(",", ".").replace(" ", "")
    try:
        price = float(raw)
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите цену числом, например 1990")
        return
    await state.update_data(price=price)
    await state.set_state(AddProduct.photo)
    await message.answer("4/4 — Отправьте фото товара (или «-» чтобы пропустить):")


@router.message(AddProduct.photo, F.photo)
async def addprod_photo(message: Message, state: FSMContext):
    await _save_product(message, state, message.photo[-1].file_id)


@router.message(AddProduct.photo)
async def addprod_nophoto(message: Message, state: FSMContext):
    if (message.text or "").strip() != "-":
        await message.answer("Отправьте фото или напишите «-».")
        return
    await _save_product(message, state, None)


async def _save_product(message: Message, state: FSMContext, photo_id: str | None):
    data = await state.get_data()
    await db.add_product(data["category_id"], data["title"], data["description"],
                         data["price"], photo_id)
    await state.clear()
    await message.answer(f"✅ Товар «{escape(data['title'])}» добавлен "
                         f"за {money(data['price'])}.", reply_markup=kb.main_menu(True))
    await message.answer("⚙️ <b>Админ-панель</b>", reply_markup=kb.admin_menu())


# --------------------------------------------------------------------- заказы

@router.callback_query(F.data == "a_orders")
async def admin_orders(callback: CallbackQuery):
    orders = await db.get_orders()
    if not orders:
        await callback.message.edit_text("Заказов пока нет.", reply_markup=kb.back_admin_kb())
        await callback.answer()
        return
    await callback.message.edit_text("🧾 <b>Последние заказы</b>",
                                     reply_markup=kb.admin_orders_kb(orders))
    await callback.answer()


@router.callback_query(F.data.startswith("a_order_"))
async def admin_order(callback: CallbackQuery):
    await show_order(callback, int(callback.data.split("_")[-1]))


async def show_order(callback: CallbackQuery, order_id: int) -> None:
    order = await db.get_order(order_id)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    items = "\n".join(f"• {escape(i['title'])} ×{i['quantity']} — "
                      f"{money(i['price'] * i['quantity'])}" for i in order["items"])
    text = (f"🧾 <b>Заказ #{order['id']}</b>  ({order['created_at'][:16].replace('T', ' ')})\n\n"
            f"{items}\n\n<b>Итого: {money(order['total'])}</b>\n\n"
            f"👤 {escape(order['name'])}\n"
            f"📱 {escape(order['phone'])}\n"
            f"🏠 {escape(order['address'])}\n"
            f"💳 {PAYMENTS.get(order['payment_method'], '—')}\n"
            f"💬 {escape(order['comment']) or '—'}\n"
            f"🆔 <code>{order['user_id']}</code>\n\n"
            f"Статус: <b>{STATUSES.get(order['status'], order['status'])}</b>")
    if order["charge_id"]:
        text += f"\n🧾 Платёж: <code>{order['charge_id']}</code>"
    try:
        await callback.message.edit_text(text, reply_markup=kb.admin_order_kb(order["id"]))
    except Exception:
        await callback.message.answer(text, reply_markup=kb.admin_order_kb(order["id"]))


@router.callback_query(F.data.startswith("a_status_"))
async def admin_set_status(callback: CallbackQuery, bot: Bot):
    _, _, raw_id, status = callback.data.split("_")
    order_id = int(raw_id)
    order = await db.get_order(order_id)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    await db.set_status(order_id, status)
    try:
        await bot.send_message(
            order["user_id"],
            f"Статус вашего заказа #{order_id}: <b>{STATUSES.get(status, status)}</b>")
    except Exception as e:
        log.warning("Не удалось уведомить клиента: %s", e)
    await callback.answer(f"Статус: {STATUSES.get(status, status)}")
    await show_order(callback, order_id)


# ---------------------------------------------------------------- статистика

@router.callback_query(F.data == "a_stats")
async def admin_stats(callback: CallbackQuery):
    s = await db.get_stats()
    text = ("📊 <b>Статистика</b>\n\n"
            f"👥 Пользователей: <b>{s['users']}</b>\n"
            f"📦 Товаров: <b>{s['products']}</b>\n"
            f"🧾 Заказов: <b>{s['orders']}</b> (новых: {s['new_orders']})\n"
            f"💰 Оборот: <b>{money(s['revenue'])}</b>")
    await callback.message.edit_text(text, reply_markup=kb.back_admin_kb())
    await callback.answer()


# ------------------------------------------------------------------ рассылка

@router.callback_query(F.data == "a_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Broadcast.text)
    await callback.message.answer(
        "📣 Отправьте текст рассылки. Поддерживается HTML-разметка.",
        reply_markup=kb.cancel_kb())
    await callback.answer()


@router.message(Broadcast.text)
async def admin_broadcast_send(message: Message, state: FSMContext, bot: Bot):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=kb.main_menu(True))
        return
    await state.clear()
    user_ids = await db.all_user_ids()
    sent = failed = 0
    status = await message.answer(f"Отправляю… 0/{len(user_ids)}")
    for idx, uid in enumerate(user_ids, 1):
        try:
            # copy_message переносит любой контент: текст, фото, видео, подпись
            await bot.copy_message(chat_id=uid, from_chat_id=message.chat.id,
                                   message_id=message.message_id)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # лимит Telegram ~30 сообщений/сек
        if idx % 25 == 0:
            try:
                await status.edit_text(f"Отправляю… {idx}/{len(user_ids)}")
            except Exception:
                pass
    await status.edit_text(f"📣 Рассылка завершена.\n✅ Доставлено: {sent}\n❌ Ошибок: {failed}")
    await message.answer("⚙️ <b>Админ-панель</b>", reply_markup=kb.admin_menu())


# ---------------------------------------------------------------- возвраты

@router.message(Command("refund"))
async def admin_refund(message: Message, bot: Bot):
    """/refund <номер заказа> — вернуть оплату Telegram Stars покупателю."""
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].lstrip("#").isdigit():
        await message.answer("Формат: <code>/refund 42</code> — где 42 это номер заказа.")
        return

    order = await db.get_order(int(parts[1].lstrip("#")))
    if not order:
        await message.answer("Заказ не найден.")
        return
    if not order["charge_id"]:
        await message.answer("По этому заказу нет онлайн-платежа — возврат делается вручную.")
        return
    if order["currency"] != STARS_CURRENCY:
        await message.answer("Автовозврат доступен только для Telegram Stars. "
                             "Платежи через провайдера возвращайте в его личном кабинете.")
        return

    try:
        await bot.refund_star_payment(user_id=order["user_id"],
                                      telegram_payment_charge_id=order["charge_id"])
    except Exception as e:
        log.warning("Возврат по заказу #%s не прошёл: %s", order["id"], e)
        await message.answer(f"Возврат не прошёл: {escape(str(e))}")
        return

    await db.set_status(order["id"], "cancelled")
    await message.answer(f"✅ Звёзды по заказу #{order['id']} возвращены покупателю.")
    try:
        await bot.send_message(order["user_id"],
                               f"Оплата по заказу #{order['id']} возвращена ⭐")
    except Exception as e:
        log.warning("Не удалось уведомить клиента о возврате: %s", e)
