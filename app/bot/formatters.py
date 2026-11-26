from __future__ import annotations

from collections import defaultdict
from datetime import date
from html import escape

from app.db.models import (
    DailySummary,
    DayPlan,
    FreeWindow,
    ParsedScheduleItem,
    PeriodStats,
    Reminder,
    ScheduleEvent,
    Task,
    UserProfile,
)
from app.services.reminder_service import format_reminder_time_local
from app.services.time_utils import format_date_ru, format_weekday_short_ru

PRIORITY_ICON = {1: "🔴", 2: "🟡", 3: "⚪"}


def render_progress_bar(done: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return "░" * width + " 0/0"
    ratio = max(0.0, min(1.0, done / total))
    filled = round(ratio * width)
    pct = round(ratio * 100)
    return f"{'▓' * filled}{'░' * (width - filled)} {done}/{total} ({pct}%)"


def format_deadline_badge(deadline_iso: str | None, today_iso: str) -> str:
    if not deadline_iso:
        return ""
    try:
        diff = (date.fromisoformat(deadline_iso) - date.fromisoformat(today_iso)).days
    except ValueError:
        return ""
    if diff < 0:
        return f"🚨 просрочено {-diff} дн."
    if diff == 0:
        return "🔥 дедлайн сегодня"
    if diff <= 3:
        return f"⏳ {diff} дн."
    d = date.fromisoformat(deadline_iso)
    return f"📅 до {d.day:02d}.{d.month:02d}"


def _format_event_line(event: ScheduleEvent) -> str:
    icon = "✅" if event.is_done else "▫️"
    time_part = f"{event.start_time}–{event.end_time}" if event.end_time else event.start_time
    title = escape(event.title)
    loc = f" · <i>{escape(event.location)}</i>" if event.location else ""
    body = f"<b>{escape(time_part)}</b> {title}{loc}"
    line = f"{icon} <s>{body}</s>" if event.is_done else f"{icon} {body}"
    if event.meeting_info and not event.is_done:
        line += f"\n      🔗 <code>{escape(event.meeting_info)}</code>"
    return line


def _format_task_line(task: Task, today_iso: str = "") -> str:
    icon = "✅" if task.status == "done" else "⬜"
    prio = PRIORITY_ICON.get(task.priority, "🟡")
    time_prefix = f"<code>{escape(task.planned_time)}</code> " if task.planned_time else ""
    title = escape(task.title)
    extras: list[str] = []
    if task.recurrence_rule:
        extras.append("🔁")
    if task.subtasks:
        sub_done = sum(1 for s in task.subtasks if s.is_done)
        extras.append(f"☑️{sub_done}/{len(task.subtasks)}")
    if task.deadline_date and today_iso and task.status != "done":
        badge = format_deadline_badge(task.deadline_date, today_iso)
        if badge:
            extras.append(badge)
    if task.tags:
        extras.append(" ".join(f"#{escape(t)}" for t in task.tags[:3]))
    if task.carried_over_count > 0:
        extras.append(f"↻{task.carried_over_count}")

    suffix = f" <i>({' · '.join(extras)})</i>" if extras else ""
    if task.status == "done":
        return f"{icon} <s>{time_prefix}{title}</s>"
    return f"{icon} {prio} {time_prefix}{title}{suffix}"


def render_day_plan(
    plan: DayPlan,
    today_iso: str,
    *,
    manage_mode: bool = False,
    upcoming_deadlines: list[Task] | None = None,
) -> str:
    header = f"📅 <b>{escape(format_date_ru(plan.day, today_iso))}</b>"
    lines = [header]

    if plan.total_items > 0:
        lines.append(f"<code>{render_progress_bar(plan.done_items, plan.total_items)}</code>")
    lines.append("")

    if upcoming_deadlines and plan.day == today_iso:
        urgent = []
        today_d = date.fromisoformat(today_iso)
        for dl in upcoming_deadlines:
            if dl.deadline_date:
                diff = (date.fromisoformat(dl.deadline_date) - today_d).days
                if diff <= 5:
                    urgent.append((dl, format_deadline_badge(dl.deadline_date, today_iso)))
        if urgent:
            lines.append("<b>🔥 Ближайшие дедлайны:</b>")
            for dl, badge in urgent[:3]:
                lines.append(f"  • {escape(dl.title)} — <b>{badge}</b>")
            lines.append("")

    if plan.schedule_events:
        lines.append("<b>🎓 Расписание:</b>")
        for ev in plan.schedule_events:
            lines.append(_format_event_line(ev))
        lines.append("")

    if plan.tasks:
        lines.append("<b>📋 Задачи:</b>")
        for task in plan.tasks:
            lines.append(_format_task_line(task, today_iso))
    elif not plan.schedule_events:
        lines.append("<i>На этот день пока ничего не запланировано.</i>")
        lines.append("Нажми <b>➕ Задача</b>, выбери из <b>📥 Инбокса</b> / <b>🗂 Пула</b> или запусти <b>🌙 Вечерний план</b>.")
    else:
        lines.append("<b>📋 Задачи:</b> <i>пока пусто</i>")

    if manage_mode:
        lines.append("")
        lines.append("⚙️ <i>Режим правки: приоритет, напоминание 🔔, перенос, пул 🗂 и удаление.</i>")
    elif plan.total_items > 0:
        lines.append("")
        lines.append("<i>Тап по задаче ставит галочку · ➡️ на завтра · 🗂 в общий пул.</i>")

    return "\n".join(lines)


def render_deadlines(tasks: list[Task], today_iso: str) -> str:
    lines = [f"⏳ <b>Ближайшие дедлайны</b> ({len(tasks)})"]
    if not tasks:
        lines.append("")
        lines.append("<i>Активных дедлайнов нет — всё спокойно! ✨</i>")
        lines.append("Чтобы задать дедлайн, просто напиши: <code>сдать лабу №4 до 30.11</code> или <code>отчёт к пятнице</code>.")
        return "\n".join(lines)

    lines.append("<i>За 3 дня до срока срочность задачи автоматически повышается до 🔴.</i>")
    lines.append("")
    for idx, t in enumerate(tasks, start=1):
        prio = PRIORITY_ICON.get(t.priority, "🟡")
        badge = format_deadline_badge(t.deadline_date, today_iso)
        lines.append(f"{idx}. {prio} <b>{escape(t.title)}</b> — {badge}")
    return "\n".join(lines)


def render_inbox(tasks: list[Task], today_iso: str = "", page: int = 0, page_size: int = 6) -> str:
    total = len(tasks)
    lines = [f"📥 <b>Инбокс</b> ({total})"]
    if not tasks:
        lines.append("")
        lines.append("<i>Инбокс пуст — голова свободна! ✨</i>")
        lines.append("Пиши сюда текстом (хоть всё в кучу), пересылай сообщения или отправляй голосовые.")
        return "\n".join(lines)

    start = page * page_size
    chunk = tasks[start : start + page_size]
    lines.append("<i>Перекинь на сегодня/завтра, убери в 🗂 Пул «когда-нибудь» или разбери вечером.</i>")
    lines.append("")
    for idx, task in enumerate(chunk, start=start + 1):
        lines.append(f"{idx}. {_format_task_line(task, today_iso)[2:]}")
    return "\n".join(lines)


def render_pool(
    tasks: list[Task],
    today_iso: str = "",
    *,
    active_tag: str = "",
    page: int = 0,
    page_size: int = 6,
) -> str:
    total = len(tasks)
    tag_part = f" · #{escape(active_tag)}" if active_tag else ""
    lines = [f"🗂 <b>Общий пул задач</b> ({total}{tag_part})"]
    if not tasks:
        lines.append("")
        lines.append("<i>Здесь пока пусто.</i>")
        lines.append(
            "Складывай сюда дела «на потом / когда будет время» с тегами вроде <code>#учёба</code> или <code>#проект</code>."
        )
        return "\n".join(lines)

    start = page * page_size
    chunk = tasks[start : start + page_size]
    lines.append("<i>Задачи без жёсткой даты. Фильтруй по #тегам и забирай в план вечером.</i>")
    lines.append("")
    for idx, task in enumerate(chunk, start=start + 1):
        lines.append(f"{idx}. {_format_task_line(task, today_iso)[2:]}")
    return "\n".join(lines)


def render_evening_pool_picker(
    tomorrow_plan: DayPlan, pool_tasks: list[Task], today_iso: str, page: int = 0, page_size: int = 8
) -> str:
    lines = [
        "🗂 <b>Выбор из общего пула на завтра</b>",
        f"🌅 <b>{escape(format_date_ru(tomorrow_plan.day, today_iso))}</b> · в плане уже {len(tomorrow_plan.tasks)} задач",
        "",
    ]
    if not pool_tasks:
        lines.append("<i>В пуле пока нет задач. Можно добавить новую или вернуться к плану на завтра.</i>")
        return "\n".join(lines)

    lines.append(f"<i>Нажми на задачу ниже — она сразу перейдёт в план на завтра (в пуле: {len(pool_tasks)}):</i>")
    lines.append("")
    start = page * page_size
    for idx, t in enumerate(pool_tasks[start : start + page_size], start=start + 1):
        lines.append(f"{idx}. {_format_task_line(t, today_iso)[2:]}")
    return "\n".join(lines)


def render_reminders(reminders: list[Reminder], tz_name: str) -> str:
    lines = [f"🔔 <b>Активные напоминания</b> ({len(reminders)})"]
    if not reminders:
        lines.append("")
        lines.append("<i>Пока нет активных напоминаний.</i>")
        lines.append(
            "Нажми <b>➕ Напоминание</b> или напиши команду:\n"
            "• <code>/remind через 30 мин выключить плиту</code>\n"
            "• <code>/remind завтра в 10:00 сдать отчёт</code>\n"
            "• <code>/remind каждый день в 22:00 пить витамины</code>"
        )
        return "\n".join(lines)

    lines.append("")
    for idx, rem in enumerate(reminders[:12], start=1):
        when = format_reminder_time_local(rem.remind_at_utc, tz_name)
        rep = " 🔁" if rem.repeat_rule == "daily" else ""
        lines.append(f"{idx}. <b>{escape(when)}</b>{rep} — {escape(rem.text)}")
    if len(reminders) > 12:
        lines.append(f"<i>…и ещё {len(reminders) - 12}</i>")
    return "\n".join(lines)


def render_evening_step1(today_plan: DayPlan, today_iso: str) -> str:
    pending = [t for t in today_plan.tasks if t.status == "planned"]
    lines = [
        "🌙 <b>Вечернее планирование · Шаг 1/2: Итоги дня</b>",
        f"📅 {escape(format_date_ru(today_plan.day, today_iso))}",
        f"<code>{render_progress_bar(today_plan.done_items, today_plan.total_items)}</code>",
        "",
    ]
    if pending:
        lines.append(f"<b>Осталось невыполненных задач: {len(pending)}</b>")
        lines.append("Реши судьбу каждой или перенеси всё на завтра одним нажатием:")
        lines.append("")
        for idx, t in enumerate(pending, start=1):
            lines.append(f"{idx}. {_format_task_line(t, today_iso)[2:]}")
    else:
        lines.append("🎉 <b>Все задачи на сегодня закрыты!</b>")
        lines.append("Переходи к сборке расписания на завтра.")
    return "\n".join(lines)


def render_evening_step2(
    tomorrow_plan: DayPlan,
    inbox_tasks: list[Task],
    today_iso: str,
    free_windows: list[FreeWindow] | None = None,
) -> str:
    lines = [
        "🌙 <b>Вечернее планирование · Шаг 2/2: План на завтра</b>",
        f"🌅 <b>{escape(format_date_ru(tomorrow_plan.day, today_iso))}</b>",
        "",
    ]
    if tomorrow_plan.schedule_events:
        lines.append("<b>🎓 Пары / события завтра:</b>")
        for ev in tomorrow_plan.schedule_events:
            lines.append(_format_event_line(ev))
        if free_windows:
            win_strs = []
            for w in free_windows[:4]:
                h, m = divmod(w.duration_minutes, 60)
                dur = f"{h}ч {m}м" if h and m else (f"{h}ч" if h else f"{m}м")
                win_strs.append(f"{w.start_time}–{w.end_time} ({dur})")
            lines.append(f"🕒 <i>Свободные окна: {', '.join(win_strs)}</i>")
        lines.append("")
    else:
        lines.append("🎓 <i>Расписание на завтра не загружено (можно скинуть .docx / .ics / .xlsx / .pdf / фото).</i>")
        lines.append("")

    if tomorrow_plan.tasks:
        lines.append(f"<b>📋 Уже в плане на завтра ({len(tomorrow_plan.tasks)}):</b>")
        for t in tomorrow_plan.tasks:
            lines.append(_format_task_line(t, today_iso))
        lines.append("")

    if inbox_tasks:
        lines.append(f"<b>📥 Выбери задачи из Инбокса ({len(inbox_tasks)}):</b>")
        lines.append("<i>Нажимай на кнопки ниже или забери задачи из 🗂 Общего пула.</i>")
    else:
        lines.append("📥 <i>Инбокс пуст — загляни в 🗂 Общий пул задач!</i>")

    return "\n".join(lines)


def render_week_schedule(
    start_iso: str, end_iso: str, events: list[ScheduleEvent], today_iso: str
) -> str:
    lines = [
        "🎓 <b>Расписание недели</b>",
        f"🗓 {format_weekday_short_ru(start_iso)} — {format_weekday_short_ru(end_iso)}",
        "",
    ]
    if not events:
        lines.append("<i>На эту неделю расписание ещё не загружено.</i>")
        lines.append("")
        lines.append(
            "Просто отправь мне <b>.docx, .ics, .xlsx, .csv, .pdf</b> или <b>фото расписания</b> прямо в чат, "
            "либо нажми <b>➕ Добавить пару / вставить текстом</b>."
        )
        return "\n".join(lines)

    by_day: dict[str, list[ScheduleEvent]] = defaultdict(list)
    for ev in events:
        by_day[ev.event_date].append(ev)

    for day_iso in sorted(by_day.keys()):
        lines.append(f"<b>{escape(format_date_ru(day_iso, today_iso))}</b>")
        for ev in by_day[day_iso]:
            lines.append("  " + _format_event_line(ev))
        lines.append("")

    return "\n".join(lines).rstrip()


def render_parsed_preview(
    items: list[ParsedScheduleItem], source_label: str, selected_group: str = ""
) -> str:
    by_day: dict[str, list[ParsedScheduleItem]] = defaultdict(list)
    for item in items:
        by_day[item.event_date].append(item)

    grp_info = f" · группа <b>{escape(selected_group)}</b>" if selected_group else ""
    lines = [
        f"🔍 <b>Распознано занятий: {len(items)}</b> ({escape(source_label)}{grp_info})",
        "Проверь предпросмотр перед сохранением:",
        "",
    ]
    shown = 0
    for day_iso in sorted(by_day.keys()):
        lines.append(f"<b>{escape(format_date_ru(day_iso))}</b>")
        for item in by_day[day_iso]:
            if shown >= 30:
                break
            time_part = f"{item.start_time}–{item.end_time}" if item.end_time else item.start_time
            loc = f" · <i>{escape(item.location)}</i>" if item.location else ""
            zm = " 🔗" if item.meeting_info else ""
            lines.append(f"  ▫️ <b>{escape(time_part)}</b> {escape(item.title)}{loc}{zm}")
            shown += 1
        lines.append("")
        if shown >= 30:
            lines.append(f"<i>…и ещё {len(items) - shown} занятий</i>")
            break
    return "\n".join(lines).rstrip()


def render_daily_history(summary: DailySummary, today_iso: str) -> str:
    lines = [
        f"📊 <b>История · {escape(format_date_ru(summary.day, today_iso))}</b>",
        f"<code>{render_progress_bar(summary.done_count, summary.total_count)}</code>",
        "",
    ]

    if summary.total_count == 0:
        lines.append("<i>За этот день записей нет.</i>")
        return "\n".join(lines)

    if summary.completed_tasks:
        lines.append(f"<b>✅ Выполнено ({len(summary.completed_tasks)}):</b>")
        for t in summary.completed_tasks:
            lines.append(f"  • {escape(t.title)}")
        lines.append("")

    if summary.pending_tasks:
        lines.append(f"<b>❌ Не выполнено ({len(summary.pending_tasks)}):</b>")
        for t in summary.pending_tasks:
            lines.append(f"  • {escape(t.title)}")
        lines.append("")

    if summary.carried_over_events:
        lines.append(f"<b>➡️ Перенесено ({len(summary.carried_over_events)}):</b>")
        for ev in summary.carried_over_events:
            lines.append(f"  • {escape(ev.task_title)}")
        lines.append("")

    if summary.schedule_events:
        done_ev = sum(1 for e in summary.schedule_events if e.is_done)
        lines.append(f"<b>🎓 Пары / события ({done_ev}/{len(summary.schedule_events)}):</b>")
        for ev in summary.schedule_events:
            lines.append("  " + _format_event_line(ev))

    return "\n".join(lines).rstrip()


def render_period_stats(stats: PeriodStats) -> str:
    pct = round(stats.completion_rate * 100) if stats.total_planned else 0
    lines = [
        f"📈 <b>Статистика за {stats.days_count} дн.</b>",
        f"🗓 {format_weekday_short_ru(stats.start_date)} — {format_weekday_short_ru(stats.end_date)}",
        "",
        f"✅ Выполнено: <b>{stats.total_done}</b> из <b>{stats.total_planned}</b> ({pct}%)",
        f"🔥 Текущая серия (стрик): <b>{stats.streak_days} дн.</b>",
        "",
        "<b>По дням:</b>",
    ]

    rows = stats.daily_breakdown[-14:] if stats.days_count > 14 else stats.daily_breakdown
    for day_iso, done, planned in rows:
        label = format_weekday_short_ru(day_iso)
        if planned == 0:
            bar = "········ 0/0"
        else:
            filled = round((done / planned) * 8)
            day_pct = round((done / planned) * 100)
            bar = f"{'▓' * filled}{'░' * (8 - filled)} {done}/{planned} ({day_pct}%)"
        lines.append(f"<code>{label}  {bar}</code>")

    return "\n".join(lines)


def render_settings(user: UserProfile, vision_enabled: bool) -> str:
    ev_state = "вкл ✅" if user.evening_reminder_enabled else "выкл 🔕"
    mo_state = "вкл ✅" if user.morning_digest_enabled else "выкл 🔕"
    cls_state = f"за {user.class_reminder_minutes} мин ✅" if user.class_reminder_minutes > 0 else "выкл 🔕"
    vision_state = "подключён ✅" if vision_enabled else "не настроен (файлы и текст работают офлайн)"
    grp_label = escape(user.study_group) if user.study_group else "не выбрана (все)"
    return "\n".join(
        [
            "⚙️ <b>Настройки</b>",
            "",
            f"🌍 Часовой пояс: <code>{escape(user.timezone)}</code>",
            f"🎓 Учебная группа: <b>{grp_label}</b>",
            f"🌙 Вечернее планирование: <b>{escape(user.evening_plan_time)}</b> ({ev_state})",
            f"☀️ Утренняя сводка: <b>{escape(user.morning_digest_time)}</b> ({mo_state})",
            f"🔔 Напоминание о парах: <b>{cls_state}</b>",
            f"🤖 AI (фото / голос / ревью): {vision_state}",
        ]
    )
