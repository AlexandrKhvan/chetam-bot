from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl


@dataclass(slots=True)
class TelegramWebAppUser:
    user_id: int
    username: str = ""
    first_name: str = ""


def verify_telegram_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = 86400,
) -> TelegramWebAppUser:
    """Validates Telegram Mini App initData using HMAC-SHA256 per Telegram Bot API spec."""
    if not init_data or not bot_token:
        raise ValueError("Missing initData or bot token")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", "")
    if not received_hash:
        raise ValueError("Missing hash in initData")

    auth_date_raw = pairs.get("auth_date", "")
    if auth_date_raw.isdigit():
        age = time.time() - int(auth_date_raw)
        if age > max_age_seconds or age < -300:
            raise ValueError("initData expired")

    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs.keys()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        raise ValueError("Invalid initData signature")

    user_json = pairs.get("user")
    if not user_json:
        raise ValueError("Missing user object in initData")

    user_data = json.loads(user_json)
    user_id = int(user_data["id"])
    return TelegramWebAppUser(
        user_id=user_id,
        username=str(user_data.get("username", "")),
        first_name=str(user_data.get("first_name", "")),
    )
