"""Демо-товары для быстрой проверки. Запуск: python seed.py"""

import asyncio

import database as db

DEMO = {
    "☕ Кофе": [
        ("Эфиопия Иргачеффе", "Зерно, средняя обжарка, 250 г. Ноты цитруса и жасмина.", 890),
        ("Бразилия Сантос", "Зерно, тёмная обжарка, 250 г. Шоколад и орех.", 690),
    ],
    "🍫 Сладкое": [
        ("Тёмный шоколад 70%", "Плитка 100 г без добавленного сахара.", 320),
        ("Набор макарон", "12 штук, ассорти вкусов.", 1290),
    ],
}


async def main() -> None:
    await db.init_db()
    if await db.get_categories(only_active=False):
        print("В базе уже есть категории — пропускаю.")
        return
    for cat_title, products in DEMO.items():
        cat_id = await db.add_category(cat_title)
        for title, desc, price in products:
            await db.add_product(cat_id, title, desc, price, None, stock=25)
    print("✅ Демо-каталог создан.")


if __name__ == "__main__":
    asyncio.run(main())
