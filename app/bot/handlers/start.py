from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.keyboards import main_menu_kb, webapp_launch_kb
from app.config import Settings
from app.db.models import UserProfile

router = Router(name="start")

WELCOME_TEXT = """👋 <b>Привет! Я CheTam («Чё там на завтра?») — твой личный планировщик, инбокс и учебный трекер.</b>

✨ <b>Что я умею:</b>
🧠 <b>Разбор «кучи мыслей»</b> — просто пиши в чат сплошным текстом (<i>«надо сделать лабу, потом купить кофе, завтра в 18:00 зал и срочно сдать отчёт»</i>). Я сам разобью на отдельные задачи, вытащу дату, время и срочность 🔴.
📥 <b>Инбокс + 🗂 Общий пул задач</b> — свежие мысли падают в Инбокс, а дела «когда-нибудь / на потом» удобно хранить в Пуле и спокойно забирать в план вечером.
🎓 <b>Расписание учёбы из .docx и фото</b> — скидывай файл на неделю прямо в чат. Понимаю таблицы и фильтрую пары по твоей группе (например, <code>ВМ-21</code> / <code>ВМ-22</code>).
🌙 <b>Вечерний ритуал планирования</b> — за 1 минуту переносишь незакрытое с сегодня, смотришь завтрашние пары и добираешь задачи из Инбокса и Пула.
📅 <b>Живой план дня с галочками</b> — пары + задачи + прогресс-бар в одном сообщении, без спама.
🔔 <b>Умные напоминания + Snooze</b> — пиши <code>/remind через 30 мин выключить плиту</code> или <code>/remind каждый день в 22:00 витамины</code>, ставь 🔔 на любую задачу, плюс авто-напоминания за 15 мин до пар и по задачам со временем.
📊 <b>История и стрик 🔥</b> — хронология выполненных и перенесённых дел по дням, статистика за 7 и 30 дней.
📱 <b>Telegram Mini App</b> — полноценный интерактивный интерфейс прямо внутри чата (кнопка <b>CheTam</b> слева от поля ввода).

<b>Команды:</b>
• /today · /tomorrow — план на сегодня и завтра
• /inbox · /pool — входящие мысли и общий пул задач
• /plan — вечернее планирование
• /remind · /reminders — создать и посмотреть напоминания
• /schedule — расписание учёбы
• /history — статистика и история по дням
• /settings — часовой пояс, время напоминаний и уведомления о парах
• /cancel — отменить текущий ввод"""


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    user_profile: UserProfile,
    settings: Settings,
) -> None:
    await state.clear()
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_kb())
    if settings.webapp_url:
        await message.answer(
            "✨ <b>Доступен CheTam Mini App</b> — интерактивный план дня, пул задач, напоминания и графики прямо внутри Telegram:",
            reply_markup=webapp_launch_kb(settings.webapp_url),
        )


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
