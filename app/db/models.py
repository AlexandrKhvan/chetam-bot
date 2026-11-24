from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class UserProfile:
    user_id: int
    username: str = ""
    first_name: str = ""
    timezone: str = "Asia/Yekaterinburg"
    evening_plan_time: str = "21:00"
    morning_digest_time: str = "08:00"
    evening_reminder_enabled: bool = True
    morning_digest_enabled: bool = True
    created_at: str = ""


@dataclass(slots=True)
class Task:
    id: int
    user_id: int
    title: str
    notes: str = ""
    status: str = "inbox"  # inbox | planned | done | cancelled
    priority: int = 2  # 1 = high, 2 = medium, 3 = low
    planned_date: str | None = None  # YYYY-MM-DD
    planned_time: str | None = None  # HH:MM
    sort_order: int = 0
    created_at: str = ""
    completed_at: str | None = None
    carried_over_count: int = 0


@dataclass(slots=True)
class ScheduleEvent:
    id: int
    user_id: int
    event_date: str  # YYYY-MM-DD
    start_time: str  # HH:MM
    end_time: str = ""  # HH:MM
    title: str = ""
    location: str = ""
    notes: str = ""
    source: str = "manual"  # manual | docx | photo
    is_done: bool = False
    created_at: str = ""


@dataclass(slots=True)
class TaskHistoryEvent:
    id: int
    user_id: int
    task_id: int | None
    event_date: str  # YYYY-MM-DD
    action: str  # completed | carried_over | cancelled
    task_title: str
    created_at: str = ""


@dataclass(slots=True)
class ParsedScheduleItem:
    event_date: str  # YYYY-MM-DD
    start_time: str  # HH:MM
    end_time: str = ""
    title: str = ""
    location: str = ""
    notes: str = ""


@dataclass(slots=True)
class DayPlan:
    day: str  # YYYY-MM-DD
    schedule_events: list[ScheduleEvent] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)

    @property
    def total_items(self) -> int:
        return len(self.schedule_events) + len(self.tasks)

    @property
    def done_items(self) -> int:
        done_events = sum(1 for e in self.schedule_events if e.is_done)
        done_tasks = sum(1 for t in self.tasks if t.status == "done")
        return done_events + done_tasks

    @property
    def total_tasks(self) -> int:
        return len(self.tasks)

    @property
    def done_tasks(self) -> int:
        return sum(1 for t in self.tasks if t.status == "done")

    @property
    def completion_rate(self) -> float:
        if self.total_items == 0:
            return 0.0
        return self.done_items / self.total_items


@dataclass(slots=True)
class DailySummary:
    day: str  # YYYY-MM-DD
    completed_tasks: list[Task] = field(default_factory=list)
    pending_tasks: list[Task] = field(default_factory=list)
    carried_over_events: list[TaskHistoryEvent] = field(default_factory=list)
    schedule_events: list[ScheduleEvent] = field(default_factory=list)

    @property
    def done_count(self) -> int:
        return len(self.completed_tasks) + sum(1 for e in self.schedule_events if e.is_done)

    @property
    def total_count(self) -> int:
        return (
            len(self.completed_tasks)
            + len(self.pending_tasks)
            + len(self.carried_over_events)
            + len(self.schedule_events)
        )

    @property
    def completion_rate(self) -> float:
        if self.total_count == 0:
            return 0.0
        return self.done_count / self.total_count


@dataclass(slots=True)
class PeriodStats:
    days_count: int
    start_date: str
    end_date: str
    total_done: int
    total_planned: int
    streak_days: int
    daily_breakdown: list[tuple[str, int, int]] = field(default_factory=list)

    @property
    def completion_rate(self) -> float:
        if self.total_planned == 0:
            return 0.0
        return self.total_done / self.total_planned
