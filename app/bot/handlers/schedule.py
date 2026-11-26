from __future__ import annotations

import io
import logging
from dataclasses import asdict
from datetime import timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.formatters import render_parsed_preview, render_week_schedule
from app.bot.handlers.common import safe_edit
from app.bot.keyboards import BTN_SCHEDULE, schedule_import_confirm_kb, schedule_week_kb
from app.bot.states import AddScheduleEventStates, ScheduleImportStates
from app.db.database import Database
from app.db.models import ParsedScheduleItem, UserProfile
from app.services.parsers.docx_parser import (
    detect_date_in_text,
    extract_detected_groups,
    extract_time_range,
    filter_items_by_group,
)
from app.services.parsers.universal_parser import parse_plain_text_schedule, parse_schedule_file
from app.services.parsers.vision_parser import VisionScheduleParser
from app.services.schedule_service import ScheduleService
from app.services.time_utils import user_today, user_today_iso

logger = logging.getLogger(__name__)
router = Router(name="schedule")

SUPPORTED_EXTENSIONS = (".docx", ".ics", ".xlsx", ".csv", ".pdf", ".txt", ".png", ".jpg", ".jpeg", ".webp")


async def _render_week_view(
    schedule_service: ScheduleService, user: UserProfile, anchor_iso: str
):
    today_iso = user_today_iso(user.timezone)
    start_iso, end_iso, events = await schedule_service.list_week_events(user.user_id, anchor_iso)
    shared_groups = await schedule_service.list_shared_groups(start_iso)
    shared_for_user = (
        user.study_group
        if user.study_group and user.study_group.upper() in {g.upper() for g in shared_groups}
        else (shared_groups[0] if shared_groups and not events else "")
    )
    text = render_week_schedule(start_iso, end_iso, events, today_iso)
    kb = schedule_week_kb(anchor_iso, start_iso, end_iso, today_iso, shared_group=shared_for_user)
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


@router.callback_query(F.data.startswith("sch:sync:"))
async def cb_schedule_sync_shared(
    callback: CallbackQuery,
    schedule_service: ScheduleService,
    user_profile: UserProfile,
) -> None:
    grp = callback.data.split(":", 2)[2]
    today_iso = user_today_iso(user_profile.timezone)
    synced = await schedule_service.sync_from_shared_group(
        user_profile.user_id, grp, from_date_iso=today_iso
    )
    text, kb = await _render_week_view(schedule_service, user_profile, today_iso)
    if callback.message:
        await safe_edit(
            callback.message,
            f"🔄 Подтянуто занятий из расписания <b>{escape(grp)}</b>: <b>{synced}</b>\n\n{text}",
            kb,
        )
    await callback.answer(f"Синхронизировано: {synced} ✅")


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
            "✏️ <b>Добавление пары или расписания текстом</b>\n\n"
            "Можно одной строкой:\n"
            "<code>25.11 09:00-10:30 Матан | ауд. 305</code>\n"
            "<code>завтра 14:00 Лабораторная по физике</code>\n\n"
            "Или сразу несколько дней блоком:\n"
            "<code>Понедельник 23.11\n09:00-10:30 Матан | 305\n10:45-12:15 Алгоритмы\nВторник 24.11\n13:00-14:30 Физика</code>\n\n"
            "<i>/cancel — отмена</i>"
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

    # Support multi-line pasted schedules right away
    if "\n" in raw:
        items = parse_plain_text_schedule(raw, reference_date=today)
        if items:
            await state.set_state(ScheduleImportStates.confirming)
            await state.update_data(
                parsed_items=[asdict(i) for i in items],
                import_source="manual",
                source_label="вставленный текст",
                detected_groups=[],
                selected_group=user_profile.study_group,
            )
            await message.answer(
                render_parsed_preview(items, "вставленный текст"),
                reply_markup=schedule_import_confirm_kb([], user_profile.study_group),
            )
            return

    lowered = raw.lower()
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
    location = ""
    if "|" in raw_rest:
        main_part, location = [p.strip() for p in raw_rest.split("|", 1)]
    else:
        main_part = raw_rest

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

    filename = doc.file_name or "schedule"
    lower = filename.lower()
    if not lower.endswith(SUPPORTED_EXTENSIONS):
        await message.answer(
            "📄 Поддерживаются расписания в форматах:\n"
            "<b>.docx, .ics (календарь), .xlsx, .csv, .pdf, .txt</b> и <b>фото/скриншоты</b>."
        )
        return

    status_msg = await message.answer(f"⏳ Читаю расписание из <b>{escape(filename)}</b>…")
    buf = io.BytesIO()
    await bot.download(doc, destination=buf)
    raw_bytes = buf.getvalue()
    ref_date = user_today(user_profile.timezone)

    try:
        items, source_code, source_label = await parse_schedule_file(
            filename,
            raw_bytes,
            reference_date=ref_date,
            tz_name=user_profile.timezone,
            vision_parser=vision_parser,
        )
    except RuntimeError as exc:
        if "VISION_NOT_CONFIGURED" in str(exc):
            await safe_edit(
                status_msg,
                "📷 <b>Распознавание фото пока не подключено.</b>\n\n"
                "Добавь в <code>.env</code> провайдер (<code>VISION_PROVIDER=gemini</code> или <code>bedrock</code>).\n"
                "Файлы <b>.docx, .ics, .xlsx, .csv, .pdf, .txt</b> и текстовый ввод работают прямо сейчас без ключей!",
            )
            return
        raise
    except Exception:
        logger.exception("Failed to parse schedule file %s", filename)
        items, source_code, source_label = [], "manual", filename

    if not items:
        await safe_edit(
            status_msg,
            f"😕 Не получилось автоматически вытащить пары из <b>{escape(filename)}</b>.\n\n"
            "Попробуй:\n"
            "• Экспортировать расписание в <b>.ics</b>, <b>.xlsx</b> или <b>.docx</b>.\n"
            "• Вставить расписание текстом через <b>🎓 Расписание → ➕ Добавить / вставить</b>.\n"
            "• Или подключить AI-парсер в <code>.env</code> (Gemini / Bedrock) для сложных PDF и фото.",
        )
        return

    await _show_import_preview(status_msg, state, items, source_code, source_label, user_profile)


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
    if not vision_parser.is_enabled:
        await message.answer(
            "📷 <b>Распознавание фото расписания ещё не подключено.</b>\n\n"
            "Чтобы бот распознавал фото/скриншоты, добавь в <code>.env</code>:\n"
            "<code>VISION_PROVIDER=gemini</code> + <code>GEMINI_API_KEY=...</code>\n"
            "или <code>VISION_PROVIDER=bedrock</code> (из твоих AWS-кредитов).\n\n"
            "А файлы <b>.docx, .ics, .xlsx, .csv, .pdf</b> и вставка текстом работают уже сейчас!"
        )
        return

    status_msg = await message.answer("⏳ Распознаю расписание по фото…")
    buf = io.BytesIO()
    await bot.download(message.photo[-1].file_id, destination=buf)
    ref_date = user_today(user_profile.timezone)

    try:
        items = await vision_parser.parse_image(
            buf.getvalue(), mime_type="image/jpeg", reference_date=ref_date
        )
    except Exception:
        logger.exception("Vision schedule parsing failed")
        await safe_edit(
            status_msg,
            "⚠️ Ошибка при обращении к AI-парсеру. Проверь ключи/доступ и попробуй ещё раз.",
        )
        return

    if not items:
        await safe_edit(
            status_msg,
            "😕 Не нашёл занятий на этом изображении. Попробуй более чёткий скриншот или файл (.docx/.ics/.xlsx).",
        )
        return

    await _show_import_preview(status_msg, state, items, "photo", "фото · AI", user_profile)


async def _show_import_preview(
    status_msg: Message,
    state: FSMContext,
    items: list[ParsedScheduleItem],
    source_code: str,
    source_label: str,
    user_profile: UserProfile,
) -> None:
    groups = extract_detected_groups(items)
    selected_group = (
        user_profile.study_group
        if user_profile.study_group and user_profile.study_group.upper() in {g.upper() for g in groups}
        else (groups[0] if len(groups) == 1 else (user_profile.study_group if not groups else ""))
    )
    visible_items = filter_items_by_group(items, selected_group) if groups else items

    await state.set_state(ScheduleImportStates.confirming)
    await state.update_data(
        parsed_items=[asdict(i) for i in items],
        import_source=source_code,
        source_label=source_label,
        detected_groups=groups,
        selected_group=selected_group,
    )
    await safe_edit(
        status_msg,
        render_parsed_preview(visible_items, source_label, selected_group),
        schedule_import_confirm_kb(groups, selected_group),
    )


@router.callback_query(ScheduleImportStates.confirming, F.data.startswith("sch:grp:"))
async def cb_schedule_import_group(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    chosen = callback.data.split(":")[2]
    selected_group = "" if chosen == "ALL" else chosen
    data = await state.get_data()
    all_items = [ParsedScheduleItem(**entry) for entry in data.get("parsed_items", [])]
    groups = data.get("detected_groups", [])
    source_label = data.get("source_label", "файл")

    await state.update_data(selected_group=selected_group)
    visible_items = filter_items_by_group(all_items, selected_group)
    if callback.message:
        await safe_edit(
            callback.message,
            render_parsed_preview(visible_items, source_label, selected_group),
            schedule_import_confirm_kb(groups, selected_group),
        )
    await callback.answer(f"Фильтр: {selected_group or 'все группы'}")


@router.callback_query(ScheduleImportStates.confirming, F.data.startswith("sch:imp:"))
async def cb_schedule_import_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
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
    selected_group = data.get("selected_group", "")
    groups = data.get("detected_groups", [])
    all_items = [ParsedScheduleItem(**entry) for entry in raw_items]
    items = filter_items_by_group(all_items, selected_group) if groups else all_items
    replace_dates = action in {"replace", "share"}

    if selected_group:
        await db.update_user_settings(user_profile.user_id, study_group=selected_group)

    saved = await schedule_service.import_parsed_events(
        user_profile.user_id,
        items,
        source=source,
        replace_dates=replace_dates,
    )

    shared_note = ""
    if action == "share" and selected_group:
        await schedule_service.publish_shared_schedule(
            selected_group, items, uploaded_by=user_profile.user_id
        )
        shared_note = f"\n👥 Опубликовано для группы <b>{escape(selected_group)}</b>!"

    anchor_iso = items[0].event_date if items else user_today_iso(user_profile.timezone)
    text, kb = await _render_week_view(schedule_service, user_profile, anchor_iso)
    if callback.message:
        await safe_edit(
            callback.message,
            f"✅ Сохранено занятий: <b>{saved}</b>{shared_note}\n\n{text}",
            kb,
        )
    await callback.answer("Расписание сохранено ✅")
