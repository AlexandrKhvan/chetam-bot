from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo

from app.bot.handlers import register_handlers
from app.bot.middlewares import UserContextMiddleware
from app.bot.scheduler import ReminderScheduler
from app.config import load_settings
from app.db.database import Database
from app.services.history_service import HistoryService
from app.services.parsers.vision_parser import VisionScheduleParser
from app.services.reminder_service import ReminderService
from app.services.schedule_service import ScheduleService
from app.services.task_service import TaskService

# Strictly <= 512 chars (Telegram Bot API limit)
BOT_DESCRIPTION = (
    "CheTam («Чё там на завтра?») — личный планировщик дня, инбокс, пул задач и учебный трекер.\n\n"
    "🧠 Пиши всё в кучу — сам разобью на задачи с датами и срочностью\n"
    "📥 Инбокс + 🗂 Общий пул задач «на потом»\n"
    "🎓 Импорт расписания из .docx и фото с фильтром группы\n"
    "🌙 Вечерний ритуал сборки завтрашнего дня\n"
    "🔔 Напоминания, Snooze и уведомления за 15 мин до пар\n"
    "📊 История по дням, стрик 🔥 и встроенный Mini App"
)

# Strictly <= 120 chars (Telegram Bot API limit)
BOT_SHORT_DESCRIPTION = (
    "Планировщик дня, пул задач, разбор «кучи мыслей», расписание из .docx, напоминания и Mini App."
)


async def _configure_bot_profile(bot: Bot, webapp_url: str) -> None:
    commands = [
        BotCommand(command="today", description="📅 План на сегодня"),
        BotCommand(command="tomorrow", description="🌅 План на завтра"),
        BotCommand(command="inbox", description="📥 Входящие мысли"),
        BotCommand(command="pool", description="🗂 Общий пул задач"),
        BotCommand(command="plan", description="🌙 Вечернее планирование"),
        BotCommand(command="remind", description="🔔 Создать напоминание"),
        BotCommand(command="reminders", description="⏰ Активные напоминания"),
        BotCommand(command="schedule", description="🎓 Расписание учёбы"),
        BotCommand(command="history", description="📊 История и статистика"),
        BotCommand(command="settings", description="⚙️ Настройки и уведомления"),
        BotCommand(command="help", description="✨ Все возможности бота"),
    ]
    await bot.set_my_commands(commands)
    try:
        await bot.set_my_description(BOT_DESCRIPTION)
        await bot.set_my_short_description(BOT_SHORT_DESCRIPTION)
        if webapp_url.strip():
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="CheTam",
                    web_app=WebAppInfo(url=webapp_url.strip()),
                )
            )
    except Exception:
        logging.getLogger("chetam-bot").warning("Could not update bot profile metadata", exc_info=True)


async def run_bot() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logger = logging.getLogger("chetam-bot")

    if not settings.bot_token or settings.bot_token == "your_telegram_bot_token_here":
        logger.error("BOT_TOKEN is not configured. Copy .env.example to .env and set BOT_TOKEN.")
        sys.exit(1)

    db = Database(settings.database_path)
    await db.init()

    task_service = TaskService(db)
    schedule_service = ScheduleService(db)
    history_service = HistoryService(db)
    reminder_service = ReminderService(db)
    vision_parser = VisionScheduleParser(settings)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    dp["db"] = db
    dp["settings"] = settings
    dp["task_service"] = task_service
    dp["schedule_service"] = schedule_service
    dp["history_service"] = history_service
    dp["reminder_service"] = reminder_service
    dp["vision_parser"] = vision_parser

    middleware = UserContextMiddleware(db=db, settings=settings)
    dp.message.middleware(middleware)
    dp.callback_query.middleware(middleware)

    register_handlers(dp)

    scheduler = ReminderScheduler(
        bot=bot,
        db=db,
        task_service=task_service,
        schedule_service=schedule_service,
        reminder_service=reminder_service,
    )

    await _configure_bot_profile(bot, settings.webapp_url)
    scheduler.start()
    logger.info("CheTam bot started. Database: %s", settings.database_path)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.stop()
        await bot.session.close()


def main() -> None:
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
