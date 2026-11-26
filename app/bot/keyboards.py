from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from app.db.models import DayPlan, Reminder, Task, UserProfile
from app.services.time_utils import shift_date_iso

BTN_TODAY = "📅 Сегодня"
BTN_TOMORROW = "🌅 Завтра"
BTN_INBOX = "📥 Инбокс"
BTN_POOL = "🗂 Пул задач"
BTN_PLAN = "🌙 Вечерний план"
BTN_REMINDERS = "🔔 Напоминания"
BTN_SCHEDULE = "🎓 Расписание"
BTN_HISTORY = "📊 История"


def _clip(text: str, limit: int = 34) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_TODAY), KeyboardButton(text=BTN_TOMORROW)],
            [KeyboardButton(text=BTN_INBOX), KeyboardButton(text=BTN_POOL)],
            [KeyboardButton(text=BTN_PLAN), KeyboardButton(text=BTN_REMINDERS)],
            [KeyboardButton(text=BTN_SCHEDULE), KeyboardButton(text=BTN_HISTORY)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Напиши мысль/кучу задач или скинь .docx расписания…",
    )


def quick_capture_kb(task_id: int, today_iso: str, tomorrow_iso: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 Сегодня", callback_data=f"qc:plan:{task_id}:{today_iso}"),
                InlineKeyboardButton(text="🌅 Завтра", callback_data=f"qc:plan:{task_id}:{tomorrow_iso}"),
                InlineKeyboardButton(text="🗂 В пул", callback_data=f"qc:pool:{task_id}"),
            ],
            [
                InlineKeyboardButton(text="🔔 Напомнить", callback_data=f"rem:ask:{task_id}"),
                InlineKeyboardButton(text="🔴 Важно", callback_data=f"qc:prio:{task_id}"),
                InlineKeyboardButton(text="🗑", callback_data=f"qc:del:{task_id}"),
            ],
        ]
    )


def brain_dump_batch_kb(batch_id: str, today_iso: str, tomorrow_iso: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 Все сегодня", callback_data=f"bd:plan:{batch_id}:{today_iso}"),
                InlineKeyboardButton(text="🌅 Все завтра", callback_data=f"bd:plan:{batch_id}:{tomorrow_iso}"),
                InlineKeyboardButton(text="🗂 Все в пул", callback_data=f"bd:pool:{batch_id}"),
            ],
            [
                InlineKeyboardButton(text="🔗 Объединить в 1 задачу", callback_data=f"bd:merge:{batch_id}"),
                InlineKeyboardButton(text="🗑 Удалить всё", callback_data=f"bd:del:{batch_id}"),
            ],
        ]
    )


def webapp_launch_kb(webapp_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📱 Открыть CheTam Mini App", web_app=WebAppInfo(url=webapp_url))]
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

    next_day = shift_date_iso(plan.day, 1)
    for task in plan.tasks:
        icon = "✅" if task.status == "done" else "⬜"
        time_prefix = f"{task.planned_time} " if task.planned_time else ""
        if task.status == "done":
            label = f"{icon} {time_prefix}{_clip(task.title, 30)}"
            rows.append(
                [InlineKeyboardButton(text=label, callback_data=f"tk:tog:{task.id}:{plan.day}")]
            )
        else:
            label = f"{icon} {time_prefix}{_clip(task.title, 22)}"
            rows.append(
                [
                    InlineKeyboardButton(text=label, callback_data=f"tk:tog:{task.id}:{plan.day}"),
                    InlineKeyboardButton(text="➡️", callback_data=f"tk:qmv:{task.id}:{plan.day}:{next_day}"),
                    InlineKeyboardButton(text="🗂", callback_data=f"tk:qpool:{task.id}:{plan.day}"),
                ]
            )

    prev_day = shift_date_iso(plan.day, -1)

    rows.append(
        [
            InlineKeyboardButton(text="➕ Задача", callback_data=f"day:add:{plan.day}"),
            InlineKeyboardButton(text="📥 Инбокс", callback_data=f"day:pick:{plan.day}"),
            InlineKeyboardButton(text="🗂 Пул", callback_data=f"day:pool:{plan.day}"),
            InlineKeyboardButton(text="⚙️", callback_data=f"day:mgr:{plan.day}"),
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
                    text=f"📌 {_clip(task.title, 18)}",
                    callback_data=f"tk:prio:{task.id}:{plan.day}",
                ),
                InlineKeyboardButton(
                    text="🔔",
                    callback_data=f"rem:ask:{task.id}",
                ),
                InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"tk:mv:{task.id}:{plan.day}:{next_day}",
                ),
                InlineKeyboardButton(
                    text="🗂",
                    callback_data=f"tk:pool:{task.id}:{plan.day}",
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
                    text=f"• {_clip(task.title, 16)}",
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
                    text="🗂",
                    callback_data=f"inb:pool:{task.id}:{page}",
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


def pool_kb(
    tasks: list[Task],
    today_iso: str,
    tomorrow_iso: str,
    *,
    tags: list[str] | None = None,
    active_tag: str = "",
    page: int = 0,
    page_size: int = 6,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if tags:
        tag_row: list[InlineKeyboardButton] = [
            InlineKeyboardButton(
                text=("🎯 Все" if not active_tag else "Все"),
                callback_data="pl:tag:ALL",
            )
        ]
        for tg_name in tags[:4]:
            mark = "🎯 " if tg_name == active_tag else ""
            tag_row.append(
                InlineKeyboardButton(text=f"{mark}#{tg_name}", callback_data=f"pl:tag:{tg_name}")
            )
        rows.append(tag_row)

    start = page * page_size
    chunk = tasks[start : start + page_size]

    for task in chunk:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"• {_clip(task.title, 16)}",
                    callback_data=f"pl:prio:{task.id}:{page}:{active_tag or 'ALL'}",
                ),
                InlineKeyboardButton(
                    text="📅",
                    callback_data=f"pl:plan:{task.id}:{today_iso}:{page}:{active_tag or 'ALL'}",
                ),
                InlineKeyboardButton(
                    text="🌅",
                    callback_data=f"pl:plan:{task.id}:{tomorrow_iso}:{page}:{active_tag or 'ALL'}",
                ),
                InlineKeyboardButton(
                    text="🔔",
                    callback_data=f"rem:ask:{task.id}",
                ),
                InlineKeyboardButton(
                    text="🗑",
                    callback_data=f"pl:del:{task.id}:{page}:{active_tag or 'ALL'}",
                ),
            ]
        )

    total_pages = max(1, (len(tasks) + page_size - 1) // page_size)
    if total_pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    text="◀️", callback_data=f"pl:pg:{page - 1}:{active_tag or 'ALL'}"
                )
            )
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
        if page + 1 < total_pages:
            nav.append(
                InlineKeyboardButton(
                    text="▶️", callback_data=f"pl:pg:{page + 1}:{active_tag or 'ALL'}"
                )
            )
        rows.append(nav)

    rows.append(
        [
            InlineKeyboardButton(text="➕ Добавить в пул", callback_data="pl:add"),
            InlineKeyboardButton(text="🌙 Вечерний план", callback_data="evn:start"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def evening_step1_kb(
    pending_tasks: list[Task], today_iso: str, tomorrow_iso: str, pool_count: int = 0
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for task in pending_tasks[:8]:
        rows.append(
            [
                InlineKeyboardButton(text=_clip(task.title, 16), callback_data="noop"),
                InlineKeyboardButton(text="✅", callback_data=f"evn:done:{task.id}"),
                InlineKeyboardButton(text="➡️", callback_data=f"evn:move:{task.id}"),
                InlineKeyboardButton(text="🗂", callback_data=f"evn:topool:{task.id}"),
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
    pool_label = f"🗂 Взять из пула ({pool_count})" if pool_count else "🗂 Взять из пула"
    rows.append(
        [
            InlineKeyboardButton(text=pool_label, callback_data="evn:pool:0"),
            InlineKeyboardButton(text="Собрать завтра ▶️", callback_data="evn:step2"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def evening_step2_kb(
    inbox_tasks: list[Task], tomorrow_iso: str, pool_count: int = 0
) -> InlineKeyboardMarkup:
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
    pool_label = f"🗂 Взять из пула ({pool_count})" if pool_count else "🗂 Открыть пул задач"
    rows.append(
        [
            InlineKeyboardButton(text=pool_label, callback_data="evn:pool:0"),
            InlineKeyboardButton(text="✏️ Новая задача", callback_data=f"day:add:{tomorrow_iso}"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="⬅️ Итоги", callback_data="evn:start"),
            InlineKeyboardButton(text="✅ Готово — план завтра", callback_data=f"day:show:{tomorrow_iso}"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def evening_pool_picker_kb(
    pool_tasks: list[Task], tomorrow_iso: str, page: int = 0, page_size: int = 8
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    start = page * page_size
    for task in pool_tasks[start : start + page_size]:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"➕ {_clip(task.title, 34)}",
                    callback_data=f"evn:pickpool:{task.id}:{tomorrow_iso}:{page}",
                )
            ]
        )

    total_pages = max(1, (len(pool_tasks) + page_size - 1) // page_size)
    if total_pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️", callback_data=f"evn:pool:{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
        if page + 1 < total_pages:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=f"evn:pool:{page + 1}"))
        rows.append(nav)

    rows.append(
        [
            InlineKeyboardButton(text="⬅️ К вечернему плану", callback_data="evn:step2"),
            InlineKeyboardButton(text="✅ План на завтра", callback_data=f"day:show:{tomorrow_iso}"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reminders_list_kb(reminders: list[Reminder]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for rem in reminders[:10]:
        rows.append(
            [
                InlineKeyboardButton(text=f"🔔 {_clip(rem.text, 24)}", callback_data="noop"),
                InlineKeyboardButton(text="🗑", callback_data=f"rem:del:{rem.id}"),
            ]
        )
    rows.append([InlineKeyboardButton(text="➕ Новое напоминание", callback_data="rem:new")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def task_remind_presets_kb(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⏰ +15 мин", callback_data=f"rem:set:{task_id}:15m"),
                InlineKeyboardButton(text="⏰ +1 час", callback_data=f"rem:set:{task_id}:1h"),
            ],
            [
                InlineKeyboardButton(text="🌙 Сегодня 20:00", callback_data=f"rem:set:{task_id}:eve"),
                InlineKeyboardButton(text="🌅 Завтра 09:00", callback_data=f"rem:set:{task_id}:tom"),
            ],
            [
                InlineKeyboardButton(text="✏️ Своё время", callback_data=f"rem:custom:{task_id}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="rem:cancel"),
            ],
        ]
    )


def reminder_fired_kb(reminder_id: int, task_id: int | None = None) -> InlineKeyboardMarkup:
    top_row: list[InlineKeyboardButton] = []
    if task_id:
        top_row.append(InlineKeyboardButton(text="✅ Сделано", callback_data=f"rem:done:{reminder_id}:{task_id}"))
    else:
        top_row.append(InlineKeyboardButton(text="✅ Понял", callback_data=f"rem:ack:{reminder_id}"))
    top_row.append(InlineKeyboardButton(text="💤 +15 мин", callback_data=f"rem:snz:{reminder_id}:15"))
    return InlineKeyboardMarkup(
        inline_keyboard=[
            top_row,
            [
                InlineKeyboardButton(text="💤 +1 час", callback_data=f"rem:snz:{reminder_id}:60"),
                InlineKeyboardButton(text="🌅 Завтра 09:00", callback_data=f"rem:snz:{reminder_id}:tom"),
            ],
        ]
    )


def schedule_week_kb(
    anchor_iso: str,
    start_iso: str,
    end_iso: str,
    today_iso: str,
    *,
    shared_group: str = "",
) -> InlineKeyboardMarkup:
    prev_w = shift_date_iso(anchor_iso, -7)
    next_w = shift_date_iso(anchor_iso, 7)
    rows = [
        [
            InlineKeyboardButton(text="◀️ Пред. нед.", callback_data=f"sch:wk:{prev_w}"),
            InlineKeyboardButton(text="Текущая", callback_data=f"sch:wk:{today_iso}"),
            InlineKeyboardButton(text="След. нед. ▶️", callback_data=f"sch:wk:{next_w}"),
        ],
        [
            InlineKeyboardButton(text="➕ Добавить / вставить", callback_data="sch:add"),
            InlineKeyboardButton(text="🗑 Очистить неделю", callback_data=f"sch:clr:{start_iso}:{end_iso}"),
        ],
    ]
    if shared_group:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🔄 Подтянуть общее расписание {shared_group}",
                    callback_data=f"sch:sync:{shared_group}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def schedule_import_confirm_kb(
    groups: list[str] | None = None, selected_group: str = ""
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if groups and len(groups) > 1:
        group_row: list[InlineKeyboardButton] = []
        for g in groups[:4]:
            mark = "🎯 " if g.upper() == selected_group.upper() else ""
            group_row.append(
                InlineKeyboardButton(text=f"{mark}{g}", callback_data=f"sch:grp:{g}")
            )
        all_mark = "🎯 " if not selected_group else ""
        group_row.append(InlineKeyboardButton(text=f"{all_mark}Все", callback_data="sch:grp:ALL"))
        rows.append(group_row)

    rows.append(
        [
            InlineKeyboardButton(
                text="✅ Сохранить (заменить эти дни)",
                callback_data="sch:imp:replace",
            )
        ]
    )
    if selected_group:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"👥 Сохранить + поделиться с {selected_group}",
                    callback_data="sch:imp:share",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="➕ Добавить к текущему",
                callback_data="sch:imp:append",
            ),
            InlineKeyboardButton(text="❌ Отмена", callback_data="sch:imp:cancel"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def onboarding_tz_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🕒 Москва (+03)", callback_data="onb:tz:Europe/Moscow"),
                InlineKeyboardButton(text="🕒 Екб / Астана (+05)", callback_data="onb:tz:Asia/Yekaterinburg"),
            ],
            [
                InlineKeyboardButton(text="🕒 Омск / Алматы (+06)", callback_data="onb:tz:Asia/Almaty"),
                InlineKeyboardButton(text="🕒 Новосибирск (+07)", callback_data="onb:tz:Asia/Novosibirsk"),
            ],
            [
                InlineKeyboardButton(text="⏭ Пропустить настройку", callback_data="onb:skip"),
            ],
        ]
    )


def onboarding_group_kb(shared_groups: list[str] | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    presets = list(dict.fromkeys([*(shared_groups or []), "ВМ-21", "ВМ-22"]))[:4]
    if presets:
        rows.append(
            [InlineKeyboardButton(text=f"🎓 {g}", callback_data=f"onb:grp:{g}") for g in presets[:3]]
        )
    rows.append([InlineKeyboardButton(text="⏭ Без группы / настрою позже", callback_data="onb:skip")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
    cls_btn = (
        f"🎓 Пары: за {user.class_reminder_minutes} мин"
        if user.class_reminder_minutes > 0
        else "🎓 Пары: выкл 🔕"
    )
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
                InlineKeyboardButton(text=cls_btn, callback_data="set:tog:class"),
                InlineKeyboardButton(text="🌍 Часовой пояс", callback_data="set:tz"),
            ],
        ]
    )
