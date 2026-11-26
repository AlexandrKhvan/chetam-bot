from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.bot.formatters import render_day_plan, render_evening_step1
from app.bot.keyboards import day_plan_kb, evening_step1_kb, reminder_fired_kb
from app.db.database import Database
from app.services.reminder_service import ReminderService
from app.services.schedule_service import ScheduleService
from app.services.task_service import TaskService
from app.services.time_utils import user_now

logger = logging.getLogger(__name__)


class ReminderScheduler:
    def __init__(
        self,
        bot: Bot,
        db: Database,
        task_service: TaskService,
        schedule_service: ScheduleService,
        reminder_service: ReminderService,
    ) -> None:
        self.bot = bot
        self.db = db
        self.task_service = task_service
        self.schedule_service = schedule_service
        self.reminder_service = reminder_service
        self.scheduler = AsyncIOScheduler()
        self._sent_keys: set[tuple[int, str, str]] = set()

    def start(self) -> None:
        self.scheduler.add_job(
            self._tick,
            trigger="interval",
            seconds=30,
            id="reminder_tick",
            replace_existing=True,
        )
        self.scheduler.start()
        logger.info("Reminder scheduler started (30s interval)")

    def stop(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    async def _tick(self) -> None:
        # 1. Persistent custom & task-linked reminders (indexed SQL query)
        due_reminders = await self.reminder_service.list_due(datetime.now(timezone.utc))
        for rem in due_reminders:
            try:
                await self.reminder_service.mark_triggered(rem.id)
                rep_tag = " <i>(ежедневно 🔁)</i>" if rem.repeat_rule == "daily" else ""
                await self.bot.send_message(
                    rem.user_id,
                    f"🔔 <b>Напоминание</b>{rep_tag}\n\n• {escape(rem.text)}",
                    reply_markup=reminder_fired_kb(rem.id, rem.task_id),
                )
                await asyncio.sleep(0.05)
            except Exception:
                logger.exception("Failed to send reminder %s to user %s", rem.id, rem.user_id)

        # 2. Per-user daily digests, timed tasks, and upcoming classes
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
                    await asyncio.sleep(0.05)

            if user.morning_digest_enabled and hhmm == user.morning_digest_time:
                key = (user.user_id, "morning", today_iso)
                if key not in self._sent_keys:
                    self._sent_keys.add(key)
                    await self._send_morning_digest(user.user_id, today_iso)
                    await asyncio.sleep(0.05)

            # 2a. Auto-notify for today's tasks that have an explicit planned_time
            tasks_today = await self.task_service.list_pending_tasks_for_date(
                user.user_id, today_iso
            )
            for task in tasks_today:
                if task.planned_time and task.planned_time == hhmm:
                    t_key = (user.user_id, f"task:{task.id}", f"{today_iso}:{hhmm}")
                    if t_key not in self._sent_keys:
                        self._sent_keys.add(t_key)
                        await self._send_timed_task_alert(user.user_id, task.id, task.title, hhmm)
                        await asyncio.sleep(0.05)

            # 2b. Auto-notify before upcoming study classes
            lead = user.class_reminder_minutes
            if lead > 0:
                target_start = (now_local + timedelta(minutes=lead)).strftime("%H:%M")
                events_today = await self.schedule_service.list_events_for_date(
                    user.user_id, today_iso
                )
                for ev in events_today:
                    if not ev.is_done and ev.start_time == target_start:
                        e_key = (user.user_id, f"class:{ev.id}", f"{today_iso}:{target_start}")
                        if e_key not in self._sent_keys:
                            self._sent_keys.add(e_key)
                            await self._send_class_alert(
                                user.user_id, ev.title, ev.start_time, ev.location, lead
                            )
                            await asyncio.sleep(0.05)

        if len(self._sent_keys) > 4000:
            self._sent_keys.clear()

    async def _send_evening_prompt(
        self, user_id: int, today_iso: str, tomorrow_iso: str
    ) -> None:
        try:
            plan = await self.task_service.get_day_plan(user_id, today_iso)
            pending = [t for t in plan.tasks if t.status == "planned"]
            pool_tasks = await self.task_service.list_pool(user_id)
            text = render_evening_step1(plan, today_iso)
            kb = evening_step1_kb(pending, today_iso, tomorrow_iso, pool_count=len(pool_tasks))
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

    async def _send_timed_task_alert(
        self, user_id: int, task_id: int, title: str, hhmm: str
    ) -> None:
        try:
            # Create a lightweight snooze-able reminder entry or alert directly
            rem = await self.reminder_service.create_reminder(
                user_id,
                title,
                datetime.now(timezone.utc),
                task_id=task_id,
            )
            await self.reminder_service.mark_triggered(rem.id)
            await self.bot.send_message(
                user_id,
                f"⏰ <b>Пора за задачу ({escape(hhmm)}):</b>\n\n• {escape(title)}",
                reply_markup=reminder_fired_kb(rem.id, task_id),
            )
        except Exception:
            logger.exception("Failed to send timed task alert to user %s", user_id)

    async def _send_class_alert(
        self, user_id: int, title: str, start_time: str, location: str, lead_minutes: int
    ) -> None:
        try:
            loc = f"\n📍 <i>{escape(location)}</i>" if location else ""
            await self.bot.send_message(
                user_id,
                f"🎓 <b>Через {lead_minutes} мин пара ({escape(start_time)}):</b>\n"
                f"• {escape(title)}{loc}",
            )
        except Exception:
            logger.exception("Failed to send class alert to user %s", user_id)
