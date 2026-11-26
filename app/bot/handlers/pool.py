from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.formatters import render_pool
from app.bot.handlers.common import safe_edit
from app.bot.keyboards import BTN_POOL, pool_kb
from app.bot.states import AddPoolTaskStates
from app.db.models import UserProfile
from app.services.brain_dump import split_brain_dump
from app.services.task_service import TaskService
from app.services.time_utils import user_today, user_today_iso, user_tomorrow_iso

router = Router(name="pool")


async def _render_pool_view(
    task_service: TaskService, user: UserProfile, *, active_tag: str = "", page: int = 0
):
    today_iso = user_today_iso(user.timezone)
    tomorrow_iso = user_tomorrow_iso(user.timezone)
    all_tags = await task_service.list_pool_tags(user.user_id)
    if active_tag and active_tag not in all_tags:
        active_tag = ""
    tasks = await task_service.list_pool(
        user.user_id, tag=active_tag or None, today_iso=today_iso
    )
    max_page = max(0, (len(tasks) - 1) // 6)
    page = max(0, min(page, max_page))
    return (
        render_pool(tasks, today_iso, active_tag=active_tag, page=page),
        pool_kb(
            tasks,
            today_iso,
            tomorrow_iso,
            tags=all_tags,
            active_tag=active_tag,
            page=page,
        ),
    )


@router.message(Command("pool"))
@router.message(F.text == BTN_POOL)
async def cmd_pool(
    message: Message,
    state: FSMContext,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    await state.clear()
    text, kb = await _render_pool_view(task_service, user_profile, page=0)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("pl:tag:"))
async def cb_pool_tag_filter(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    chosen = callback.data.split(":", 2)[2]
    active_tag = "" if chosen == "ALL" else chosen
    text, kb = await _render_pool_view(
        task_service, user_profile, active_tag=active_tag, page=0
    )
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer(f"Фильтр: #{active_tag}" if active_tag else "Все задачи пула")


@router.callback_query(F.data.startswith("pl:pg:"))
async def cb_pool_page(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    parts = callback.data.split(":")
    page = int(parts[2])
    active_tag = "" if len(parts) < 4 or parts[3] == "ALL" else parts[3]
    text, kb = await _render_pool_view(
        task_service, user_profile, active_tag=active_tag, page=page
    )
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer()


@router.callback_query(F.data == "pl:add")
async def cb_pool_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddPoolTaskStates.waiting_title)
    if callback.message:
        await callback.message.answer(
            "🗂 <b>Добавить в общий пул задач</b>\n\n"
            "Напиши одну задачу или сразу несколько (можно с <code>#тегами</code> и дедлайнами вроде <code>до 05.12</code>).\n"
            "<i>/cancel — отмена</i>"
        )
    await callback.answer()


@router.message(AddPoolTaskStates.waiting_title, F.text)
async def handle_pool_add_input(
    message: Message,
    state: FSMContext,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    raw = (message.text or "").strip()
    if raw.startswith("/"):
        return
    today = user_today(user_profile.timezone)
    drafts = split_brain_dump(raw, today=today)
    created = 0
    for d in drafts:
        await task_service.create_task(
            user_profile.user_id,
            d.title,
            deadline_date=d.deadline_date,
            tags=d.tags,
            priority=d.priority,
            initial_status="pool",
            today_iso=today.isoformat(),
        )
        created += 1
    await state.clear()
    text, kb = await _render_pool_view(task_service, user_profile, page=0)
    await message.answer(f"✅ Добавлено в пул: <b>{created}</b>\n\n{text}", reply_markup=kb)


@router.callback_query(F.data.startswith("pl:plan:"))
async def cb_pool_plan(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    parts = callback.data.split(":")
    task_id_s, target_day, page_s = parts[2], parts[3], parts[4]
    active_tag = "" if len(parts) < 6 or parts[5] == "ALL" else parts[5]
    await task_service.plan_task_for_date(user_profile.user_id, int(task_id_s), target_day)
    text, kb = await _render_pool_view(
        task_service, user_profile, active_tag=active_tag, page=int(page_s)
    )
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer("Забрано из пула в план ✅")


@router.callback_query(F.data.startswith("pl:prio:"))
async def cb_pool_priority(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    parts = callback.data.split(":")
    task_id_s, page_s = parts[2], parts[3]
    active_tag = "" if len(parts) < 5 or parts[4] == "ALL" else parts[4]
    await task_service.cycle_priority(user_profile.user_id, int(task_id_s))
    text, kb = await _render_pool_view(
        task_service, user_profile, active_tag=active_tag, page=int(page_s)
    )
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer("Приоритет изменён")


@router.callback_query(F.data.startswith("pl:del:"))
async def cb_pool_delete(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    parts = callback.data.split(":")
    task_id_s, page_s = parts[2], parts[3]
    active_tag = "" if len(parts) < 5 or parts[4] == "ALL" else parts[4]
    await task_service.delete_task(user_profile.user_id, int(task_id_s))
    text, kb = await _render_pool_view(
        task_service, user_profile, active_tag=active_tag, page=int(page_s)
    )
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer("Удалено 🗑")
