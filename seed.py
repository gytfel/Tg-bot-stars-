"""Демо-каталог для быстрой проверки. Запуск: python seed.py

Для цифрового магазина у каждого товара заполнено то, что бот выдаёт
покупателю после оплаты.
"""

import asyncio

import database as db
from config import settings

DIGITAL = {
    "📚 Курсы": [
        ("Python с нуля", "12 уроков, доступ навсегда.", 2900,
         "Доступ к курсу: https://example.com/python\nКод: PY-DEMO-2026"),
        ("Telegram-боты за неделю", "7 занятий и разбор кода.", 3900,
         "Доступ к курсу: https://example.com/bots\nКод: TG-DEMO-2026"),
    ],
    "🧩 Шаблоны": [
        ("Набор Notion-шаблонов", "20 шаблонов для работы и учёбы.", 990,
         "Скачать: https://example.com/notion-pack"),
        ("Пресеты для Lightroom", "15 пресетов, RAW и JPEG.", 690,
         "Скачать: https://example.com/presets"),
    ],
    "💬 Консультации": [
        ("Разбор проекта, 60 минут", "Созвон и письменные рекомендации.", 5000,
         "Спасибо! Напишите @your_username — согласуем время созвона."),
    ],
}

PHYSICAL = {
    "☕ Кофе": [
        ("Эфиопия Иргачеффе", "Зерно, средняя обжарка, 250 г. Ноты цитруса и жасмина.", 890, None),
        ("Бразилия Сантос", "Зерно, тёмная обжарка, 250 г. Шоколад и орех.", 690, None),
    ],
    "🍫 Сладкое": [
        ("Тёмный шоколад 70%", "Плитка 100 г без добавленного сахара.", 320, None),
        ("Набор макарон", "12 штук, ассорти вкусов.", 1290, None),
    ],
}


async def main() -> None:
    await db.init_db()
    if settings.stars_shop:
        print("Режим продажи звёзд — каталог не нужен: количество покупатель "
              "выбирает сам.\nПрайс: python manage.py stars price")
        return
    if await db.get_categories(only_active=False):
        print("В базе уже есть категории — пропускаю.")
        return

    demo = DIGITAL if settings.digital else PHYSICAL
    for cat_title, products in demo.items():
        cat_id = await db.add_category(cat_title)
        for title, desc, price, content in products:
            await db.add_product(cat_id, title, desc, price, None,
                                 stock=999 if settings.digital else 25,
                                 content=content)
    kind = "цифровой" if settings.digital else "физический"
    print(f"✅ Демо-каталог создан ({kind} магазин).")


if __name__ == "__main__":
    asyncio.run(main())
