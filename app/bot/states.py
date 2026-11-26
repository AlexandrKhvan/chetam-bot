from aiogram.fsm.state import State, StatesGroup


class AddTaskStates(StatesGroup):
    waiting_title = State()


class AddPoolTaskStates(StatesGroup):
    waiting_title = State()


class AddReminderStates(StatesGroup):
    waiting_input = State()
    waiting_task_time = State()


class AddScheduleEventStates(StatesGroup):
    waiting_input = State()


class ScheduleImportStates(StatesGroup):
    confirming = State()


class SettingsStates(StatesGroup):
    waiting_evening_time = State()
    waiting_morning_time = State()
    waiting_timezone = State()
