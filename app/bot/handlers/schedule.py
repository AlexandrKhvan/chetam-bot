from __future__ import annotations

import io
import logging
from dataclasses import asdict
from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.formatters import render_parsed_preview, render_week_schedule
from app.bot.handlers.common import safe_edit
from app.bot.keyboards import BTN_SCHEDULE, schedule_import_confirm_kb, schedule_week_kb
from app.bot.states import AddScheduleEventStates, ScheduleImportStates
from app.db.models import ParsedScheduleItem, UserProfile
from app.services.parsers.docx_parser import (
    detect_date_in_text,
    extract_docx_text,
    extract_time_range,
    parse_docx_schedule,
)
from app.services.parsers.vision_parser import VisionScheduleParser
from app.services.schedule_service import ScheduleService
from app.services.time_utils import user_today, user_today_iso

logger = logging.getLogger(__name__)
router = Router(name="schedule")


async def _render_week_view(
    schedule_service: ScheduleService, user: UserProfile, anchor_iso: str
):
    today_iso = user_today_iso(user.timezone)
    start_iso, end_iso, events = await schedule_service.list_week_events(user.user_id, anchor_iso)
    text = render_week_schedule(start_iso, end_iso, events, today_iso)
    kb = schedule_week_kb(anchor_iso, start_iso, end_iso, today_iso)
    return text, kb


@router.message(Command("schedule"))
@router.message(F.text == BTN_SCHEDULE)
async def cmd_schedule(
    message: Message,
    state: FSMContext,
    schedule_service: ScheduleService,
    user_profile: UserProfile,
) -> None:
    await state.clear()
    today_iso = user_today_iso(user_profile.timezone)
    text, kb = await _render_week_view(schedule_service, user_profile, today_iso)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("sch:wk:"))
async def cb_schedule_week(
    callback: CallbackQuery,
    schedule_service: ScheduleService,
    user_profile: UserProfile,
) -> None:
    anchor_iso = callback.data.split(":")[2]
    text, kb = await _render_week_view(schedule_service, user_profile, anchor_iso)
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer()


@router.callback_query(F.data.startswith("sch:clr:"))
async def cb_schedule_clear_week(
    callback: CallbackQuery,
    schedule_service: ScheduleService,
    user_profile: UserProfile,
) -> None:
    _, _, start_iso, end_iso = callback.data.split(":")
    removed = await schedule_service.clear_week(user_profile.user_id, start_iso, end_iso)
    text, kb = await _render_week_view(schedule_service, user_profile, start_iso)
    if callback.message:
        await safe_edit(callback.message, text, kb)
    await callback.answer(f"Удалено занятий: {removed} 🗑")


@router.callback_query(F.data == "sch:add")
async def cb_schedule_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddScheduleEventStates.waiting_input)
    if callback.message:
        await callback.message.answer(
            "✏️ <b>Добавление пары / события</b>\n\n"
            "Напиши в формате:\n"
            "<code>25.11 09:00-10:30 Матан | ауд. 305</code>\n"
            "или:\n"
            "<code>завтра 14:00 Лабораторная по физике</code>\n"
            "<code>пн 10:45-12:15 Алгоритмы | 412</code>\n\n"
            "<i>Для отмены нажми /cancel</i>"
        )
    await callback.answer()


@router.message(AddScheduleEventStates.waiting_input, F.text)
async def handle_manual_schedule_input(
    message: Message,
    state: FSMContext,
    schedule_service: ScheduleService,
    user_profile: UserProfile,
) -> None:
    raw = (message.text or "").strip()
    if raw.startswith("/"):
        return

    today = user_today(user_profile.timezone)
    lowered = raw.lower()
    event_date = None
    if lowered.startswith("сегодня"):
        event_date = today
        raw_rest = raw[len("сегодня") :].strip()
    elif lowered.startswith("завтра"):
        event_date = today + timedelta(days=1)
        raw_rest = raw[len("завтра") :].strip()
    else:
        event_date = detect_date_in_text(raw, today)
        raw_rest = raw

    time_info = extract_time_range(raw_rest)
    if not event_date or not time_info:
        await message.answer(
            "⚠️ Не смог понять дату или время. Пример:\n"
            "<code>25.11 09:00-10:30 Матан | ауд. 305</code>\n"
            "Или /cancel для отмены."
        )
        return

    start_t, end_t = time_info
    # Strip leading date/time tokens to get clean title & optional location after "|"
    location = ""
    if "|" in raw_rest:
        main_part, location = [p.strip() for p in raw_rest.split("|", 1)]
    else:
        main_part = raw_rest

    # Find end of time string in main_part and take what follows
    idx_time = main_part.find(end_t) if end_t and end_t in main_part else main_part.find(start_t)
    if idx_time != -1:
        after_time = main_part[idx_time + (len(end_t) if end_t and end_t in main_part else len(start_t)) :]
        title = after_time.strip(" -–—:\t|")
    else:
        title = main_part.strip()

    if not title:
        await message.answer("⚠️ Не хватает названия занятия после времени. Попробуй ещё раз.")
        return

    await schedule_service.add_event(
        user_profile.user_id,
        event_date.isoformat(),
        start_t,
        title,
        end_time=end_t,
        location=location,
        source="manual",
    )
    await state.clear()
    text, kb = await _render_week_view(schedule_service, user_profile, event_date.isoformat())
    await message.answer("✅ Пара добавлена!\n\n" + text, reply_markup=kb)


@router.message(F.document)
async def handle_document_upload(
    message: Message,
    bot: Bot,
    state: FSMContext,
    vision_parser: VisionScheduleParser,
    user_profile: UserProfile,
) -> None:
    doc = message.document
    if not doc:
        return

    filename = (doc.file_name or "").lower()
    if filename.endswith((".png", ".jpg", ".jpeg", ".webp")):
        await _process_image_file(
            message,
            bot,
            state,
            file_id=doc.file_id,
            mime_type=doc.mime_type or "image/jpeg",
            vision_parser=vision_parser,
            user_profile=user_profile,
        )
        return

    if not filename.endswith(".docx"):
        await message.answer(
            "📄 Для импорта расписания пришли <b>.docx файл</b> или <b>фото/скриншот</b>."
        )
        return

    status_msg = await message.answer("⏳ Читаю <b>.docx</b> расписание…")
    buf = io.BytesIO()
    await bot.download(doc, destination=buf)
    raw_bytes = buf.getvalue()

    ref_date = user_today(user_profile.timezone)
    try:
        items = parse_docx_schedule(raw_bytes, reference_date=ref_date)
    except Exception:
        logger.exception("Failed to parse docx schedule")
        items = []

    source_label = f"файл {doc.file_name}"
    if not items and vision_parser.is_enabled:
        try:
            plain_text = extract_docx_text(raw_bytes)
            if plain_text:
                items = await vision_parser.parse_text(plain_text, reference_date=ref_date)
                source_label = f"{doc.file_name} · AI"
        except Exception:
            logger.exception("AI fallback failed for docx")

    if not items:
        await safe_edit(
            status_msg,
            "😕 Не получилось автоматически распознать пары в этом <b>.docx</b>.\n\n"
            "Что можно сделать:\n"
            "• Пришли файл со стандартной таблицей (Дни / Время / Предмет).\n"
            "• Или включи AI-парсер в <code>.env</code> (<code>VISION_PROVIDER=gemini</code>), "
            "тогда бот поймёт любой нестандартный формат и фото.",
        )
        return

    await state.set_state(ScheduleImportStates.confirming)
    await state.update_data(
        parsed_items=[asdict(i) for i in items],
        import_source="docx",
    )
    await safe_edit(
        status_msg,
        render_parsed_preview(items, source_label),
        schedule_import_confirm_kb(),
    )


@router.message(F.photo)
async def handle_photo_upload(
    message: Message,
    bot: Bot,
    state: FSMContext,
    vision_parser: VisionScheduleParser,
    user_profile: UserProfile,
) -> None:
    if not message.photo:
        return
    largest = message.photo[-1]
    await _process_image_file(
        message,
        bot,
        state,
        file_id=largest.file_id,
        mime_type="image/jpeg",
        vision_parser=vision_parser,
        user_profile=user_profile,
    )


async def _process_image_file(
    message: Message,
    bot: Bot,
    state: FSMContext,
    *,
    file_id: str,
    mime_type: str,
    vision_parser: VisionScheduleParser,
    user_profile: UserProfile,
) -> None:
    if not vision_parser.is_enabled:
        await message.answer(
            "📷 <b>Распознавание фото расписания ещё не подключено.</b>\n\n"
            "Чтобы бот распознавал фото/скриншоты, добавь в <code>.env</code>:\n"
            "<code>VISION_PROVIDER=gemini</code>\n"
            "<code>GEMINI_API_KEY=...</code>\n\n"
            "А файлы <b>.docx</b> и ручной ввод работают прямо сейчас без API-ключей!"
        )
        return

    status_msg = await message.answer("⏳ Распознаю расписание по фото…")
    buf = io.BytesIO()
    await bot.download(file_id, destination=buf)
    ref_date = user_today(user_profile.timezone)

    try:
        items = await vision_parser.parse_image(
            buf.getvalue(), mime_type=mime_type, reference_date=ref_date
        )
    except Exception:
        logger.exception("Vision schedule parsing failed")
        await safe_edit(
            status_msg,
            "⚠️ Ошибка при обращении к AI-парсеру. Проверь API-ключ и попробуй ещё раз.",
        )
        return

    if not items:
        await safe_edit(
            status_msg,
            "😕 Не нашёл занятий на этом изображении. Попробуй более чёткий скриншот или .docx.",
        )
        return

    await state.set_state(ScheduleImportStates.confirming)
    await state.update_data(
        parsed_items=[asdict(i) for i in items],
        import_source="photo",
    )
    await safe_edit(
        status_msg,
        render_parsed_preview(items, "фото · AI"),
        schedule_import_confirm_kb(),
    )


@router.callback_query(ScheduleImportStates.confirming, F.data.startswith("sch:imp:"))
async def cb_schedule_import_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    schedule_service: ScheduleService,
    user_profile: UserProfile,
) -> None:
    action = callback.data.split(":")[2]
    data = await state.get_data()
    await state.clear()

    if action == "cancel":
        if callback.message:
            await safe_edit(callback.message, "❌ Импорт расписания отменён.")
        await callback.answer("Отменено")
        return

    raw_items = data.get("parsed_items", [])
    source = data.get("import_source", "docx")
    items = [ParsedScheduleItem(**entry) for entry in raw_items]
    replace_dates = action == "replace"

    saved = await schedule_service.import_parsed_events(
        user_profile.user_id,
        items,
        source=source,
        replace_dates=replace_dates,
    )
    anchor_iso = items[0].event_date if items else user_today_iso(user_profile.timezone)
    text, kb = await _render_week_view(schedule_service, user_profile, anchor_iso)
    if callback.message:
        await safe_edit(
            callback.message,
            f"✅ Сохранено занятий: <b>{saved}</b>\n\n{text}",
            kb,
        )
    await callback.answer("Расписание сохранено ✅")
