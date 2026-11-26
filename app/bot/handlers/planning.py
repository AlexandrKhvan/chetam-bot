from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.formatters import (
    render_evening_pool_picker,
    render_evening_step1,
    render_evening_step2,
)
from app.bot.handlers.common import safe_edit
from app.bot.keyboards import (
    BTN_PLAN,
    evening_pool_picker_kb,
    evening_step1_kb,
    evening_step2_kb,
)
from app.db.models import UserProfile
from app.services.schedule_service import compute_free_windows
from app.services.task_service import TaskService
from app.services.time_utils import user_today_iso, user_tomorrow_iso

router = Router(name="planning")


async def _build_step1(task_service: TaskService, user: UserProfile):
    today_iso = user_today_iso(user.timezone)
    tomorrow_iso = user_tomorrow_iso(user.timezone)
    plan = await task_service.get_day_plan(user.user_id, today_iso, today_iso=today_iso)
    pending = [t for t in plan.tasks if t.status == "planned"]
    pool_tasks = await task_service.list_pool(user.user_id, today_iso=today_iso)
    return (
        render_evening_step1(plan, today_iso),
        evening_step1_kb(pending, today_iso, tomorrow_iso, pool_count=len(pool_tasks)),
    )


async def _build_step2(task_service: TaskService, user: UserProfile):
    today_iso = user_today_iso(user.timezone)
    tomorrow_iso = user_tomorrow_iso(user.timezone)
    tomorrow_plan = await task_service.get_day_plan(user.user_id, tomorrow_iso, today_iso=today_iso)
    inbox_tasks = await task_service.list_inbox(user.user_id, today_iso=today_iso)
    pool_tasks = await task_service.list_pool(user.user_id, today_iso=today_iso)
    windows = compute_free_windows(tomorrow_plan.schedule_events) if tomorrow_plan.schedule_events else None
    return (
        render_evening_step2(tomorrow_plan, inbox_tasks, today_iso, free_windows=windows),
        evening_step2_kb(inbox_tasks, tomorrow_iso, pool_count=len(pool_tasks)),
    )


async def _build_pool_picker(task_service: TaskService, user: UserProfile, page: int = 0):
    today_iso = user_today_iso(user.timezone)
    tomorrow_iso = user_tomorrow_iso(user.timezone)
    tomorrow_plan = await task_service.get_day_plan(user.user_id, tomorrow_iso)
    pool_tasks = await task_service.list_pool(user.user_id)
    max_page = max(0, (len(pool_tasks) - 1) // 8)
    page = max(0, min(page, max_page))
    return (
        render_evening_pool_picker(tomorrow_plan, pool_tasks, today_iso, page=page),
        evening_pool_picker_kb(pool_tasks, tomorrow_iso, page=page),
    )


@router.message(Command("plan"))
@router.message(F.text == BTN_PLAN)
async def cmd_evening_plan(
    message: Message,
    state: FSMContext,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    await state.clear()
    text, kb = await _build_step1(task_service, user_profile)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "evn:start")
async def cb_evening_start(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    text, kb = await _build_step1(task_service, user_profile)
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer()


@router.callback_query(F.data == "evn:step2")
async def cb_evening_step2(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    text, kb = await _build_step2(task_service, user_profile)
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer()


@router.callback_query(F.data.startswith("evn:done:"))
async def cb_evening_done(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    task_id = int(callback.data.split(":")[2])
    await task_service.toggle_done(user_profile.user_id, task_id)
    text, kb = await _build_step1(task_service, user_profile)
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer("Отмечено сделанным ✅")


@router.callback_query(F.data.startswith("evn:move:"))
async def cb_evening_move(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    task_id = int(callback.data.split(":")[2])
    tomorrow_iso = user_tomorrow_iso(user_profile.timezone)
    await task_service.plan_task_for_date(
        user_profile.user_id, task_id, tomorrow_iso, record_carry_over=True
    )
    text, kb = await _build_step1(task_service, user_profile)
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer("Перенесено на завтра ➡️")


@router.callback_query(F.data.startswith("evn:moveall:"))
async def cb_evening_move_all(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    _, _, from_day, to_day = callback.data.split(":")
    moved = await task_service.carry_over_all_pending(user_profile.user_id, from_day, to_day)
    text, kb = await _build_step2(task_service, user_profile)
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer(f"Перенесено задач: {moved} ➡️")


@router.callback_query(F.data.startswith("evn:inb:"))
async def cb_evening_to_inbox(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    task_id = int(callback.data.split(":")[2])
    await task_service.move_to_inbox(user_profile.user_id, task_id, record_carry_over=True)
    text, kb = await _build_step1(task_service, user_profile)
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer("Вернулось в инбокс 📥")


@router.callback_query(F.data.startswith("evn:del:"))
async def cb_evening_delete(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    task_id = int(callback.data.split(":")[2])
    await task_service.delete_task(user_profile.user_id, task_id)
    text, kb = await _build_step1(task_service, user_profile)
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer("Удалено 🗑")


@router.callback_query(F.data.startswith("evn:pick:"))
async def cb_evening_pick_inbox(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    _, _, task_id_s, tomorrow_iso = callback.data.split(":")
    await task_service.plan_task_for_date(user_profile.user_id, int(task_id_s), tomorrow_iso)
    text, kb = await _build_step2(task_service, user_profile)
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer("Добавлено в план на завтра ✅")


@router.callback_query(F.data.startswith("evn:topool:"))
async def cb_evening_to_pool(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    task_id = int(callback.data.split(":")[2])
    await task_service.move_to_pool(user_profile.user_id, task_id, record_carry_over=True)
    text, kb = await _build_step1(task_service, user_profile)
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer("Убрано в общий пул 🗂")


@router.callback_query(F.data.startswith("evn:pool:"))
async def cb_evening_open_pool(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    page = int(callback.data.split(":")[2])
    text, kb = await _build_pool_picker(task_service, user_profile, page=page)
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer()


@router.callback_query(F.data.startswith("evn:pickpool:"))
async def cb_evening_pick_from_pool(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    _, _, task_id_s, tomorrow_iso, page_s = callback.data.split(":")
    await task_service.plan_task_for_date(user_profile.user_id, int(task_id_s), tomorrow_iso)
    text, kb = await _build_pool_picker(task_service, user_profile, page=int(page_s))
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer("Забрано из пула на завтра ✅")
