from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.db.models import DayPlan, Task, UserProfile
from app.services.time_utils import shift_date_iso

BTN_TODAY = "📅 Сегодня"
BTN_TOMORROW = "🌅 Завтра"
BTN_INBOX = "📥 Инбокс"
BTN_PLAN = "🌙 Вечерний план"
BTN_SCHEDULE = "🎓 Расписание"
BTN_HISTORY = "📊 История"


def _clip(text: str, limit: int = 34) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_TODAY), KeyboardButton(text=BTN_TOMORROW)],
            [KeyboardButton(text=BTN_INBOX), KeyboardButton(text=BTN_PLAN)],
            [KeyboardButton(text=BTN_SCHEDULE), KeyboardButton(text=BTN_HISTORY)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Напиши мысль/задачу или скинь .docx / фото расписания…",
    )


def quick_capture_kb(task_id: int, today_iso: str, tomorrow_iso: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 На сегодня", callback_data=f"qc:plan:{task_id}:{today_iso}"),
                InlineKeyboardButton(text="🌅 На завтра", callback_data=f"qc:plan:{task_id}:{tomorrow_iso}"),
            ],
            [
                InlineKeyboardButton(text="🔴 Важно", callback_data=f"qc:prio:{task_id}"),
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"qc:del:{task_id}"),
            ],
        ]
    )


def day_plan_kb(plan: DayPlan, today_iso: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for ev in plan.schedule_events:
        icon = "✅" if ev.is_done else "▫️"
        label = f"{icon} {ev.start_time} {_clip(ev.title, 26)}"
        rows.append(
            [InlineKeyboardButton(text=label, callback_data=f"ev:tog:{ev.id}:{plan.day}")]
        )

    for task in plan.tasks:
        icon = "✅" if task.status == "done" else "⬜"
        time_prefix = f"{task.planned_time} " if task.planned_time else ""
        label = f"{icon} {time_prefix}{_clip(task.title, 30)}"
        rows.append(
            [InlineKeyboardButton(text=label, callback_data=f"tk:tog:{task.id}:{plan.day}")]
        )

    prev_day = shift_date_iso(plan.day, -1)
    next_day = shift_date_iso(plan.day, 1)

    rows.append(
        [
            InlineKeyboardButton(text="➕ Задача", callback_data=f"day:add:{plan.day}"),
            InlineKeyboardButton(text="📥 Из инбокса", callback_data=f"day:pick:{plan.day}"),
            InlineKeyboardButton(text="⚙️ Правка", callback_data=f"day:mgr:{plan.day}"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="◀️", callback_data=f"day:show:{prev_day}"),
            InlineKeyboardButton(text="Сегодня", callback_data=f"day:show:{today_iso}"),
            InlineKeyboardButton(text="▶️", callback_data=f"day:show:{next_day}"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def day_manage_kb(plan: DayPlan) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    next_day = shift_date_iso(plan.day, 1)

    for task in plan.tasks:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"📌 {_clip(task.title, 22)}",
                    callback_data=f"tk:prio:{task.id}:{plan.day}",
                ),
                InlineKeyboardButton(
                    text="➡️ +1д",
                    callback_data=f"tk:mv:{task.id}:{plan.day}:{next_day}",
                ),
                InlineKeyboardButton(
                    text="📥",
                    callback_data=f"tk:inb:{task.id}:{plan.day}",
                ),
                InlineKeyboardButton(
                    text="🗑",
                    callback_data=f"tk:del:{task.id}:{plan.day}",
                ),
            ]
        )

    for ev in plan.schedule_events:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🎓 {ev.start_time} {_clip(ev.title, 24)}",
                    callback_data="noop",
                ),
                InlineKeyboardButton(
                    text="🗑 Удалить пару",
                    callback_data=f"ev:del:{ev.id}:{plan.day}",
                ),
            ]
        )

    rows.append(
        [InlineKeyboardButton(text="⬅️ Назад к чек-листу", callback_data=f"day:show:{plan.day}")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pick_from_inbox_kb(tasks: list[Task], target_day: str, back_callback: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for task in tasks[:12]:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"➕ {_clip(task.title, 34)}",
                    callback_data=f"day:pull:{task.id}:{target_day}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="⬅️ Назад к дню", callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def inbox_kb(
    tasks: list[Task], today_iso: str, tomorrow_iso: str, page: int = 0, page_size: int = 6
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    start = page * page_size
    chunk = tasks[start : start + page_size]

    for task in chunk:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"• {_clip(task.title, 18)}",
                    callback_data=f"inb:prio:{task.id}:{page}",
                ),
                InlineKeyboardButton(
                    text="📅",
                    callback_data=f"inb:plan:{task.id}:{today_iso}:{page}",
                ),
                InlineKeyboardButton(
                    text="🌅",
                    callback_data=f"inb:plan:{task.id}:{tomorrow_iso}:{page}",
                ),
                InlineKeyboardButton(
                    text="✅",
                    callback_data=f"inb:done:{task.id}:{page}",
                ),
                InlineKeyboardButton(
                    text="🗑",
                    callback_data=f"inb:del:{task.id}:{page}",
                ),
            ]
        )

    total_pages = max(1, (len(tasks) + page_size - 1) // page_size)
    if total_pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️", callback_data=f"inb:pg:{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
        if page + 1 < total_pages:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=f"inb:pg:{page + 1}"))
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="🌙 Перейти к вечернему плану", callback_data="evn:start")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def evening_step1_kb(
    pending_tasks: list[Task], today_iso: str, tomorrow_iso: str
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for task in pending_tasks[:8]:
        rows.append(
            [
                InlineKeyboardButton(text=_clip(task.title, 18), callback_data="noop"),
                InlineKeyboardButton(text="✅", callback_data=f"evn:done:{task.id}"),
                InlineKeyboardButton(text="➡️ Завтра", callback_data=f"evn:move:{task.id}"),
                InlineKeyboardButton(text="📥", callback_data=f"evn:inb:{task.id}"),
                InlineKeyboardButton(text="🗑", callback_data=f"evn:del:{task.id}"),
            ]
        )

    if pending_tasks:
        rows.append(
            [
                InlineKeyboardButton(
                    text="➡️ Перенести все на завтра",
                    callback_data=f"evn:moveall:{today_iso}:{tomorrow_iso}",
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="Дальше: собрать завтра ▶️", callback_data="evn:step2")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def evening_step2_kb(inbox_tasks: list[Task], tomorrow_iso: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for task in inbox_tasks[:10]:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"➕ {_clip(task.title, 34)}",
                    callback_data=f"evn:pick:{task.id}:{tomorrow_iso}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="✏️ Новая задача на завтра", callback_data=f"day:add:{tomorrow_iso}"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="⬅️ Назад к итогам", callback_data="evn:start"),
            InlineKeyboardButton(text="✅ Готово — открыть план", callback_data=f"day:show:{tomorrow_iso}"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def schedule_week_kb(anchor_iso: str, start_iso: str, end_iso: str, today_iso: str) -> InlineKeyboardMarkup:
    prev_w = shift_date_iso(anchor_iso, -7)
    next_w = shift_date_iso(anchor_iso, 7)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="◀️ Пред. нед.", callback_data=f"sch:wk:{prev_w}"),
                InlineKeyboardButton(text="Текущая", callback_data=f"sch:wk:{today_iso}"),
                InlineKeyboardButton(text="След. нед. ▶️", callback_data=f"sch:wk:{next_w}"),
            ],
            [
                InlineKeyboardButton(text="➕ Добавить пару", callback_data="sch:add"),
                InlineKeyboardButton(text="🗑 Очистить неделю", callback_data=f"sch:clr:{start_iso}:{end_iso}"),
            ],
        ]
    )


def schedule_import_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Сохранить (заменить эти дни)",
                    callback_data="sch:imp:replace",
                )
            ],
            [
                InlineKeyboardButton(
                    text="➕ Добавить к текущему",
                    callback_data="sch:imp:append",
                ),
                InlineKeyboardButton(text="❌ Отмена", callback_data="sch:imp:cancel"),
            ],
        ]
    )


def history_day_kb(day_iso: str, today_iso: str) -> InlineKeyboardMarkup:
    prev_day = shift_date_iso(day_iso, -1)
    next_day = shift_date_iso(day_iso, 1)
    nav = [InlineKeyboardButton(text="◀️ Вчера/назад", callback_data=f"his:day:{prev_day}")]
    if day_iso < today_iso:
        nav.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"his:day:{next_day}"))
    return InlineKeyboardMarkup(
        inline_keyboard=[
            nav,
            [
                InlineKeyboardButton(text="📈 За 7 дней", callback_data="his:st:7"),
                InlineKeyboardButton(text="🗓 За 30 дней", callback_data="his:st:30"),
            ],
        ]
    )


def history_stats_kb(today_iso: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📈 7 дней", callback_data="his:st:7"),
                InlineKeyboardButton(text="🗓 30 дней", callback_data="his:st:30"),
            ],
            [
                InlineKeyboardButton(text="📅 История по дням", callback_data=f"his:day:{today_iso}"),
            ],
        ]
    )


def settings_kb(user: UserProfile) -> InlineKeyboardMarkup:
    ev_btn = "🔕 Выкл. вечернее" if user.evening_reminder_enabled else "🔔 Вкл. вечернее"
    mo_btn = "🔕 Выкл. утреннее" if user.morning_digest_enabled else "🔔 Вкл. утреннее"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=ev_btn, callback_data="set:tog:evening"),
                InlineKeyboardButton(text="🕒 Время вечера", callback_data="set:time:evening"),
            ],
            [
                InlineKeyboardButton(text=mo_btn, callback_data="set:tog:morning"),
                InlineKeyboardButton(text="🕒 Время утра", callback_data="set:time:morning"),
            ],
            [
                InlineKeyboardButton(text="🌍 Изменить часовой пояс", callback_data="set:tz"),
            ],
        ]
    )
