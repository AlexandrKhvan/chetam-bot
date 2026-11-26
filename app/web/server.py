from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import Settings, load_settings
from app.db.database import Database
from app.db.models import UserProfile
from app.services.brain_dump import split_brain_dump
from app.services.history_service import HistoryService
from app.services.reminder_service import (
    ReminderService,
    format_reminder_time_local,
    parse_reminder_input,
)
from app.services.schedule_service import ScheduleService
from app.services.task_service import TaskService
from app.services.time_utils import (
    format_date_ru,
    format_weekday_short_ru,
    get_zoneinfo,
    user_now,
    user_today,
    user_today_iso,
)
from app.web.auth import verify_telegram_init_data

STATIC_DIR = Path(__file__).parent / "static"


class BrainDumpRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    target_date: str | None = None
    target_bucket: str = "inbox"  # inbox | pool


class PlanTaskRequest(BaseModel):
    target_date: str
    planned_time: str | None = None
    carry_over: bool = False


class CarryOverAllRequest(BaseModel):
    from_date: str
    to_date: str


class AddScheduleRequest(BaseModel):
    event_date: str
    start_time: str
    end_time: str = ""
    title: str = Field(min_length=1, max_length=250)
    location: str = ""


class CreateReminderRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class TaskRemindPresetRequest(BaseModel):
    preset: str = "1h"  # 15m | 1h | eve | tom


class SnoozeReminderRequest(BaseModel):
    minutes: int = Field(default=15, ge=1, le=10080)


def create_app(custom_settings: Settings | None = None) -> FastAPI:
    settings = custom_settings or load_settings()
    db = Database(settings.database_path)
    task_service = TaskService(db)
    schedule_service = ScheduleService(db)
    history_service = HistoryService(db)
    reminder_service = ReminderService(db)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await db.init()
        yield

    app = FastAPI(title="CheTam Mini App API", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    async def get_current_user(
        x_telegram_init_data: str | None = Header(default=None),
    ) -> UserProfile:
        if not x_telegram_init_data:
            raise HTTPException(status_code=401, detail="Open this app inside Telegram")
        try:
            tg_user = verify_telegram_init_data(x_telegram_init_data, settings.bot_token)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

        allowed = settings.allowed_user_ids
        if allowed and tg_user.user_id not in allowed:
            raise HTTPException(status_code=403, detail="Access restricted to owner")

        return await db.upsert_user(
            user_id=tg_user.user_id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            default_timezone=settings.default_timezone,
            default_evening_plan_time=settings.default_evening_plan_time,
            default_morning_digest_time=settings.default_morning_digest_time,
        )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/me")
    async def api_me(user: UserProfile = Depends(get_current_user)):
        today = user_today(user.timezone)
        today_iso = today.isoformat()
        tomorrow_iso = (today + timedelta(days=1)).isoformat()
        inbox = await task_service.list_inbox(user.user_id)
        pool = await task_service.list_pool(user.user_id)
        reminders = await reminder_service.list_active(user.user_id)
        monday = today - timedelta(days=today.weekday())
        week_days = [
            {
                "iso": (monday + timedelta(days=i)).isoformat(),
                "label": format_weekday_short_ru((monday + timedelta(days=i)).isoformat()),
                "is_today": (monday + timedelta(days=i)) == today,
            }
            for i in range(7)
        ]
        return {
            "user": asdict(user),
            "today": today_iso,
            "tomorrow": tomorrow_iso,
            "inbox_count": len(inbox),
            "pool_count": len(pool),
            "reminders_count": len(reminders),
            "week_days": week_days,
        }

    @app.get("/api/day")
    async def api_day(
        day: str | None = Query(default=None, alias="date"),
        user: UserProfile = Depends(get_current_user),
    ):
        today_iso = user_today_iso(user.timezone)
        target = day or today_iso
        try:
            date.fromisoformat(target)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid date format") from exc

        plan = await task_service.get_day_plan(user.user_id, target)
        return {
            "day": plan.day,
            "label": format_date_ru(plan.day, today_iso),
            "done_items": plan.done_items,
            "total_items": plan.total_items,
            "completion_rate": round(plan.completion_rate * 100),
            "schedule_events": [asdict(e) for e in plan.schedule_events],
            "tasks": [asdict(t) for t in plan.tasks],
        }

    @app.get("/api/inbox")
    async def api_inbox(user: UserProfile = Depends(get_current_user)):
        tasks = await task_service.list_inbox(user.user_id)
        return {"tasks": [asdict(t) for t in tasks]}

    @app.get("/api/pool")
    async def api_pool(user: UserProfile = Depends(get_current_user)):
        tasks = await task_service.list_pool(user.user_id)
        return {"tasks": [asdict(t) for t in tasks]}

    @app.post("/api/tasks/dump")
    async def api_tasks_dump(
        payload: BrainDumpRequest,
        user: UserProfile = Depends(get_current_user),
    ):
        today = user_today(user.timezone)
        drafts = split_brain_dump(payload.text, today=today)
        bucket = "pool" if payload.target_bucket == "pool" else "inbox"
        created = []
        for d in drafts:
            planned_date = None if bucket == "pool" else (d.planned_date or payload.target_date)
            task = await task_service.create_task(
                user.user_id,
                d.title,
                planned_date=planned_date,
                planned_time=None if bucket == "pool" else d.planned_time,
                priority=d.priority,
                initial_status=bucket,
            )
            created.append(asdict(task))
        return {"created": created, "count": len(created)}

    @app.post("/api/tasks/{task_id}/toggle")
    async def api_toggle_task(task_id: int, user: UserProfile = Depends(get_current_user)):
        today_iso = user_today_iso(user.timezone)
        updated = await task_service.toggle_done(user.user_id, task_id, fallback_date=today_iso)
        if not updated:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"task": asdict(updated)}

    @app.post("/api/tasks/{task_id}/plan")
    async def api_plan_task(
        task_id: int,
        payload: PlanTaskRequest,
        user: UserProfile = Depends(get_current_user),
    ):
        updated = await task_service.plan_task_for_date(
            user.user_id,
            task_id,
            payload.target_date,
            planned_time=payload.planned_time,
            record_carry_over=payload.carry_over,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"task": asdict(updated)}

    @app.post("/api/tasks/{task_id}/inbox")
    async def api_task_to_inbox(task_id: int, user: UserProfile = Depends(get_current_user)):
        updated = await task_service.move_to_inbox(user.user_id, task_id, record_carry_over=True)
        if not updated:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"task": asdict(updated)}

    @app.post("/api/tasks/{task_id}/pool")
    async def api_task_to_pool(task_id: int, user: UserProfile = Depends(get_current_user)):
        updated = await task_service.move_to_pool(user.user_id, task_id, record_carry_over=True)
        if not updated:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"task": asdict(updated)}

    @app.post("/api/tasks/{task_id}/priority")
    async def api_cycle_priority(task_id: int, user: UserProfile = Depends(get_current_user)):
        updated = await task_service.cycle_priority(user.user_id, task_id)
        if not updated:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"task": asdict(updated)}

    @app.post("/api/tasks/{task_id}/remind")
    async def api_task_remind(
        task_id: int,
        payload: TaskRemindPresetRequest,
        user: UserProfile = Depends(get_current_user),
    ):
        task = await task_service.get_task(user.user_id, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        now_local = user_now(user.timezone)
        if payload.preset == "15m":
            target_local = now_local + timedelta(minutes=15)
        elif payload.preset == "eve":
            target_local = now_local.replace(hour=20, minute=0, second=0, microsecond=0)
            if target_local <= now_local:
                target_local += timedelta(days=1)
        elif payload.preset == "tom":
            tom = now_local.date() + timedelta(days=1)
            target_local = datetime(
                tom.year, tom.month, tom.day, 9, 0, tzinfo=get_zoneinfo(user.timezone)
            )
        else:
            target_local = now_local + timedelta(hours=1)

        rem = await reminder_service.create_reminder(
            user.user_id,
            task.title,
            target_local.astimezone(timezone.utc),
            task_id=task.id,
        )
        return {
            "reminder": {
                **asdict(rem),
                "when_label": format_reminder_time_local(rem.remind_at_utc, user.timezone),
            }
        }

    @app.delete("/api/tasks/{task_id}")
    async def api_delete_task(task_id: int, user: UserProfile = Depends(get_current_user)):
        ok = await task_service.delete_task(user.user_id, task_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"deleted": True}

    @app.post("/api/evening/carry-over-all")
    async def api_carry_over_all(
        payload: CarryOverAllRequest,
        user: UserProfile = Depends(get_current_user),
    ):
        moved = await task_service.carry_over_all_pending(
            user.user_id, payload.from_date, payload.to_date
        )
        return {"moved": moved}

    @app.get("/api/reminders")
    async def api_list_reminders(user: UserProfile = Depends(get_current_user)):
        items = await reminder_service.list_active(user.user_id)
        return {
            "reminders": [
                {
                    **asdict(r),
                    "when_label": format_reminder_time_local(r.remind_at_utc, user.timezone),
                }
                for r in items
            ]
        }

    @app.post("/api/reminders")
    async def api_create_reminder(
        payload: CreateReminderRequest,
        user: UserProfile = Depends(get_current_user),
    ):
        parsed = parse_reminder_input(payload.text, user.timezone)
        if not parsed:
            raise HTTPException(
                status_code=400,
                detail="Не понял время. Пример: «через 30 мин выключить плиту» или «завтра в 10:00 отчёт»",
            )
        rem = await reminder_service.create_reminder(
            user.user_id,
            parsed.text,
            parsed.remind_at_utc,
            repeat_rule=parsed.repeat_rule,
        )
        return {
            "reminder": {
                **asdict(rem),
                "when_label": format_reminder_time_local(rem.remind_at_utc, user.timezone),
            }
        }

    @app.post("/api/reminders/{reminder_id}/snooze")
    async def api_snooze_reminder(
        reminder_id: int,
        payload: SnoozeReminderRequest,
        user: UserProfile = Depends(get_current_user),
    ):
        updated = await reminder_service.snooze(
            user.user_id, reminder_id, minutes=payload.minutes
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Reminder not found")
        return {
            "reminder": {
                **asdict(updated),
                "when_label": format_reminder_time_local(updated.remind_at_utc, user.timezone),
            }
        }

    @app.delete("/api/reminders/{reminder_id}")
    async def api_delete_reminder(
        reminder_id: int, user: UserProfile = Depends(get_current_user)
    ):
        ok = await reminder_service.delete_reminder(user.user_id, reminder_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Reminder not found")
        return {"deleted": True}

    @app.post("/api/schedule/{event_id}/toggle")
    async def api_toggle_schedule(event_id: int, user: UserProfile = Depends(get_current_user)):
        updated = await schedule_service.toggle_done(user.user_id, event_id)
        if not updated:
            raise HTTPException(status_code=404, detail="Event not found")
        return {"event": asdict(updated)}

    @app.post("/api/schedule")
    async def api_add_schedule(
        payload: AddScheduleRequest,
        user: UserProfile = Depends(get_current_user),
    ):
        ev = await schedule_service.add_event(
            user.user_id,
            payload.event_date,
            payload.start_time,
            payload.title,
            end_time=payload.end_time,
            location=payload.location,
            source="manual",
        )
        return {"event": asdict(ev)}

    @app.delete("/api/schedule/{event_id}")
    async def api_delete_schedule(event_id: int, user: UserProfile = Depends(get_current_user)):
        ok = await schedule_service.delete_event(user.user_id, event_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Event not found")
        return {"deleted": True}

    @app.get("/api/history/stats")
    async def api_history_stats(
        days: int = Query(default=7, ge=1, le=60),
        user: UserProfile = Depends(get_current_user),
    ):
        today_iso = user_today_iso(user.timezone)
        stats = await history_service.get_period_stats(user.user_id, today_iso, days=days)
        return {
            "days_count": stats.days_count,
            "start_date": stats.start_date,
            "end_date": stats.end_date,
            "total_done": stats.total_done,
            "total_planned": stats.total_planned,
            "completion_rate": round(stats.completion_rate * 100),
            "streak_days": stats.streak_days,
            "daily_breakdown": [
                {
                    "day": d,
                    "label": format_weekday_short_ru(d),
                    "done": done,
                    "planned": planned,
                    "pct": round((done / planned) * 100) if planned else 0,
                }
                for d, done, planned in stats.daily_breakdown
            ],
        }

    @app.get("/api/history/day")
    async def api_history_day(
        day: str | None = Query(default=None, alias="date"),
        user: UserProfile = Depends(get_current_user),
    ):
        today_iso = user_today_iso(user.timezone)
        target = day or today_iso
        summary = await history_service.get_daily_summary(user.user_id, target)
        return {
            "day": summary.day,
            "label": format_date_ru(summary.day, today_iso),
            "done_count": summary.done_count,
            "total_count": summary.total_count,
            "completion_rate": round(summary.completion_rate * 100),
            "completed_tasks": [asdict(t) for t in summary.completed_tasks],
            "pending_tasks": [asdict(t) for t in summary.pending_tasks],
            "carried_over_events": [asdict(e) for e in summary.carried_over_events],
            "schedule_events": [asdict(e) for e in summary.schedule_events],
        }

    return app


app = create_app()
