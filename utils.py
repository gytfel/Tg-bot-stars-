"""Мелкие помощники: форматирование и словари статусов."""

from config import settings

STATUSES = {
    "new": "🆕 Новый",
    "paid": "💰 Оплачен",
    "shipped": "🚚 Отправлен",
    "done": "✅ Выполнен",
    "cancelled": "❌ Отменён",
}

PAYMENTS = {
    "cash": "💵 При получении",
    "transfer": "🏦 Перевод на карту",
    "online": "💳 Онлайн-оплата",
}


def money(value: float) -> str:
    """1500.0 -> '1 500 ₽', 199.5 -> '199.50 ₽'"""
    if float(value).is_integer():
        body = f"{int(value):,}".replace(",", " ")
    else:
        body = f"{value:,.2f}".replace(",", " ")
    return f"{body} {settings.currency}"


def escape(text: str | None) -> str:
    """Экранирование для parse_mode=HTML."""
    if not text:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
