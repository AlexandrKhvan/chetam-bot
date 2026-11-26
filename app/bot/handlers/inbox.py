from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.formatters import render_inbox
from app.bot.handlers.common import safe_edit
from app.bot.keyboards import BTN_INBOX, inbox_kb
from app.db.models import UserProfile
from app.services.task_service import TaskService
from app.services.time_utils import user_today_iso, user_tomorrow_iso

router = Router(name="inbox")


async def _render_inbox_view(
    task_service: TaskService, user: UserProfile, page: int = 0
):
    tasks = await task_service.list_inbox(user.user_id)
    today_iso = user_today_iso(user.timezone)
    tomorrow_iso = user_tomorrow_iso(user.timezone)
    max_page = max(0, (len(tasks) - 1) // 6)
    page = max(0, min(page, max_page))
    text = render_inbox(tasks, page=page)
    kb = inbox_kb(tasks, today_iso, tomorrow_iso, page=page)
    return text, kb


@router.message(Command("inbox"))
@router.message(F.text == BTN_INBOX)
async def show_inbox(
    message: Message,
    state: FSMContext,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    await state.clear()
    text, kb = await _render_inbox_view(task_service, user_profile, page=0)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("inb:pg:"))
async def cb_inbox_page(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    page = int(callback.data.split(":")[2])
    text, kb = await _render_inbox_view(task_service, user_profile, page=page)
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer()


@router.callback_query(F.data.startswith("inb:plan:"))
async def cb_inbox_plan(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    _, _, task_id_s, target_day, page_s = callback.data.split(":")
    await task_service.plan_task_for_date(user_profile.user_id, int(task_id_s), target_day)
    text, kb = await _render_inbox_view(task_service, user_profile, page=int(page_s))
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer("Запланировано ✅")


@router.callback_query(F.data.startswith("inb:prio:"))
async def cb_inbox_priority(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    _, _, task_id_s, page_s = callback.data.split(":")
    await task_service.cycle_priority(user_profile.user_id, int(task_id_s))
    text, kb = await _render_inbox_view(task_service, user_profile, page=int(page_s))
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer("Приоритет изменён")


@router.callback_query(F.data.startswith("inb:done:"))
async def cb_inbox_done(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    _, _, task_id_s, page_s = callback.data.split(":")
    today_iso = user_today_iso(user_profile.timezone)
    await task_service.toggle_done(user_profile.user_id, int(task_id_s), fallback_date=today_iso)
    text, kb = await _render_inbox_view(task_service, user_profile, page=int(page_s))
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer("Отмечено выполненным ✅")


@router.callback_query(F.data.startswith("inb:pool:"))
async def cb_inbox_to_pool(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    _, _, task_id_s, page_s = callback.data.split(":")
    await task_service.move_to_pool(user_profile.user_id, int(task_id_s))
    text, kb = await _render_inbox_view(task_service, user_profile, page=int(page_s))
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer("Перенесено в общий пул 🗂")


@router.callback_query(F.data.startswith("inb:del:"))
async def cb_inbox_delete(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    _, _, task_id_s, page_s = callback.data.split(":")
    await task_service.delete_task(user_profile.user_id, int(task_id_s))
    text, kb = await _render_inbox_view(task_service, user_profile, page=int(page_s))
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer("Удалено 🗑")
