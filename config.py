"""Настройки бота: читаются из .env"""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _parse_admins() -> list[int]:
    raw = os.getenv("ADMIN_IDS", "")
    return [int(x) for x in raw.replace(" ", "").split(",") if x.strip().isdigit()]


@dataclass
class Settings:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    admin_ids: list[int] = field(default_factory=_parse_admins)
    shop_name: str = os.getenv("SHOP_NAME", "Магазин")
    currency: str = os.getenv("CURRENCY", "₽")
    db_path: str = os.getenv("DB_PATH", "shop.db")
    payment_token: str = os.getenv("PAYMENT_PROVIDER_TOKEN", "")
    payment_currency: str = os.getenv("PAYMENT_CURRENCY_CODE", "RUB")
    support: str = os.getenv("SUPPORT_CONTACT", "")

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids


settings = Settings()
