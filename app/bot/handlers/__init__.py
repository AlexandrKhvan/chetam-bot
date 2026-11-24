from aiogram import Dispatcher

from app.bot.handlers import (
    common,
    history,
    inbox,
    planning,
    schedule,
    settings,
    start,
    tasks,
)


def register_handlers(dp: Dispatcher) -> None:
    dp.include_router(common.router)
    dp.include_router(start.router)
    dp.include_router(settings.router)
    dp.include_router(schedule.router)
    dp.include_router(planning.router)
    dp.include_router(inbox.router)
    dp.include_router(history.router)
    dp.include_router(tasks.router)
    # Must be registered last so plain text captures thoughts without shadowing commands/FSM
    dp.include_router(tasks.quick_capture_router)
