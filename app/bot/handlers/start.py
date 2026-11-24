from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.keyboards import main_menu_kb
from app.db.models import UserProfile

router = Router(name="start")

WELCOME_TEXT = """👋 <b>Привет! Я твой личный планировщик и todo-бот.</b>

Как со мной удобно работать:
1️⃣ <b>Закидывай мысли прямо в чат</b> — любое текстовое сообщение (даже список из нескольких строк) мгновенно попадёт в <b>📥 Инбокс</b>.
2️⃣ <b>Скидывай расписание учёбы</b> — просто пришли <b>.docx файл</b> или <b>фото</b> на неделю, я распознаю пары и покажу предпросмотр.
3️⃣ <b>Каждый вечер</b> открывай <b>🌙 Вечерний план</b> — за 1 минуту переносишь недоделанное и выбираешь задачи на завтра с учётом пар.
4️⃣ <b>Днём</b> отмечай дела галочками прямо в карточке <b>📅 Сегодня</b>, а прогресс и стрик смотри в <b>📊 Истории</b>.

Команды:
• /today — план на сегодня
• /tomorrow — план на завтра
• /inbox — входящие мысли
• /plan — вечернее планирование
• /schedule — расписание учёбы
• /history — история и статистика
• /settings — время напоминаний и часовой пояс
• /cancel — отменить текущий ввод"""


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, user_profile: UserProfile) -> None:
    await state.clear()
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_kb())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_kb())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    await state.clear()
    if current:
        await message.answer("👌 Текущее действие отменено.", reply_markup=main_menu_kb())
    else:
        await message.answer("Сейчас нет активного ввода.", reply_markup=main_menu_kb())
