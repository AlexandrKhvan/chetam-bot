from __future__ import annotations

import io
from datetime import date

from docx import Document

from app.services.parsers.docx_parser import parse_docx_schedule


def _doc_to_bytes(doc: Document) -> bytes:
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_parse_row_oriented_table_with_merged_days():
    doc = Document()
    table = doc.add_table(rows=4, cols=4)
    rows_data = [
        ("День", "Время", "Предмет", "Аудитория"),
        ("Понедельник 23.11", "09:00-10:30", "Математический анализ", "ауд. 305"),
        ("Понедельник 23.11", "10:45-12:15", "Программирование", "412"),
        ("Вторник 24.11", "13:00-14:30", "Физика", "201"),
    ]
    for r_idx, row_vals in enumerate(rows_data):
        for c_idx, val in enumerate(row_vals):
            table.rows[r_idx].cells[c_idx].text = val

    # Simulate merged day cell for Monday
    table.cell(1, 0).merge(table.cell(2, 0))
    table.cell(1, 0).text = "Понедельник 23.11"

    items = parse_docx_schedule(_doc_to_bytes(doc), reference_date=date(2026, 11, 23))
    assert len(items) == 3
    assert items[0].event_date == "2026-11-23"
    assert items[0].start_time == "09:00"
    assert items[0].end_time == "10:30"
    assert items[0].title == "Математический анализ"
    assert items[0].location == "ауд. 305"

    assert items[1].event_date == "2026-11-23"
    assert items[1].start_time == "10:45"
    assert items[1].title == "Программирование"

    assert items[2].event_date == "2026-11-24"
    assert items[2].title == "Физика"


def test_parse_matrix_grid_table():
    doc = Document()
    table = doc.add_table(rows=3, cols=4)
    grid = [
        ["Время", "Пн 23.11", "Вт 24.11", "Ср 25.11"],
        ["09:00-10:30", "Линейная алгебра (ауд. 104)", "—", "Английский язык"],
        ["10:45-12:15", "", "Базы данных ауд. 502", "Физкультура"],
    ]
    for r_idx, row_vals in enumerate(grid):
        for c_idx, val in enumerate(row_vals):
            table.rows[r_idx].cells[c_idx].text = val

    items = parse_docx_schedule(_doc_to_bytes(doc), reference_date=date(2026, 11, 23))
    assert len(items) == 4
    by_key = {(i.event_date, i.start_time): i for i in items}
    assert ("2026-11-23", "09:00") in by_key
    assert by_key[("2026-11-23", "09:00")].location == "ауд. 104"
    assert ("2026-11-24", "10:45") in by_key
    assert ("2026-11-25", "09:00") in by_key
    assert ("2026-11-25", "10:45") in by_key


def test_parse_paragraph_schedule():
    doc = Document()
    doc.add_paragraph("Среда, 25 ноября")
    doc.add_paragraph("08:30-10:00 Операционные системы ауд. 210")
    doc.add_paragraph("10:15-11:45 Сети и телекоммуникации")

    items = parse_docx_schedule(_doc_to_bytes(doc), reference_date=date(2026, 11, 23))
    assert len(items) == 2
    assert items[0].event_date == "2026-11-25"
    assert items[0].start_time == "08:30"
    assert items[0].end_time == "10:00"
    assert items[0].location == "ауд. 210"
