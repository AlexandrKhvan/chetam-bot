from __future__ import annotations

import re
import secrets
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.formatters import PRIORITY_ICON, render_day_plan
from app.bot.handlers.common import safe_edit
from app.bot.keyboards import (
    BTN_TODAY,
    BTN_TOMORROW,
    brain_dump_batch_kb,
    day_manage_kb,
    day_plan_kb,
    pick_from_inbox_kb,
    quick_capture_kb,
)
from app.bot.states import AddTaskStates
from app.db.models import UserProfile
from app.services.brain_dump import split_brain_dump
from app.services.schedule_service import ScheduleService
from app.services.task_service import TaskService
from app.services.time_utils import format_date_ru, user_today, user_today_iso, user_tomorrow_iso

router = Router(name="tasks")
quick_capture_router = Router(name="quick_capture")

# Bounded in-memory cache of recent brain-dump batches: batch_id -> (user_id, task_ids, original_text)
_RECENT_BATCHES: dict[str, tuple[int, list[int], str]] = {}

LEADING_TIME_RE = re.compile(r"^(\d{1,2})[:.](\d{2})\s+(.+)$")


def _split_time_and_title(raw: str) -> tuple[str | None, str]:
    m = LEADING_TIME_RE.match(raw.strip())
    if m:
        h, minute, rest = int(m.group(1)), int(m.group(2)), m.group(3).strip()
        if 0 <= h <= 23 and 0 <= minute <= 59 and rest:
            return f"{h:02d}:{minute:02d}", rest
    return None, raw.strip()


async def _render_day_view(
    task_service: TaskService, user: UserProfile, day_iso: str, *, manage_mode: bool = False
):
    today_iso = user_today_iso(user.timezone)
    plan = await task_service.get_day_plan(user.user_id, day_iso)
    text = render_day_plan(plan, today_iso, manage_mode=manage_mode)
    kb = day_manage_kb(plan) if manage_mode else day_plan_kb(plan, today_iso)
    return text, kb


@router.message(Command("today"))
@router.message(F.text == BTN_TODAY)
async def cmd_today(
    message: Message,
    state: FSMContext,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    await state.clear()
    today_iso = user_today_iso(user_profile.timezone)
    text, kb = await _render_day_view(task_service, user_profile, today_iso)
    await message.answer(text, reply_markup=kb)


@router.message(Command("tomorrow"))
@router.message(F.text == BTN_TOMORROW)
async def cmd_tomorrow(
    message: Message,
    state: FSMContext,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    await state.clear()
    tomorrow_iso = user_tomorrow_iso(user_profile.timezone)
    text, kb = await _render_day_view(task_service, user_profile, tomorrow_iso)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("day:show:"))
async def cb_day_show(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    day_iso = callback.data.split(":")[2]
    text, kb = await _render_day_view(task_service, user_profile, day_iso)
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer()


@router.callback_query(F.data.startswith("day:mgr:"))
async def cb_day_manage(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    day_iso = callback.data.split(":")[2]
    text, kb = await _render_day_view(task_service, user_profile, day_iso, manage_mode=True)
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer("Режим правки ⚙️")


@router.callback_query(F.data.startswith("day:add:"))
async def cb_day_add_start(
    callback: CallbackQuery,
    state: FSMContext,
    user_profile: UserProfile,
) -> None:
    day_iso = callback.data.split(":")[2]
    today_iso = user_today_iso(user_profile.timezone)
    await state.set_state(AddTaskStates.waiting_title)
    await state.update_data(target_day=day_iso)
    if callback.message:
        await callback.message.answer(
            f"✏️ Напиши задачу на <b>{escape(format_date_ru(day_iso, today_iso))}</b>.\n"
            "Можно указать время в начале (например, <code>18:30 Сделать лабу</code>) "
            "или отправить сразу несколько строк.\n\n"
            "<i>/cancel — отмена</i>"
        )
    await callback.answer()


@router.message(AddTaskStates.waiting_title, F.text)
async def handle_day_add_input(
    message: Message,
    state: FSMContext,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    raw = (message.text or "").strip()
    if raw.startswith("/"):
        return
    data = await state.get_data()
    target_day = data.get("target_day") or user_today_iso(user_profile.timezone)
    lines = [line.strip().lstrip("-•*—– ").strip() for line in raw.splitlines() if line.strip()]
    for line in lines:
        planned_time, title = _split_time_and_title(line)
        if title:
            await task_service.create_task(
                user_profile.user_id,
                title,
                planned_date=target_day,
                planned_time=planned_time,
            )
    await state.clear()
    text, kb = await _render_day_view(task_service, user_profile, target_day)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("day:pick:"))
async def cb_day_pick_inbox(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    target_day = callback.data.split(":")[2]
    today_iso = user_today_iso(user_profile.timezone)
    inbox_tasks = await task_service.list_inbox(user_profile.user_id)
    if not inbox_tasks:
        await callback.answer("Инбокс пуст ✨", show_alert=True)
        return
    if callback.message:
        await safe_edit(
            callback.message,
            f"📥 <b>Выбери задачи из инбокса на {escape(format_date_ru(target_day, today_iso))}:</b>",
            pick_from_inbox_kb(inbox_tasks, target_day, back_callback=f"day:show:{target_day}"),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("day:pool:"))
async def cb_day_pick_pool(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    target_day = callback.data.split(":")[2]
    today_iso = user_today_iso(user_profile.timezone)
    pool_tasks = await task_service.list_pool(user_profile.user_id)
    if not pool_tasks:
        await callback.answer("Пул задач пуст 🗂", show_alert=True)
        return
    if callback.message:
        await safe_edit(
            callback.message,
            f"🗂 <b>Выбери задачи из общего пула на {escape(format_date_ru(target_day, today_iso))}:</b>",
            pick_from_inbox_kb(pool_tasks, target_day, back_callback=f"day:show:{target_day}"),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("day:pull:"))
async def cb_day_pull_from_inbox(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    _, _, task_id_s, target_day = callback.data.split(":")
    await task_service.plan_task_for_date(user_profile.user_id, int(task_id_s), target_day)
    inbox_tasks = await task_service.list_inbox(user_profile.user_id)
    if not inbox_tasks:
        text, kb = await _render_day_view(task_service, user_profile, target_day)
        if callback.message:
            await safe_edit(callback.message, text, kb)
    else:
        today_iso = user_today_iso(user_profile.timezone)
        if callback.message:
            await safe_edit(
                callback.message,
                f"📥 <b>Выбери задачи из инбокса на {escape(format_date_ru(target_day, today_iso))}:</b>",
                pick_from_inbox_kb(inbox_tasks, target_day, back_callback=f"day:show:{target_day}"),
            )
    await callback.answer("Добавлено в план ✅")


@router.callback_query(F.data.startswith("tk:tog:"))
async def cb_toggle_task(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    _, _, task_id_s, day_iso = callback.data.split(":")
    updated = await task_service.toggle_done(user_profile.user_id, int(task_id_s), fallback_date=day_iso)
    text, kb = await _render_day_view(task_service, user_profile, day_iso)
    if callback.message:
        await safe_edit(callback.message, text, kb)
    label = "Сделано! ✅" if updated and updated.status == "done" else "Возвращено в план ⬜"
    await callback.answer(label)


@router.callback_query(F.data.startswith("ev:tog:"))
async def cb_toggle_event(
    callback: CallbackQuery,
    task_service: TaskService,
    schedule_service: ScheduleService,
    user_profile: UserProfile,
) -> None:
    _, _, event_id_s, day_iso = callback.data.split(":")
    updated = await schedule_service.toggle_done(user_profile.user_id, int(event_id_s))
    text, kb = await _render_day_view(task_service, user_profile, day_iso)
    if callback.message:
        await safe_edit(callback.message, text, kb)
    label = "Отмечено ✅" if updated and updated.is_done else "Снята отметка ▫️"
    await callback.answer(label)


@router.callback_query(F.data.startswith("tk:prio:"))
async def cb_task_priority(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    _, _, task_id_s, day_iso = callback.data.split(":")
    await task_service.cycle_priority(user_profile.user_id, int(task_id_s))
    text, kb = await _render_day_view(task_service, user_profile, day_iso, manage_mode=True)
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer("Приоритет изменён")


@router.callback_query(F.data.startswith("tk:mv:"))
async def cb_task_move(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    _, _, task_id_s, from_day, to_day = callback.data.split(":")
    await task_service.plan_task_for_date(
        user_profile.user_id, int(task_id_s), to_day, record_carry_over=True
    )
    text, kb = await _render_day_view(task_service, user_profile, from_day, manage_mode=True)
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer("Перенесено на следующий день ➡️")


@router.callback_query(F.data.startswith("tk:inb:"))
async def cb_task_to_inbox(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    _, _, task_id_s, day_iso = callback.data.split(":")
    await task_service.move_to_inbox(user_profile.user_id, int(task_id_s), record_carry_over=True)
    text, kb = await _render_day_view(task_service, user_profile, day_iso, manage_mode=True)
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer("Убрано в инбокс 📥")


@router.callback_query(F.data.startswith("tk:pool:"))
async def cb_task_to_pool(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    _, _, task_id_s, day_iso = callback.data.split(":")
    await task_service.move_to_pool(user_profile.user_id, int(task_id_s), record_carry_over=True)
    text, kb = await _render_day_view(task_service, user_profile, day_iso, manage_mode=True)
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer("Убрано в общий пул 🗂")


@router.callback_query(F.data.startswith("tk:del:"))
async def cb_task_delete(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    _, _, task_id_s, day_iso = callback.data.split(":")
    await task_service.delete_task(user_profile.user_id, int(task_id_s))
    text, kb = await _render_day_view(task_service, user_profile, day_iso, manage_mode=True)
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer("Удалено 🗑")


@router.callback_query(F.data.startswith("ev:del:"))
async def cb_event_delete(
    callback: CallbackQuery,
    task_service: TaskService,
    schedule_service: ScheduleService,
    user_profile: UserProfile,
) -> None:
    _, _, event_id_s, day_iso = callback.data.split(":")
    await schedule_service.delete_event(user_profile.user_id, int(event_id_s))
    text, kb = await _render_day_view(task_service, user_profile, day_iso, manage_mode=True)
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer("Пара удалена 🗑")


# --- Quick Capture Callbacks ---


@router.callback_query(F.data.startswith("qc:plan:"))
async def cb_quick_plan(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    _, _, task_id_s, target_day = callback.data.split(":")
    task = await task_service.plan_task_for_date(user_profile.user_id, int(task_id_s), target_day)
    today_iso = user_today_iso(user_profile.timezone)
    if task and callback.message:
        await safe_edit(
            callback.message,
            f"📅 Запланировано на <b>{escape(format_date_ru(target_day, today_iso))}</b>:\n"
            f"• {escape(task.title)}",
        )
    await callback.answer("Запланировано ✅")


@router.callback_query(F.data.startswith("qc:pool:"))
async def cb_quick_to_pool(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    task_id = int(callback.data.split(":")[2])
    task = await task_service.move_to_pool(user_profile.user_id, task_id)
    if task and callback.message:
        await safe_edit(
            callback.message,
            f"🗂 Сохранено в общий пул задач:\n• <b>{escape(task.title)}</b>",
        )
    await callback.answer("В общем пуле 🗂")


@router.callback_query(F.data.startswith("qc:prio:"))
async def cb_quick_priority(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    task_id = int(callback.data.split(":")[2])
    task = await task_service.set_priority(user_profile.user_id, task_id, 1)
    today_iso = user_today_iso(user_profile.timezone)
    tomorrow_iso = user_tomorrow_iso(user_profile.timezone)
    if task and callback.message:
        await safe_edit(
            callback.message,
            f"📥 В инбоксе (🔴 важно):\n• <b>{escape(task.title)}</b>",
            quick_capture_kb(task.id, today_iso, tomorrow_iso),
        )
    await callback.answer("Отмечено важным 🔴")


@router.callback_query(F.data.startswith("qc:del:"))
async def cb_quick_delete(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    task_id = int(callback.data.split(":")[2])
    await task_service.delete_task(user_profile.user_id, task_id)
    if callback.message:
        await safe_edit(callback.message, "🗑 Задача удалена.")
    await callback.answer("Удалено")


@router.callback_query(F.data.startswith("bd:plan:"))
async def cb_brain_dump_plan_all(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    _, _, batch_id, target_day = callback.data.split(":")
    entry = _RECENT_BATCHES.get(batch_id)
    if not entry or entry[0] != user_profile.user_id:
        await callback.answer("Пакет устарел, открой Инбокс.", show_alert=True)
        return
    _, task_ids, _ = entry
    for tid in task_ids:
        await task_service.plan_task_for_date(user_profile.user_id, tid, target_day)
    today_iso = user_today_iso(user_profile.timezone)
    if callback.message:
        await safe_edit(
            callback.message,
            f"📅 Все задачи (<b>{len(task_ids)}</b>) перенесены на <b>{escape(format_date_ru(target_day, today_iso))}</b>!",
        )
    await callback.answer("Запланировано ✅")


@router.callback_query(F.data.startswith("bd:pool:"))
async def cb_brain_dump_pool_all(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    batch_id = callback.data.split(":")[2]
    entry = _RECENT_BATCHES.get(batch_id)
    if not entry or entry[0] != user_profile.user_id:
        await callback.answer("Пакет устарел, открой Инбокс.", show_alert=True)
        return
    _, task_ids, _ = entry
    for tid in task_ids:
        await task_service.move_to_pool(user_profile.user_id, tid)
    if callback.message:
        await safe_edit(
            callback.message,
            f"🗂 Все задачи (<b>{len(task_ids)}</b>) перенесены в общий пул!",
        )
    await callback.answer("В общем пуле 🗂")


@router.callback_query(F.data.startswith("bd:merge:"))
async def cb_brain_dump_merge(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    batch_id = callback.data.split(":")[2]
    entry = _RECENT_BATCHES.pop(batch_id, None)
    if not entry or entry[0] != user_profile.user_id:
        await callback.answer("Пакет устарел.", show_alert=True)
        return
    _, task_ids, original_text = entry
    for tid in task_ids:
        await task_service.delete_task(user_profile.user_id, tid)
    single = await task_service.create_task(user_profile.user_id, original_text)
    today_iso = user_today_iso(user_profile.timezone)
    tomorrow_iso = user_tomorrow_iso(user_profile.timezone)
    if callback.message:
        await safe_edit(
            callback.message,
            f"📥 Объединил обратно в одну задачу:\n• <b>{escape(single.title)}</b>",
            quick_capture_kb(single.id, today_iso, tomorrow_iso),
        )
    await callback.answer("Объединено в 1 задачу 🔗")


@router.callback_query(F.data.startswith("bd:del:"))
async def cb_brain_dump_delete(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    batch_id = callback.data.split(":")[2]
    entry = _RECENT_BATCHES.pop(batch_id, None)
    if not entry or entry[0] != user_profile.user_id:
        await callback.answer("Пакет устарел.", show_alert=True)
        return
    _, task_ids, _ = entry
    for tid in task_ids:
        await task_service.delete_task(user_profile.user_id, tid)
    if callback.message:
        await safe_edit(callback.message, f"🗑 Удалено задач: <b>{len(task_ids)}</b>.")
    await callback.answer("Удалено")


# --- Catch-all Quick Capture (registered LAST in dispatcher) ---


@quick_capture_router.message(StateFilter(None), F.text)
async def handle_quick_capture(
    message: Message,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    raw = (message.text or "").strip()
    if not raw or raw.startswith("/"):
        return

    today = user_today(user_profile.timezone)
    today_iso = today.isoformat()
    tomorrow_iso = user_tomorrow_iso(user_profile.timezone)

    drafts = split_brain_dump(raw, today=today)
    if not drafts:
        return

    if len(drafts) == 1:
        d = drafts[0]
        task = await task_service.create_task(
            user_profile.user_id,
            d.title,
            planned_date=d.planned_date,
            planned_time=d.planned_time,
            priority=d.priority,
        )
        prio = PRIORITY_ICON.get(task.priority, "🟡")
        time_part = f"<code>{escape(task.planned_time)}</code> " if task.planned_time else ""
        if task.planned_date:
            where = f"📅 На <b>{escape(format_date_ru(task.planned_date, today_iso))}</b>"
        else:
            where = "📥 Сохранил в инбокс"
        await message.answer(
            f"{where}:\n• {prio} {time_part}<b>{escape(task.title)}</b>",
            reply_markup=quick_capture_kb(task.id, today_iso, tomorrow_iso),
        )
        return

    created = []
    for d in drafts:
        created.append(
            await task_service.create_task(
                user_profile.user_id,
                d.title,
                planned_date=d.planned_date,
                planned_time=d.planned_time,
                priority=d.priority,
            )
        )

    batch_id = secrets.token_hex(4)
    _RECENT_BATCHES[batch_id] = (user_profile.user_id, [t.id for t in created], raw)
    if len(_RECENT_BATCHES) > 300:
        oldest = next(iter(_RECENT_BATCHES))
        _RECENT_BATCHES.pop(oldest, None)

    lines = [f"🧠 <b>Разобрал сообщение на {len(created)} задач:</b>", ""]
    for idx, t in enumerate(created[:12], start=1):
        prio = PRIORITY_ICON.get(t.priority, "🟡")
        time_part = f"<code>{escape(t.planned_time)}</code> " if t.planned_time else ""
        if t.planned_date == today_iso:
            tag = " <i>(сегодня)</i>"
        elif t.planned_date == tomorrow_iso:
            tag = " <i>(завтра)</i>"
        elif t.planned_date:
            tag = f" <i>({escape(format_date_ru(t.planned_date, today_iso))})</i>"
        else:
            tag = ""
        lines.append(f"{idx}. {prio} {time_part}{escape(t.title)}{tag}")
    if len(created) > 12:
        lines.append(f"<i>…и ещё {len(created) - 12}</i>")

    await message.answer(
        "\n".join(lines),
        reply_markup=brain_dump_batch_kb(batch_id, today_iso, tomorrow_iso),
    )
