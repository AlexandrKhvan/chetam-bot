from aiogram.fsm.state import State, StatesGroup


class AddTaskStates(StatesGroup):
    waiting_title = State()


class AddScheduleEventStates(StatesGroup):
    waiting_input = State()


class ScheduleImportStates(StatesGroup):
    confirming = State()


class SettingsStates(StatesGroup):
    waiting_evening_time = State()
    waiting_morning_time = State()
    waiting_timezone = State()
