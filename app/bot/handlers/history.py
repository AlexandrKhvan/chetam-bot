from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.formatters import render_daily_history, render_period_stats
from app.bot.handlers.common import safe_edit
from app.bot.keyboards import BTN_HISTORY, history_day_kb, history_stats_kb
from app.db.models import UserProfile
from app.services.history_service import HistoryService
from app.services.time_utils import user_today_iso

router = Router(name="history")


@router.message(Command("history"))
@router.message(F.text == BTN_HISTORY)
async def cmd_history(
    message: Message,
    state: FSMContext,
    history_service: HistoryService,
    user_profile: UserProfile,
) -> None:
    await state.clear()
    today_iso = user_today_iso(user_profile.timezone)
    stats = await history_service.get_period_stats(user_profile.user_id, today_iso, days=7)
    await message.answer(
        render_period_stats(stats),
        reply_markup=history_stats_kb(today_iso),
    )


@router.callback_query(F.data.startswith("his:st:"))
async def cb_history_stats(
    callback: CallbackQuery,
    history_service: HistoryService,
    user_profile: UserProfile,
) -> None:
    days = int(callback.data.split(":")[2])
    today_iso = user_today_iso(user_profile.timezone)
    stats = await history_service.get_period_stats(user_profile.user_id, today_iso, days=days)
    if callback.message:
        await safe_edit(
            callback.message,
            render_period_stats(stats),
            history_stats_kb(today_iso),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("his:day:"))
async def cb_history_day(
    callback: CallbackQuery,
    history_service: HistoryService,
    user_profile: UserProfile,
) -> None:
    day_iso = callback.data.split(":")[2]
    today_iso = user_today_iso(user_profile.timezone)
    summary = await history_service.get_daily_summary(user_profile.user_id, day_iso)
    if callback.message:
        await safe_edit(
            callback.message,
            render_daily_history(summary, today_iso),
            history_day_kb(day_iso, today_iso),
        )
    await callback.answer()
