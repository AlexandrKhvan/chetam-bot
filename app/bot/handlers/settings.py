from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.formatters import render_settings
from app.bot.handlers.common import safe_edit
from app.bot.keyboards import settings_kb
from app.bot.states import SettingsStates
from app.config import Settings
from app.db.database import Database
from app.db.models import UserProfile
from app.services.time_utils import validate_hhmm

router = Router(name="settings")


@router.message(Command("settings"))
async def cmd_settings(
    message: Message,
    state: FSMContext,
    user_profile: UserProfile,
    settings: Settings,
) -> None:
    await state.clear()
    await message.answer(
        render_settings(user_profile, settings.has_vision_configured),
        reply_markup=settings_kb(user_profile),
    )


@router.callback_query(F.data.startswith("set:tog:"))
async def cb_toggle_reminder(
    callback: CallbackQuery,
    db: Database,
    user_profile: UserProfile,
    settings: Settings,
) -> None:
    kind = callback.data.split(":")[2]
    if kind == "evening":
        updated = await db.update_user_settings(
            user_profile.user_id,
            evening_reminder_enabled=not user_profile.evening_reminder_enabled,
        )
    elif kind == "class":
        # Cycle class reminder lead time: 15 -> 30 -> 0 (off) -> 15
        next_lead = {15: 30, 30: 0, 0: 15}.get(user_profile.class_reminder_minutes, 15)
        updated = await db.update_user_settings(
            user_profile.user_id,
            class_reminder_minutes=next_lead,
        )
    else:
        updated = await db.update_user_settings(
            user_profile.user_id,
            morning_digest_enabled=not user_profile.morning_digest_enabled,
        )
    if updated and callback.message:
        await safe_edit(
            callback.message,
            render_settings(updated, settings.has_vision_configured),
            settings_kb(updated),
        )
    await callback.answer("Обновлено ✅")


@router.callback_query(F.data == "set:time:evening")
async def cb_ask_evening_time(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsStates.waiting_evening_time)
    if callback.message:
        await callback.message.answer(
            "🌙 Введи время для вечернего планирования в формате <code>HH:MM</code> (например, <code>21:30</code>).\n"
            "<i>/cancel — отмена</i>"
        )
    await callback.answer()


@router.callback_query(F.data == "set:time:morning")
async def cb_ask_morning_time(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsStates.waiting_morning_time)
    if callback.message:
        await callback.message.answer(
            "☀️ Введи время для утренней сводки в формате <code>HH:MM</code> (например, <code>08:00</code>).\n"
            "<i>/cancel — отмена</i>"
        )
    await callback.answer()


@router.callback_query(F.data == "set:tz")
async def cb_ask_timezone(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsStates.waiting_timezone)
    if callback.message:
        await callback.message.answer(
            "🌍 Введи часовой пояс в формате IANA, например:\n"
            "• <code>Asia/Yekaterinburg</code> (+05:00)\n"
            "• <code>Europe/Moscow</code> (+03:00)\n"
            "• <code>Asia/Novosibirsk</code> (+07:00)\n"
            "• <code>Australia/Sydney</code>\n\n"
            "<i>/cancel — отмена</i>"
        )
    await callback.answer()


@router.message(SettingsStates.waiting_evening_time, F.text)
async def handle_evening_time_input(
    message: Message,
    state: FSMContext,
    db: Database,
    user_profile: UserProfile,
    settings: Settings,
) -> None:
    hhmm = validate_hhmm(message.text or "")
    if not hhmm:
        await message.answer("⚠️ Неверный формат. Введи, например, <code>21:30</code>.")
        return
    updated = await db.update_user_settings(user_profile.user_id, evening_plan_time=hhmm)
    await state.clear()
    if updated:
        await message.answer(
            "✅ Время вечернего планирования обновлено!\n\n"
            + render_settings(updated, settings.has_vision_configured),
            reply_markup=settings_kb(updated),
        )


@router.message(SettingsStates.waiting_morning_time, F.text)
async def handle_morning_time_input(
    message: Message,
    state: FSMContext,
    db: Database,
    user_profile: UserProfile,
    settings: Settings,
) -> None:
    hhmm = validate_hhmm(message.text or "")
    if not hhmm:
        await message.answer("⚠️ Неверный формат. Введи, например, <code>08:00</code>.")
        return
    updated = await db.update_user_settings(user_profile.user_id, morning_digest_time=hhmm)
    await state.clear()
    if updated:
        await message.answer(
            "✅ Время утренней сводки обновлено!\n\n"
            + render_settings(updated, settings.has_vision_configured),
            reply_markup=settings_kb(updated),
        )


@router.message(SettingsStates.waiting_timezone, F.text)
async def handle_timezone_input(
    message: Message,
    state: FSMContext,
    db: Database,
    user_profile: UserProfile,
    settings: Settings,
) -> None:
    tz_raw = (message.text or "").strip()
    try:
        ZoneInfo(tz_raw)
    except ZoneInfoNotFoundError:
        await message.answer(
            "⚠️ Неизвестный часовой пояс. Пример: <code>Asia/Yekaterinburg</code> или <code>Europe/Moscow</code>."
        )
        return
    updated = await db.update_user_settings(user_profile.user_id, timezone_name=tz_raw)
    await state.clear()
    if updated:
        await message.answer(
            "✅ Часовой пояс обновлён!\n\n"
            + render_settings(updated, settings.has_vision_configured),
            reply_markup=settings_kb(updated),
        )
