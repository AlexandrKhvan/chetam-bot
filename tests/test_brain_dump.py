from __future__ import annotations

from datetime import date

from app.services.brain_dump import split_brain_dump

TODAY = date(2026, 11, 25)


def test_run_on_russian_brain_dump():
    msg = (
        "надо сделать лабу по осям, потом купить кофе и молоко, "
        "еще повторить дифуры к завтрашнему семинару и не забыть отправить отчет срочно"
    )
    drafts = split_brain_dump(msg, today=TODAY)
    assert len(drafts) == 4
    assert drafts[0].title == "Сделать лабу по осям"
    assert drafts[1].title == "Купить кофе и молоко"
    assert drafts[2].title == "Повторить дифуры к завтрашнему семинару"
    assert drafts[2].planned_date == "2026-11-26"
    assert drafts[3].title == "Отправить отчет"
    assert drafts[3].priority == 1


def test_inline_numbered_and_time_extraction():
    msg = "1) решить 3 задачи по терверу 2) написать препу; завтра в 18:00 сходить в зал, и еще оплатить интернет"
    drafts = split_brain_dump(msg, today=TODAY)
    assert len(drafts) == 4
    assert drafts[0].title == "Решить 3 задачи по терверу"
    assert drafts[1].title == "Написать препу"
    assert drafts[2].title == "Сходить в зал"
    assert drafts[2].planned_date == "2026-11-26"
    assert drafts[2].planned_time == "18:00"
    assert drafts[3].title == "Оплатить интернет"


def test_section_headers_propagate_dates():
    msg = "Сегодня: дочитать главу, сделать дз по англу\nЗавтра:\n- забрать посылку в 15:30"
    drafts = split_brain_dump(msg, today=TODAY)
    assert len(drafts) == 3
    assert drafts[0].planned_date == "2026-11-25"
    assert drafts[1].planned_date == "2026-11-25"
    assert drafts[2].planned_date == "2026-11-26"
    assert drafts[2].planned_time == "15:30"


def test_single_task_does_not_oversplit():
    drafts1 = split_brain_dump("Купить хлеб и молоко в магазине", today=TODAY)
    assert len(drafts1) == 1
    assert drafts1[0].title == "Купить хлеб и молоко в магазине"

    drafts2 = split_brain_dump("Повторить лекции по матану, физике и дискретке", today=TODAY)
    assert len(drafts2) == 1
