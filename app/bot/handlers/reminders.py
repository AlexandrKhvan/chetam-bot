from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.formatters import render_reminders
from app.bot.handlers.common import safe_edit
from app.bot.keyboards import BTN_REMINDERS, reminders_list_kb, task_remind_presets_kb
from app.bot.states import AddReminderStates
from app.db.models import UserProfile
from app.services.reminder_service import (
    ReminderService,
    format_reminder_time_local,
    parse_reminder_input,
)
from app.services.task_service import TaskService
from app.services.time_utils import get_zoneinfo, user_now

router = Router(name="reminders")

REMIND_HINT = (
    "🔔 <b>Создание напоминания</b>\n\n"
    "Напиши в свободной форме, например:\n"
    "• <code>через 30 мин выключить плиту</code>\n"
    "• <code>в 19:30 позвонить маме</code>\n"
    "• <code>завтра в 10:00 сдать отчёт</code>\n"
    "• <code>28.11 в 14:00 зачёт</code>\n"
    "• <code>каждый день в 22:00 пить витамины</code>\n\n"
    "<i>/cancel — отмена</i>"
)


async def _render_reminders_view(reminder_service: ReminderService, user: UserProfile):
    items = await reminder_service.list_active(user.user_id)
    return render_reminders(items, user.timezone), reminders_list_kb(items)


@router.message(Command("reminders"))
@router.message(F.text == BTN_REMINDERS)
async def cmd_reminders(
    message: Message,
    state: FSMContext,
    reminder_service: ReminderService,
    user_profile: UserProfile,
) -> None:
    await state.clear()
    text, kb = await _render_reminders_view(reminder_service, user_profile)
    await message.answer(text, reply_markup=kb)


@router.message(Command("remind"))
async def cmd_remind_quick(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    reminder_service: ReminderService,
    user_profile: UserProfile,
) -> None:
    await state.clear()
    arg = (command.args or "").strip()
    if not arg:
        await state.set_state(AddReminderStates.waiting_input)
        await message.answer(REMIND_HINT)
        return

    parsed = parse_reminder_input(arg, user_profile.timezone)
    if not parsed:
        await message.answer("⚠️ Не понял время напоминания.\n\n" + REMIND_HINT)
        return

    rem = await reminder_service.create_reminder(
        user_profile.user_id,
        parsed.text,
        parsed.remind_at_utc,
        repeat_rule=parsed.repeat_rule,
    )
    when = format_reminder_time_local(rem.remind_at_utc, user_profile.timezone)
    rep = " 🔁 (ежедневно)" if rem.repeat_rule == "daily" else ""
    await message.answer(
        f"✅ Напомню <b>{escape(when)}</b>{rep}:\n• {escape(rem.text)}"
    )


@router.callback_query(F.data == "rem:new")
async def cb_reminder_new(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddReminderStates.waiting_input)
    if callback.message:
        await callback.message.answer(REMIND_HINT)
    await callback.answer()


@router.message(AddReminderStates.waiting_input, F.text)
async def handle_reminder_input(
    message: Message,
    state: FSMContext,
    reminder_service: ReminderService,
    user_profile: UserProfile,
) -> None:
    raw = (message.text or "").strip()
    if raw.startswith("/"):
        return
    parsed = parse_reminder_input(raw, user_profile.timezone)
    if not parsed:
        await message.answer("⚠️ Не смог распознать время. Пример: <code>через 45 мин проверить духовку</code>")
        return
    rem = await reminder_service.create_reminder(
        user_profile.user_id,
        parsed.text,
        parsed.remind_at_utc,
        repeat_rule=parsed.repeat_rule,
    )
    await state.clear()
    when = format_reminder_time_local(rem.remind_at_utc, user_profile.timezone)
    text, kb = await _render_reminders_view(reminder_service, user_profile)
    await message.answer(
        f"✅ Напоминание создано на <b>{escape(when)}</b>!\n\n{text}",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("rem:ask:"))
async def cb_task_remind_ask(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    task_id = int(callback.data.split(":")[2])
    task = await task_service.get_task(user_profile.user_id, task_id)
    if not task:
        await callback.answer("Задача не найдена", show_alert=True)
        return
    if callback.message:
        await callback.message.answer(
            f"🔔 <b>Когда напомнить о задаче?</b>\n• {escape(task.title)}",
            reply_markup=task_remind_presets_kb(task.id),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("rem:set:"))
async def cb_task_remind_preset(
    callback: CallbackQuery,
    task_service: TaskService,
    reminder_service: ReminderService,
    user_profile: UserProfile,
) -> None:
    _, _, task_id_s, preset = callback.data.split(":")
    task = await task_service.get_task(user_profile.user_id, int(task_id_s))
    if not task:
        await callback.answer("Задача не найдена", show_alert=True)
        return

    now_local = user_now(user_profile.timezone)
    if preset == "15m":
        target_local = now_local + timedelta(minutes=15)
    elif preset == "1h":
        target_local = now_local + timedelta(hours=1)
    elif preset == "eve":
        target_local = now_local.replace(hour=20, minute=0, second=0, microsecond=0)
        if target_local <= now_local:
            target_local += timedelta(days=1)
    else:  # tom 09:00
        tomorrow = now_local.date() + timedelta(days=1)
        target_local = datetime(
            tomorrow.year, tomorrow.month, tomorrow.day, 9, 0, tzinfo=get_zoneinfo(user_profile.timezone)
        )

    rem = await reminder_service.create_reminder(
        user_profile.user_id,
        task.title,
        target_local.astimezone(timezone.utc),
        task_id=task.id,
    )
    when = format_reminder_time_local(rem.remind_at_utc, user_profile.timezone)
    if callback.message:
        await safe_edit(
            callback.message,
            f"🔔 Напомню <b>{escape(when)}</b>:\n• {escape(task.title)}",
        )
    await callback.answer("Напоминание установлено 🔔")


@router.callback_query(F.data.startswith("rem:custom:"))
async def cb_task_remind_custom(
    callback: CallbackQuery,
    state: FSMContext,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    task_id = int(callback.data.split(":")[2])
    task = await task_service.get_task(user_profile.user_id, task_id)
    if not task:
        await callback.answer("Задача не найдена", show_alert=True)
        return
    await state.set_state(AddReminderStates.waiting_task_time)
    await state.update_data(remind_task_id=task.id, remind_task_title=task.title)
    if callback.message:
        await safe_edit(
            callback.message,
            f"🕒 Напиши, когда напомнить о <b>{escape(task.title)}</b>:\n"
            "Например: <code>через 40 мин</code>, <code>в 18:30</code>, <code>завтра в 11:00</code>.\n"
            "<i>/cancel — отмена</i>",
        )
    await callback.answer()


@router.message(AddReminderStates.waiting_task_time, F.text)
async def handle_task_remind_custom_time(
    message: Message,
    state: FSMContext,
    reminder_service: ReminderService,
    user_profile: UserProfile,
) -> None:
    raw = (message.text or "").strip()
    if raw.startswith("/"):
        return
    data = await state.get_data()
    task_id = data.get("remind_task_id")
    task_title = data.get("remind_task_title") or "Задача"

    parsed = parse_reminder_input(f"{raw} {task_title}", user_profile.timezone)
    if not parsed:
        await message.answer("⚠️ Не понял время. Пример: <code>через 20 мин</code> или <code>завтра в 10:00</code>.")
        return

    rem = await reminder_service.create_reminder(
        user_profile.user_id,
        task_title,
        parsed.remind_at_utc,
        task_id=task_id,
        repeat_rule=parsed.repeat_rule,
    )
    await state.clear()
    when = format_reminder_time_local(rem.remind_at_utc, user_profile.timezone)
    await message.answer(f"🔔 Напомню <b>{escape(when)}</b>:\n• {escape(task_title)}")


@router.callback_query(F.data == "rem:cancel")
async def cb_reminder_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message:
        await safe_edit(callback.message, "👌 Отменено.")
    await callback.answer()


@router.callback_query(F.data.startswith("rem:del:"))
async def cb_reminder_delete(
    callback: CallbackQuery,
    reminder_service: ReminderService,
    user_profile: UserProfile,
) -> None:
    rem_id = int(callback.data.split(":")[2])
    await reminder_service.delete_reminder(user_profile.user_id, rem_id)
    text, kb = await _render_reminders_view(reminder_service, user_profile)
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer("Удалено 🗑")


@router.callback_query(F.data.startswith("rem:snz:"))
async def cb_reminder_snooze(
    callback: CallbackQuery,
    reminder_service: ReminderService,
    user_profile: UserProfile,
) -> None:
    _, _, rem_id_s, mode = callback.data.split(":")
    rem_id = int(rem_id_s)
    if mode == "tom":
        now_local = user_now(user_profile.timezone)
        tom = now_local.date() + timedelta(days=1)
        target_local = datetime(
            tom.year, tom.month, tom.day, 9, 0, tzinfo=get_zoneinfo(user_profile.timezone)
        )
        updated = await reminder_service.snooze(
            user_profile.user_id, rem_id, target_utc=target_local.astimezone(timezone.utc)
        )
    else:
        updated = await reminder_service.snooze(
            user_profile.user_id, rem_id, minutes=int(mode)
        )

    if not updated:
        await callback.answer("Напоминание не найдено", show_alert=True)
        return
    when = format_reminder_time_local(updated.remind_at_utc, user_profile.timezone)
    if callback.message:
        await safe_edit(
            callback.message,
            f"💤 Отложено на <b>{escape(when)}</b>:\n• {escape(updated.text)}",
        )
    await callback.answer("Отложено 💤")


@router.callback_query(F.data.startswith("rem:done:"))
async def cb_reminder_done_task(
    callback: CallbackQuery,
    task_service: TaskService,
    user_profile: UserProfile,
) -> None:
    _, _, _rem_id_s, task_id_s = callback.data.split(":")
    task = await task_service.toggle_done(user_profile.user_id, int(task_id_s))
    if callback.message:
        title = task.title if task else "Задача"
        await safe_edit(callback.message, f"✅ Выполнено:\n• <s>{escape(title)}</s>")
    await callback.answer("Отмечено сделанным ✅")


@router.callback_query(F.data.startswith("rem:ack:"))
async def cb_reminder_ack(callback: CallbackQuery) -> None:
    if callback.message:
        await safe_edit(callback.message, "✅ Принято!")
    await callback.answer("Готово")
