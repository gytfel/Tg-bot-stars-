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


def _packages() -> list[int]:
    raw = os.getenv("STAR_PACKAGES", "50,100,250,500,1000")
    return sorted({int(x) for x in raw.replace(" ", "").split(",") if x.isdigit()})


@dataclass
class Settings:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    admin_ids: list[int] = field(default_factory=_parse_admins)
    shop_name: str = os.getenv("SHOP_NAME", "Магазин")
    currency: str = os.getenv("CURRENCY", "₽")
    db_path: str = os.getenv("DB_PATH", "shop.db")
    support: str = os.getenv("SUPPORT_CONTACT", "")
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    # stars    — продажа Telegram Stars: покупатель выбирает количество и получает
    #            звёзды на свой @username после оплаты
    # digital  — цифровой товар: без адреса доставки, выдача сразу после оплаты
    # physical — физический: анкета с телефоном и адресом, оплата при получении
    shop_mode: str = os.getenv("SHOP_MODE", "stars").lower()

    # --- оплата -------------------------------------------------------------
    payment_token: str = os.getenv("PAYMENT_PROVIDER_TOKEN", "")
    payment_currency: str = os.getenv("PAYMENT_CURRENCY_CODE", "RUB").upper()
    # сколько единиц валюты магазина стоит одна ⭐ (для режима Telegram Stars)
    stars_rate: float = _float("STARS_RATE", 2.0)

    # --- продажа звёзд ------------------------------------------------------
    star_price: float = _float("STAR_PRICE", 1.6)      # ₽ за одну ⭐ при продаже
    min_stars: int = _int("MIN_STARS", 50)             # у Fragment минимум 50
    max_stars: int = _int("MAX_STARS", 100_000)
    star_packages: list[int] = field(default_factory=_packages)

    # --- закупка звёзд через Fragment ---------------------------------------
    # manual — админ покупает вручную и подтверждает выдачу
    # api    — автозакупка через сторонний шлюз к Fragment
    fragment_mode: str = os.getenv("FRAGMENT_MODE", "manual").lower()
    fragment_url: str = os.getenv("FRAGMENT_API_URL", "").rstrip("/")
    fragment_token: str = os.getenv("FRAGMENT_API_TOKEN", "")
    fragment_buy_path: str = os.getenv("FRAGMENT_BUY_PATH", "/buyStars")
    fragment_balance_path: str = os.getenv("FRAGMENT_BALANCE_PATH", "/balance")
    # у разных шлюзов поля и заголовок авторизации называются по-разному
    fragment_username_field: str = os.getenv("FRAGMENT_USERNAME_FIELD", "username")
    fragment_quantity_field: str = os.getenv("FRAGMENT_QUANTITY_FIELD", "quantity")
    fragment_reference_field: str = os.getenv("FRAGMENT_REFERENCE_FIELD", "reference")
    fragment_auth_header: str = os.getenv("FRAGMENT_AUTH_HEADER", "Authorization")
    fragment_auth_prefix: str = os.getenv("FRAGMENT_AUTH_PREFIX", "Bearer")
    fragment_timeout: int = _int("FRAGMENT_TIMEOUT", 60)
    fragment_retries: int = _int("FRAGMENT_RETRIES", 3)
    fragment_min_balance: float = _float("FRAGMENT_MIN_BALANCE", 0)

    # --- оплата в TON -------------------------------------------------------
    ton_wallet: str = os.getenv("TON_WALLET", "")
    ton_api_url: str = os.getenv("TON_API_URL", "https://toncenter.com/api/v3").rstrip("/")
    ton_api_key: str = os.getenv("TON_API_KEY", "")
    ton_rate_rub: float = _float("TON_RATE_RUB", 0)    # 0 — брать курс из API
    ton_rate_url: str = os.getenv(
        "TON_RATE_URL",
        "https://tonapi.io/v2/rates?tokens=ton&currencies=rub"
        " https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=rub"
        " https://min-api.cryptocompare.com/data/price?fsym=TON&tsyms=RUB")
    ton_check_interval: int = _int("TON_CHECK_INTERVAL", 60)
    ton_tolerance: float = _float("TON_TOLERANCE", 0.02)   # допуск на комиссию, 2%
    ton_invoice_ttl: int = _int("TON_INVOICE_TTL", 3600)   # сколько ждать оплату, сек

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
    def digital(self) -> bool:
        """Товар не нужно везти: ни телефона, ни адреса в оформлении."""
        return self.shop_mode != "physical"

    @property
    def stars_shop(self) -> bool:
        """Магазин продаёт сами звёзды."""
        return self.shop_mode == "stars"

    @property
    def ton_enabled(self) -> bool:
        return bool(self.ton_wallet)

    @property
    def fragment_auto(self) -> bool:
        return self.fragment_mode == "api" and bool(self.fragment_url)

    @property
    def pay_in_stars(self) -> bool:
        """Оплата в Telegram Stars: провайдер не нужен, валюта XTR."""
        return self.payment_currency == STARS_CURRENCY

    @property
    def online_enabled(self) -> bool:
        """Показывать ли кнопку онлайн-оплаты."""
        return self.pay_in_stars or bool(self.payment_token)

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
        if self.shop_mode not in {"stars", "digital", "physical"}:
            problems.append(f"SHOP_MODE={self.shop_mode!r}: допустимо stars, digital или physical")
        if self.stars_shop:
            problems.extend(self._validate_stars_shop())
        elif self.digital and self.payment_currency != STARS_CURRENCY and not self.payment_token:
            problems.append("Цифровой магазин без онлайн-оплаты: включите Telegram Stars "
                            "(PAYMENT_CURRENCY_CODE=XTR) или укажите токен провайдера")
        if self.shop_mode == "physical" and self.pay_in_stars:
            problems.append("Telegram Stars нельзя использовать для физических товаров — "
                            "подключите платёжного провайдера")
        if self.mode not in {"polling", "webhook"}:
            problems.append(f"BOT_MODE={self.mode!r}: допустимо polling или webhook")
        if self.mode == "webhook":
            if not self.webhook_base:
                problems.append("BOT_MODE=webhook, но WEBHOOK_URL не задан")
            elif not self.webhook_base.startswith("https://"):
                problems.append("WEBHOOK_URL должен начинаться с https:// — "
                                "Telegram не примет http")
        if self.pay_in_stars and self.payment_token:
            problems.append("Для Telegram Stars токен провайдера не нужен — очистите "
                            "PAYMENT_PROVIDER_TOKEN")
        if self.pay_in_stars and self.stars_rate <= 0:
            problems.append("STARS_RATE должен быть больше нуля")
        return problems

    def _validate_stars_shop(self) -> list[str]:
        problems: list[str] = []
        if self.pay_in_stars:
            problems.append("Магазин продаёт звёзды — платить за них звёздами нельзя. "
                            "Уберите PAYMENT_CURRENCY_CODE=XTR")
        if not self.ton_enabled and not self.payment_token:
            problems.append("Принимать оплату нечем: укажите TON_WALLET "
                            "или токен платёжного провайдера")
        if self.star_price <= 0:
            problems.append("STAR_PRICE должен быть больше нуля")
        if self.min_stars < 50:
            problems.append("MIN_STARS меньше 50 — Fragment не продаёт меньше 50 ⭐")
        if self.star_packages and min(self.star_packages) < self.min_stars:
            problems.append(f"В STAR_PACKAGES есть наборы меньше MIN_STARS={self.min_stars}")
        if self.fragment_mode not in {"manual", "api"}:
            problems.append(f"FRAGMENT_MODE={self.fragment_mode!r}: допустимо manual или api")
        if self.fragment_mode == "api" and not (self.fragment_url and self.fragment_token):
            problems.append("FRAGMENT_MODE=api требует FRAGMENT_API_URL и FRAGMENT_API_TOKEN")
        if self.ton_enabled and not self.ton_rate_rub and not self.ton_rate_url:
            problems.append("Не задан курс TON: укажите TON_RATE_RUB или TON_RATE_URL")
        if self.ton_enabled:
            problems.extend(self._validate_wallet())
        return problems

    def _validate_wallet(self) -> list[str]:
        from ton import parse_address     # локальный импорт: ton тянет database

        parsed = parse_address(self.ton_wallet)
        if not parsed:
            return ["TON_WALLET не проходит проверку контрольной суммы — "
                    "проверьте, не потерялся ли символ при копировании"]
        if parsed["testnet"]:
            return ["TON_WALLET — адрес тестовой сети: настоящие переводы на него "
                    "не придут"]
        return []


settings = Settings()
