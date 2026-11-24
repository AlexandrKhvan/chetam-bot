from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.config import Settings
from app.db.database import Database


class UserContextMiddleware(BaseMiddleware):
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None:
            return await handler(event, data)

        allowed = self.settings.allowed_user_ids
        if allowed and tg_user.id not in allowed:
            if isinstance(event, Message):
                await event.answer("⛔ Это личный бот. Доступ ограничен владельцем.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔ Доступ ограничен.", show_alert=True)
            return None

        profile = await self.db.upsert_user(
            user_id=tg_user.id,
            username=tg_user.username or "",
            first_name=tg_user.first_name or "",
            default_timezone=self.settings.default_timezone,
            default_evening_plan_time=self.settings.default_evening_plan_time,
            default_morning_digest_time=self.settings.default_morning_digest_time,
        )
        data["user_profile"] = profile
        return await handler(event, data)
