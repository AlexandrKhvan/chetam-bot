from __future__ import annotations

import logging
from datetime import timedelta

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.bot.formatters import render_day_plan, render_evening_step1
from app.bot.keyboards import day_plan_kb, evening_step1_kb
from app.db.database import Database
from app.services.task_service import TaskService
from app.services.time_utils import user_now

logger = logging.getLogger(__name__)


class ReminderScheduler:
    def __init__(self, bot: Bot, db: Database, task_service: TaskService) -> None:
        self.bot = bot
        self.db = db
        self.task_service = task_service
        self.scheduler = AsyncIOScheduler()
        self._sent_keys: set[tuple[int, str, str]] = set()

    def start(self) -> None:
        self.scheduler.add_job(
            self._tick,
            trigger="interval",
            seconds=60,
            id="reminder_tick",
            replace_existing=True,
        )
        self.scheduler.start()
        logger.info("Reminder scheduler started (60s interval)")

    def stop(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    async def _tick(self) -> None:
        users = await self.db.list_users()
        for user in users:
            now_local = user_now(user.timezone)
            hhmm = now_local.strftime("%H:%M")
            today_iso = now_local.date().isoformat()
            tomorrow_iso = (now_local.date() + timedelta(days=1)).isoformat()

            if user.evening_reminder_enabled and hhmm == user.evening_plan_time:
                key = (user.user_id, "evening", today_iso)
                if key not in self._sent_keys:
                    self._sent_keys.add(key)
                    await self._send_evening_prompt(user.user_id, today_iso, tomorrow_iso)

            if user.morning_digest_enabled and hhmm == user.morning_digest_time:
                key = (user.user_id, "morning", today_iso)
                if key not in self._sent_keys:
                    self._sent_keys.add(key)
                    await self._send_morning_digest(user.user_id, today_iso)

        # Keep dedup cache bounded
        if len(self._sent_keys) > 2000:
            self._sent_keys.clear()

    async def _send_evening_prompt(
        self, user_id: int, today_iso: str, tomorrow_iso: str
    ) -> None:
        try:
            plan = await self.task_service.get_day_plan(user_id, today_iso)
            pending = [t for t in plan.tasks if t.status == "planned"]
            text = render_evening_step1(plan, today_iso)
            kb = evening_step1_kb(pending, today_iso, tomorrow_iso)
            await self.bot.send_message(user_id, text, reply_markup=kb)
        except Exception:
            logger.exception("Failed to send evening reminder to user %s", user_id)

    async def _send_morning_digest(self, user_id: int, today_iso: str) -> None:
        try:
            plan = await self.task_service.get_day_plan(user_id, today_iso)
            text = "☀️ <b>Доброе утро! Вот твой план на день:</b>\n\n" + render_day_plan(
                plan, today_iso
            )
            kb = day_plan_kb(plan, today_iso)
            await self.bot.send_message(user_id, text, reply_markup=kb)
        except Exception:
            logger.exception("Failed to send morning digest to user %s", user_id)
