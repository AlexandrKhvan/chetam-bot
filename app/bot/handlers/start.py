from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.handlers.common import safe_edit
from app.bot.keyboards import (
    main_menu_kb,
    onboarding_group_kb,
    onboarding_tz_kb,
    webapp_launch_kb,
)
from app.config import Settings
from app.db.database import Database
from app.db.models import UserProfile
from app.services.schedule_service import ScheduleService
from app.services.time_utils import user_today_iso

router = Router(name="start")

WELCOME_TEXT = """👋 <b>Привет! Я CheTam («Чё там на завтра?») — твой личный планировщик, инбокс и учебный трекер.</b>

✨ <b>Что я умею:</b>
🧠 <b>Разбор «кучи мыслей» + 🎙 Голосовые + ↪️ Forward</b> — пиши сплошным текстом, диктуй голосовым или пересылай сообщения от старосты. Я разобью на задачи, вытащу даты, время, <code>#теги</code>, повторы (<code>каждый день</code>, <code>пн ср пт</code>) и дедлайны.
⏳ <b>Дедлайны с авто-срочностью</b> — пиши <code>сдать лабу до 30.11</code> или <code>отчёт к пятнице</code>. За ≤ 3 дня до срока приоритет сам поднимается до 🔴!
📥 <b>Инбокс + 🗂 Общий пул задач</b> — свежие мысли падают в Инбокс, а дела «когда-нибудь» хранятся в Пуле с фильтром по <code>#тегам</code> и кнопкой <b>🗂</b> прямо в задачах на «Сегодня».
🎓 <b>Универсальное расписание</b> — понимает <b>.docx, .ics, .xlsx, .csv, .pdf, фото и текст</b>, вытаскивает Zoom ID/коды и умеет делиться расписанием с группой.
🌙 <b>Вечерний ритуал</b> — итоги дня, свободные окна завтра + забор задач из Инбокса и Пула.
🔔 <b>Напоминания + Snooze</b> — <code>/remind через 30 мин ...</code>, кнопка 🔔 на задачах, уведомления за 15 мин до пар и по задачам со временем.
🧭 <b>Воскресное AI-ревью</b> (/review) + 📊 <b>История и стрик 🔥</b> + 📱 <b>Telegram Mini App</b>.

<b>Команды:</b>
• /today · /tomorrow · /deadlines
• /inbox · /pool · /plan
• /remind · /reminders · /schedule
• /history · /review · /settings · /help"""


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    user_profile: UserProfile,
    settings: Settings,
) -> None:
    await state.clear()
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_kb())

    if not user_profile.onboarded:
        await message.answer(
            "👋 <b>Быстрая настройка (Шаг 1/2)</b>\nВыбери свой часовой пояс, чтобы напоминания приходили точно вовремя:",
            reply_markup=onboarding_tz_kb(),
        )
    elif settings.webapp_url:
        await message.answer(
            "✨ <b>CheTam Mini App</b> — план дня, подзадачи, пул с тегами, напоминания и графики прямо внутри Telegram:",
            reply_markup=webapp_launch_kb(settings.webapp_url),
        )


@router.callback_query(F.data.startswith("onb:tz:"))
async def cb_onboarding_tz(
    callback: CallbackQuery,
    db: Database,
    schedule_service: ScheduleService,
    user_profile: UserProfile,
) -> None:
    tz_name = callback.data.split(":", 2)[2]
    await db.update_user_settings(user_profile.user_id, timezone_name=tz_name)
    today_iso = user_today_iso(tz_name)
    shared = await schedule_service.list_shared_groups(today_iso)
    if callback.message:
        await safe_edit(
            callback.message,
            f"✅ Часовой пояс: <code>{escape(tz_name)}</code>\n\n"
            "🎓 <b>Шаг 2/2: Учебная группа</b>\nВыбери группу (если для неё уже загружено общее расписание — подтяну его сразу!):",
            onboarding_group_kb(shared),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("onb:grp:"))
async def cb_onboarding_group(
    callback: CallbackQuery,
    db: Database,
    schedule_service: ScheduleService,
    user_profile: UserProfile,
    settings: Settings,
) -> None:
    grp = callback.data.split(":", 2)[2]
    await db.update_user_settings(user_profile.user_id, study_group=grp, onboarded=True)
    today_iso = user_today_iso(user_profile.timezone)
    synced = await schedule_service.sync_from_shared_group(
        user_profile.user_id, grp, from_date_iso=today_iso
    )
    sync_note = (
        f"\n🎓 Автоматически подтянул <b>{synced}</b> занятий из общего расписания группы <b>{escape(grp)}</b>!"
        if synced
        else ""
    )
    if callback.message:
        kb = webapp_launch_kb(settings.webapp_url) if settings.webapp_url else None
        await safe_edit(
            callback.message,
            f"🎉 <b>Готово!</b> Группа <b>{escape(grp)}</b> сохранена.{sync_note}\n\n"
            "Можешь прямо сейчас закинуть задачи текстом, голосовым или открыть Mini App:",
            kb,
        )
    await callback.answer("Настройка завершена ✅")


@router.callback_query(F.data == "onb:skip")
async def cb_onboarding_skip(
    callback: CallbackQuery,
    db: Database,
    user_profile: UserProfile,
    settings: Settings,
) -> None:
    await db.update_user_settings(user_profile.user_id, onboarded=True)
    if callback.message:
        kb = webapp_launch_kb(settings.webapp_url) if settings.webapp_url else None
        await safe_edit(
            callback.message,
            "👌 Готово! Всё всегда можно поменять в /settings.",
            kb,
        )
    await callback.answer()


@router.message(Command("help"))
async def cmd_help(message: Message, settings: Settings) -> None:
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_kb())
    if settings.webapp_url:
        await message.answer(
            "📱 Открыть интерактивное приложение:",
            reply_markup=webapp_launch_kb(settings.webapp_url),
        )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    await state.clear()
    if current:
        await message.answer("👌 Текущее действие отменено.", reply_markup=main_menu_kb())
    else:
        await message.answer("Сейчас нет активного ввода.", reply_markup=main_menu_kb())
