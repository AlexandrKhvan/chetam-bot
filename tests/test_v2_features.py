from __future__ import annotations

import gzip
import io
from datetime import date

import openpyxl
import pytest
from docx import Document
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.database import Database
from app.db.models import ParsedScheduleItem, ScheduleEvent
from app.services.backup_service import BackupService
from app.services.brain_dump import split_brain_dump
from app.services.history_service import HistoryService
from app.services.parsers.docx_parser import parse_docx_schedule
from app.services.parsers.universal_parser import (
    parse_csv_schedule,
    parse_ics_schedule,
    parse_plain_text_schedule,
    parse_xlsx_schedule,
)
from app.services.review_service import WeeklyReviewService
from app.services.schedule_service import ScheduleService, compute_free_windows
from app.services.task_service import TaskService
from app.web.server import create_app
from tests.test_webapp import _make_init_data


def test_brain_dump_deadlines_tags_and_recurrence():
    today = date(2026, 11, 26)  # Thursday
    msg = (
        "сдать лабу №4 #учёба до 28.11; "
        "реферат #учёба до 10.12; "
        "каждый день английский 20 мин #привычка; "
        "пн ср пт зал #спорт"
    )
    drafts = split_brain_dump(msg, today=today)
    assert len(drafts) == 4

    # 2 days until 28.11 -> auto-escalated to priority 1!
    assert drafts[0].deadline_date == "2026-11-28"
    assert drafts[0].priority == 1
    assert "учёба" in drafts[0].tags

    # 14 days until 10.12 -> stays priority 2
    assert drafts[1].deadline_date == "2026-12-10"
    assert drafts[1].priority == 2

    # Daily habit
    assert drafts[2].recurrence_rule == "daily"
    assert "привычка" in drafts[2].tags

    # Mon/Wed/Fri habit
    assert drafts[3].recurrence_rule == "days:0,2,4"
    assert "спорт" in drafts[3].tags


def test_universal_schedule_parsers_and_zoom():
    # 1. ICS
    ics = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\n"
        "DTSTART;TZID=Asia/Yekaterinburg:20261126T090000\r\n"
        "DTEND;TZID=Asia/Yekaterinburg:20261126T103000\r\n"
        "SUMMARY:Математический анализ\r\n"
        "LOCATION:ауд. 501\r\n"
        "DESCRIPTION:Ссылка https://zoom.us/j/123456789\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    ).encode("utf-8")
    ics_items = parse_ics_schedule(ics, tz_name="Asia/Yekaterinburg")
    assert len(ics_items) == 1
    assert ics_items[0].start_time == "09:00"
    assert "zoom.us/j/123456789" in ics_items[0].meeting_info

    # 2. XLSX matrix
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Время", "Пн 23.11", "Вт 24.11"])
    ws.append(["09:00-10:30", "Алгоритмы ауд. 305", "Физика"])
    buf = io.BytesIO()
    wb.save(buf)
    xlsx_items = parse_xlsx_schedule(buf.getvalue(), reference_date=date(2026, 11, 23))
    assert len(xlsx_items) == 2

    # 3. CSV row-oriented
    csv_bytes = "День;Время;Предмет;Аудитория\nСр 25.11;10:40-12:10;Операционные системы;614\n".encode("utf-8")
    csv_items = parse_csv_schedule(csv_bytes, reference_date=date(2026, 11, 23))
    assert len(csv_items) == 1
    assert csv_items[0].event_date == "2026-11-25"

    # 4. Plain text multi-line
    txt = "Понедельник 23.11\n09:00-10:30 Матан | ауд. 501\n12:30-14:00 Дискретка"
    txt_items = parse_plain_text_schedule(txt, reference_date=date(2026, 11, 23))
    assert len(txt_items) == 2

    # 5. DOCX Zoom header extraction
    doc = Document()
    doc.add_paragraph("ZOOM Идентификатор: 961 1154 5087, код доступа: 3673")
    tbl = doc.add_table(rows=2, cols=3)
    tbl.rows[0].cells[0].text = "Понедельник 23.11"
    tbl.rows[0].cells[1].text = "10:40-12:10"
    tbl.rows[0].cells[2].text = "Zoom Дифференциальные уравнения"
    dbuf = io.BytesIO()
    doc.save(dbuf)
    docx_items = parse_docx_schedule(dbuf.getvalue(), reference_date=date(2026, 11, 23))
    assert len(docx_items) == 1
    assert "961 1154 5087" in docx_items[0].meeting_info
    assert "3673" in docx_items[0].meeting_info


def test_compute_free_windows():
    events = [
        ScheduleEvent(id=1, user_id=1, event_date="2026-11-27", start_time="09:00", end_time="12:10", title="A"),
        ScheduleEvent(id=2, user_id=1, event_date="2026-11-27", start_time="14:10", end_time="15:40", title="B"),
    ]
    windows = compute_free_windows(events, day_start="08:00", day_end="22:00")
    assert [(w.start_time, w.end_time) for w in windows] == [
        ("08:00", "09:00"),
        ("12:10", "14:10"),
        ("15:40", "22:00"),
    ]


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "v2.db")
    await database.init()
    await database.upsert_user(user_id=901, username="alex", first_name="Alex")
    await database.upsert_user(user_id=902, username="friend", first_name="Friend")
    return database


async def test_deadline_auto_escalation_subtasks_habits_and_review(db: Database, tmp_path):
    tasks = TaskService(db)
    schedule = ScheduleService(db)
    history = HistoryService(db)
    review = WeeklyReviewService(db, tasks, history)

    # Task with deadline 5 days away starts priority 2, then auto-escalates when 2 days remain
    t_dl = await tasks.create_task(
        901, "Сдать курсовую", deadline_date="2026-12-01", tags=["учёба"], initial_status="pool", today_iso="2026-11-26"
    )
    assert t_dl.priority == 2

    changed = await tasks.escalate_deadline_priorities(901, "2026-11-29")
    assert changed == 1
    t_dl_after = await tasks.get_task(901, t_dl.id)
    assert t_dl_after is not None and t_dl_after.priority == 1

    # Tag filtering
    assert await tasks.list_pool_tags(901) == ["учёба"]
    assert len(await tasks.list_pool(901, tag="учёба")) == 1
    assert len(await tasks.list_pool(901, tag="дом")) == 0

    # Subtasks
    s1 = await tasks.add_subtask(901, t_dl.id, "Написать введение")
    assert s1 is not None
    await tasks.toggle_subtask(901, s1.id)
    loaded = await tasks.get_task(901, t_dl.id)
    assert loaded is not None and len(loaded.subtasks) == 1 and loaded.subtasks[0].is_done is True

    # Recurring habit materializes idempotently
    await tasks.create_task(901, "Зарядка", planned_date="2026-11-26", recurrence_rule="daily")
    plan_27 = await tasks.get_day_plan(901, "2026-11-27", today_iso="2026-11-27")
    assert any(t.title == "Зарядка" for t in plan_27.tasks)
    # Calling again does not duplicate
    plan_27_again = await tasks.get_day_plan(901, "2026-11-27", today_iso="2026-11-27")
    assert sum(1 for t in plan_27_again.tasks if t.title == "Зарядка") == 1

    # Shared group schedule publish & sync to classmate
    await schedule.publish_shared_schedule(
        "ВМ-21",
        [ParsedScheduleItem(event_date="2026-11-27", start_time="09:00", end_time="10:30", title="Тервер")],
        uploaded_by=901,
    )
    synced = await schedule.sync_from_shared_group(902, "ВМ-21", from_date_iso="2026-11-26")
    assert synced == 1

    # Weekly review works cleanly without AI key
    html = await review.build_weekly_review_html(901, "2026-11-29")
    assert "Воскресное ревью недели" in html

    # Local SQLite online backup produces valid gzip
    backup_svc = BackupService(
        Settings(DATABASE_PATH=tmp_path / "v2.db", LOCAL_BACKUP_DIR=tmp_path / "backups", S3_BACKUP_BUCKET="")
    )
    res = await backup_svc.run_backup()
    assert res.local_path.exists()
    with gzip.open(res.local_path, "rb") as f:
        header = f.read(16)
    assert header.startswith(b"SQLite format 3")


def test_webapp_subtasks_and_schedule_upload(tmp_path):
    token = "123456:TEST_TOKEN"
    settings = Settings(BOT_TOKEN=token, DATABASE_PATH=tmp_path / "web_v2.db", ALLOWED_USER_IDS="555")
    app = create_app(settings)
    headers = {"X-Telegram-Init-Data": _make_init_data(token, user_id=555)}

    with TestClient(app) as client:
        dump = client.post(
            "/api/tasks/dump",
            headers=headers,
            json={"text": "Курсовая #учёба до 28.11", "target_bucket": "pool"},
        )
        assert dump.status_code == 200
        tid = dump.json()["created"][0]["id"]

        st = client.post(f"/api/tasks/{tid}/subtasks", headers=headers, json={"title": "Глава 1"})
        assert st.status_code == 200
        sid = st.json()["subtask"]["id"]
        assert client.post(f"/api/subtasks/{sid}/toggle", headers=headers).status_code == 200

        pool = client.get("/api/pool?tag=учёба", headers=headers)
        assert pool.status_code == 200
        assert len(pool.json()["tasks"]) == 1
        assert pool.json()["tasks"][0]["subtasks"][0]["is_done"] is True

        # Upload .ics schedule via multipart endpoint
        ics = b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:20261127T090000Z\r\nSUMMARY:Test Class\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        up = client.post(
            "/api/schedule/upload",
            headers=headers,
            files={"file": ("week.ics", ics, "text/calendar")},
        )
        assert up.status_code == 200
        assert up.json()["saved"] == 1
