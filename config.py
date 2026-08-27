"""Настройки бота: читаются из .env"""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

STARS_CURRENCY = "XTR"


def _parse_admins() -> list[int]:
    raw = os.getenv("ADMIN_IDS", "")
    return [int(x) for x in raw.replace(" ", "").split(",") if x.strip().isdigit()]


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "").replace(",", ".") or default)
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


@dataclass
class Settings:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    admin_ids: list[int] = field(default_factory=_parse_admins)
    shop_name: str = os.getenv("SHOP_NAME", "Магазин")
    currency: str = os.getenv("CURRENCY", "₽")
    db_path: str = os.getenv("DB_PATH", "shop.db")
    support: str = os.getenv("SUPPORT_CONTACT", "")
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()

    # --- оплата -------------------------------------------------------------
    payment_token: str = os.getenv("PAYMENT_PROVIDER_TOKEN", "")
    payment_currency: str = os.getenv("PAYMENT_CURRENCY_CODE", "RUB").upper()
    # сколько единиц валюты магазина стоит одна ⭐ (для режима Telegram Stars)
    stars_rate: float = _float("STARS_RATE", 2.0)

    # --- подключение к серверу ---------------------------------------------
    # polling — бот сам ходит в Telegram (проще, работает без домена)
    # webhook — Telegram стучится в наш сервер (нужен домен + HTTPS)
    mode: str = os.getenv("BOT_MODE", "polling").lower()
    webhook_base: str = os.getenv("WEBHOOK_URL", "").rstrip("/")
    webhook_path: str = os.getenv("WEBHOOK_PATH", "/webhook")
    webhook_secret: str = os.getenv("WEBHOOK_SECRET", "")
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = _int("PORT", 8080)
    # если сервер ходит в интернет только через прокси: http://user:pass@host:port
    proxy: str = os.getenv("TELEGRAM_PROXY", "")

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids

    # --- производные значения ----------------------------------------------

    @property
    def stars_mode(self) -> bool:
        """Оплата в Telegram Stars: провайдер не нужен, валюта XTR."""
        return self.payment_currency == STARS_CURRENCY

    @property
    def online_enabled(self) -> bool:
        """Показывать ли кнопку онлайн-оплаты."""
        return self.stars_mode or bool(self.payment_token)

    @property
    def webhook_url(self) -> str:
        if not self.webhook_base:
            return ""
        return f"{self.webhook_base}{self.webhook_path}"

    def validate(self) -> list[str]:
        """Список проблем в конфигурации (пустой список — всё в порядке)."""
        problems: list[str] = []
        if not self.bot_token:
            problems.append("BOT_TOKEN не задан")
        elif ":" not in self.bot_token:
            problems.append("BOT_TOKEN выглядит некорректно (нет двоеточия)")
        if not self.admin_ids:
            problems.append("ADMIN_IDS пуст — админ-панель будет недоступна")
        if self.mode not in {"polling", "webhook"}:
            problems.append(f"BOT_MODE={self.mode!r}: допустимо polling или webhook")
        if self.mode == "webhook":
            if not self.webhook_base:
                problems.append("BOT_MODE=webhook, но WEBHOOK_URL не задан")
            elif not self.webhook_base.startswith("https://"):
                problems.append("WEBHOOK_URL должен начинаться с https:// — "
                                "Telegram не примет http")
        if self.stars_mode and self.payment_token:
            problems.append("Для Telegram Stars токен провайдера не нужен — очистите "
                            "PAYMENT_PROVIDER_TOKEN")
        if self.stars_mode and self.stars_rate <= 0:
            problems.append("STARS_RATE должен быть больше нуля")
        return problems


settings = Settings()
