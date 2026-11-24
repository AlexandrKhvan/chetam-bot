from __future__ import annotations

import io
import re
from datetime import date, timedelta
from pathlib import Path

from docx import Document

from app.db.models import ParsedScheduleItem

WEEKDAY_MAP: dict[str, int] = {
    "понедельник": 0,
    "пн": 0,
    "monday": 0,
    "mon": 0,
    "вторник": 1,
    "вт": 1,
    "tuesday": 1,
    "tue": 1,
    "среда": 2,
    "ср": 2,
    "wednesday": 2,
    "wed": 2,
    "четверг": 3,
    "чт": 3,
    "thursday": 3,
    "thu": 3,
    "пятница": 4,
    "пт": 4,
    "friday": 4,
    "fri": 4,
    "суббота": 5,
    "сб": 5,
    "saturday": 5,
    "sat": 5,
    "воскресенье": 6,
    "вс": 6,
    "sunday": 6,
    "sun": 6,
}

MONTH_MAP: dict[str, int] = {
    "янв": 1,
    "фев": 2,
    "мар": 3,
    "апр": 4,
    "май": 5,
    "мая": 5,
    "июн": 6,
    "июл": 7,
    "авг": 8,
    "сен": 9,
    "окт": 10,
    "ноя": 11,
    "дек": 12,
}

DATE_RANGE_RE = re.compile(
    r"(?:с|from)?\s*(\d{1,2})[./](\d{1,2})[./](\d{2,4})\s*(?:по|[-–—]|to)\s*(\d{1,2})[./](\d{1,2})[./](\d{2,4})",
    re.IGNORECASE,
)
DATE_NUMERIC_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b")
DATE_TEXT_RU_RE = re.compile(
    r"\b(\d{1,2})\s+(январ[яь]|феврал[яь]|март[а]?|апрел[яь]|ма[яй]|июн[яь]|июл[яь]|август[а]?|сентябр[яь]|октябр[яь]|ноябр[яь]|декабр[яь])\b",
    re.IGNORECASE,
)
TIME_RANGE_RE = re.compile(
    r"\b(\d{1,2})[:.](\d{2})\s*(?:[-–—~]|до|\n)\s*(\d{1,2})[:.](\d{2})\b"
)
SINGLE_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
ROOM_RE = re.compile(
    r"\b(?:ауд\.?|каб\.?|к\.|room|аудитория)\s*[:.]?\s*([A-Za-zА-Яа-я0-9\-/]*\d[A-Za-zА-Яа-я0-9\-/]*)",
    re.IGNORECASE,
)
LEADING_ROOM_RE = re.compile(r"^(\d{3}[А-Яа-яA-Za-z]?)\s+(.*)$")
ZOOM_RE = re.compile(r"\bzoom\b", re.IGNORECASE)
GROUP_TAG_RE = re.compile(r"(?:^|[\s.,;(])([А-ЯЁA-Z]{2,5}-\d{2,3}[А-Яа-я]?)\b")
ROMAN_PAIR_RE = re.compile(r"^[IVX]{1,4}$")
MODE_CELL_RE = re.compile(r"^(?:ОО|ДОО|ДО)(?:[\s/\n]+(?:ОО|ДОО|ДО))*$", re.IGNORECASE)
TEACHER_SPLIT_RE = re.compile(
    r"\s+(?=(?:ст\.?\s*преп\.?|преп\.?|доцент|профессор|проф\.?|асс\.?|КФ\s+МГУ|МГУ)\b)",
    re.IGNORECASE,
)
CLASS_TYPE_RE = re.compile(
    r"\b(Лекци[яи]|Семинар[ы]?|Сем\.?|Практик[аи]|Лаб\.?\s*раб\.?|Спец\.?\s*группа)\b",
    re.IGNORECASE,
)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.replace("\xa0", " ")).strip()


def _resolve_week_monday(reference_date: date) -> date:
    if reference_date.weekday() == 6:
        return reference_date + timedelta(days=1)
    return reference_date - timedelta(days=reference_date.weekday())


def detect_date_range_in_doc(doc: Document) -> tuple[date, date] | None:
    """Finds an explicit date range like 'с 23.11.2026 по 28.11.2026' in paragraphs or tables."""
    texts: list[str] = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables[:2]:
        for row in table.rows[:10]:
            for cell in _dedupe_row_cells(row):
                if cell:
                    texts.append(cell)

    for text in texts:
        m = DATE_RANGE_RE.search(text)
        if not m:
            continue
        d1, mo1, y1, d2, mo2, y2 = map(int, m.groups())
        if y1 < 100:
            y1 += 2000
        if y2 < 100:
            y2 += 2000
        try:
            start = date(y1, mo1, d1)
            end = date(y2, mo2, d2)
            if 0 <= (end - start).days <= 14:
                return start, end
        except ValueError:
            continue
    return None


def detect_date_in_text(text: str, reference_date: date) -> date | None:
    cleaned = _normalize_whitespace(text)
    if not cleaned:
        return None

    m_num = DATE_NUMERIC_RE.search(cleaned)
    if m_num:
        day_val = int(m_num.group(1))
        month_val = int(m_num.group(2))
        year_str = m_num.group(3)
        if year_str:
            year_val = int(year_str)
            if year_val < 100:
                year_val += 2000
        else:
            year_val = reference_date.year
            if reference_date.month == 12 and month_val == 1:
                year_val += 1
            elif reference_date.month == 1 and month_val == 12:
                year_val -= 1
        try:
            return date(year_val, month_val, day_val)
        except ValueError:
            pass

    m_ru = DATE_TEXT_RU_RE.search(cleaned)
    if m_ru:
        day_val = int(m_ru.group(1))
        month_prefix = m_ru.group(2).lower()[:3]
        month_val = MONTH_MAP.get(month_prefix)
        if month_val:
            year_val = reference_date.year
            if reference_date.month == 12 and month_val == 1:
                year_val += 1
            try:
                return date(year_val, month_val, day_val)
            except ValueError:
                pass

    lowered = cleaned.lower()
    tokens = re.findall(r"[а-яёa-z]+", lowered)
    monday = _resolve_week_monday(reference_date)
    for token in tokens:
        if token in WEEKDAY_MAP:
            return monday + timedelta(days=WEEKDAY_MAP[token])

    return None


def extract_time_range(text: str) -> tuple[str, str] | None:
    m_range = TIME_RANGE_RE.search(text)
    if m_range:
        h1, m1, h2, m2 = map(int, m_range.groups())
        if 0 <= h1 <= 23 and 0 <= m1 <= 59 and 0 <= h2 <= 23 and 0 <= m2 <= 59:
            return f"{h1:02d}:{m1:02d}", f"{h2:02d}:{m2:02d}"

    matches = SINGLE_TIME_RE.findall(text)
    valid_times: list[str] = []
    for h_str, m_str in matches:
        h, m = int(h_str), int(m_str)
        if 0 <= h <= 23 and 0 <= m <= 59:
            valid_times.append(f"{h:02d}:{m:02d}")
    if len(valid_times) >= 2:
        return valid_times[0], valid_times[1]
    if len(valid_times) == 1:
        return valid_times[0], ""
    return None


def _extract_location_and_clean(text: str) -> tuple[str, str]:
    location = ""
    m_room = ROOM_RE.search(text)
    if m_room:
        location = f"ауд. {m_room.group(1)}"
    cleaned = _normalize_whitespace(text.replace("\n", " · "))
    cleaned = re.sub(r"(?:·\s*)+", " · ", cleaned).strip(" ·-")
    return cleaned, location


def _dedupe_row_cells(row) -> list[str]:
    texts: list[str] = []
    seen_ids: set[int] = set()
    for cell in row.cells:
        tc_id = id(cell._tc)
        if tc_id in seen_ids:
            continue
        seen_ids.add(tc_id)
        texts.append(cell.text.strip())
    return texts


def _split_multi_entry_cell(raw_cell: str) -> list[str]:
    """Splits a cell that may hold entries for multiple groups (e.g. ВМ-21 and ВМ-22),
    while re-joining wrapped continuation lines like teacher names."""
    raw_lines = [_normalize_whitespace(line) for line in raw_cell.splitlines()]
    lines = [line for line in raw_lines if line]
    if len(lines) <= 1:
        return lines

    entries: list[str] = []
    for line in lines:
        starts_new = bool(
            LEADING_ROOM_RE.match(line)
            or line.lower().startswith("физическая культура")
            or (entries and GROUP_TAG_RE.search(entries[-1]))
        )
        if not entries or starts_new:
            entries.append(line)
        else:
            entries[-1] = f"{entries[-1]} {line}".strip()
    return entries


def _parse_university_entry(entry_text: str) -> tuple[str, str, str, str]:
    """Parses a university class string like:
    '614 Zoom Дифференциальные уравнения Лекции доцент МГУ Разборов А.Г. ВМ-21'
    into (title, location, notes, group_tag)."""
    text = _normalize_whitespace(entry_text)
    group_tag = ""
    m_group = GROUP_TAG_RE.search(text)
    if m_group:
        group_tag = m_group.group(1).upper()
        text = (text[: m_group.start(1)] + text[m_group.end(1) :]).strip(" .,;-")

    location_parts: list[str] = []
    m_lead = LEADING_ROOM_RE.match(text)
    if m_lead:
        location_parts.append(f"ауд. {m_lead.group(1)}")
        text = m_lead.group(2).strip()
    else:
        m_room = ROOM_RE.search(text)
        if m_room:
            location_parts.append(f"ауд. {m_room.group(1)}")

    if ZOOM_RE.search(text):
        location_parts.append("Zoom")
        text = ZOOM_RE.sub("", text).strip(" .,;-")

    location = " · ".join(location_parts)

    notes = ""
    parts = TEACHER_SPLIT_RE.split(text, maxsplit=1)
    if len(parts) == 2 and parts[0].strip():
        subject_part = parts[0].strip(" .,;-")
        notes = parts[1].strip(" .,;-")
    else:
        subject_part = text.strip(" .,;-")

    m_type = CLASS_TYPE_RE.search(subject_part)
    if m_type:
        raw_type = m_type.group(1).lower()
        if raw_type.startswith("лекц"):
            pretty_type = "Лекция"
        elif raw_type.startswith("сем"):
            pretty_type = "Семинар"
        elif raw_type.startswith("практ"):
            pretty_type = "Практика"
        elif raw_type.startswith("лаб"):
            pretty_type = "Лаб."
        elif raw_type.startswith("спец"):
            pretty_type = "Спец.группа"
        else:
            pretty_type = m_type.group(1)
        clean_subj = _normalize_whitespace(
            subject_part[: m_type.start()] + " " + subject_part[m_type.end() :]
        ).strip(" .,;-")
        if clean_subj:
            title = f"{clean_subj} ({pretty_type})"
        else:
            title = subject_part
    else:
        title = subject_part

    return _normalize_whitespace(title), location, _normalize_whitespace(notes), group_tag


def _parse_matrix_table(table, reference_date: date) -> list[ParsedScheduleItem]:
    if len(table.rows) < 2:
        return []
    header_cells = [c.text.strip() for c in table.rows[0].cells]
    col_dates: dict[int, date] = {}
    for idx, cell_text in enumerate(header_cells):
        if idx == 0:
            continue
        detected = detect_date_in_text(cell_text, reference_date)
        if detected:
            col_dates[idx] = detected

    if len(col_dates) < 2:
        return []

    items: list[ParsedScheduleItem] = []
    for row in table.rows[1:]:
        raw_cells = [c.text.strip() for c in row.cells]
        if not raw_cells:
            continue
        time_info = extract_time_range(raw_cells[0])
        if not time_info:
            continue
        start_t, end_t = time_info

        seen_col_tc: set[int] = set()
        for col_idx, day_date in col_dates.items():
            if col_idx >= len(row.cells):
                continue
            tc_id = id(row.cells[col_idx]._tc)
            if tc_id in seen_col_tc:
                continue
            seen_col_tc.add(tc_id)
            content = raw_cells[col_idx].strip()
            if not content or content in {"-", "—", "–"}:
                continue
            title, location = _extract_location_and_clean(content)
            if title:
                items.append(
                    ParsedScheduleItem(
                        event_date=day_date.isoformat(),
                        start_time=start_t,
                        end_time=end_t,
                        title=title,
                        location=location,
                    )
                )
    return items


def _parse_row_table(table, reference_date: date) -> list[ParsedScheduleItem]:
    items: list[ParsedScheduleItem] = []
    current_date: date | None = None

    for row in table.rows:
        cells = _dedupe_row_cells(row)
        non_empty = [c for c in cells if c.strip()]
        if not non_empty:
            continue

        if len(non_empty) == 1:
            if DATE_RANGE_RE.search(non_empty[0]):
                continue
            maybe_date = detect_date_in_text(non_empty[0], reference_date)
            if maybe_date and not extract_time_range(non_empty[0]):
                current_date = maybe_date
                continue

        if cells and DATE_RANGE_RE.search(cells[0]):
            continue

        row_date = detect_date_in_text(cells[0], reference_date) if cells else None
        remaining_cells = list(cells)
        if row_date is not None and not extract_time_range(cells[0]):
            current_date = row_date
            remaining_cells = cells[1:]
        elif row_date is not None and current_date is None:
            current_date = row_date

        if current_date is None:
            continue

        time_idx: int | None = None
        time_info: tuple[str, str] | None = None
        for idx, cell_text in enumerate(remaining_cells):
            t = extract_time_range(cell_text)
            if t:
                time_idx = idx
                time_info = t
                break

        if time_info is None or time_idx is None:
            continue

        start_t, end_t = time_info
        other_cells = [
            c.strip()
            for idx, c in enumerate(remaining_cells)
            if idx != time_idx
            and c.strip()
            and c.strip() not in {"-", "—", "–"}
            and not ROMAN_PAIR_RE.match(c.strip())
            and not MODE_CELL_RE.match(c.strip())
        ]
        if not other_cells:
            stripped = TIME_RANGE_RE.sub("", remaining_cells[time_idx])
            stripped = SINGLE_TIME_RE.sub("", stripped).strip(" -–—:\n\t")
            if stripped:
                other_cells = [stripped]

        if not other_cells:
            continue

        title_raw = other_cells[0]
        extra = " · ".join(other_cells[1:]) if len(other_cells) > 1 else ""
        title, detected_loc = _extract_location_and_clean(title_raw)
        location = detected_loc
        notes = ""
        if extra:
            extra_clean, extra_loc = _extract_location_and_clean(extra)
            if not location and (extra_loc or len(extra_clean) <= 18):
                location = extra_loc or extra_clean
            else:
                notes = extra_clean

        if title:
            items.append(
                ParsedScheduleItem(
                    event_date=current_date.isoformat(),
                    start_time=start_t,
                    end_time=end_t,
                    title=title,
                    location=location,
                    notes=notes,
                )
            )
    return items


def _parse_sequential_day_blocks(
    doc: Document, start_date: date
) -> list[ParsedScheduleItem]:
    """Parses university schedules split into repeating daily time-slot blocks across
    one or more tables (where column 0 has no text / vertical shapes and each new day
    resets start_time back to the first slot like 09:00)."""
    items: list[ParsedScheduleItem] = []
    day_index = -1
    prev_start_minutes: int | None = None

    for table in doc.tables:
        for row in table.rows:
            cells = _dedupe_row_cells(row)
            time_idx: int | None = None
            time_info: tuple[str, str] | None = None
            for idx, cell_text in enumerate(cells):
                t = extract_time_range(cell_text)
                if t:
                    time_idx = idx
                    time_info = t
                    break

            if time_info is None or time_idx is None:
                continue

            start_t, end_t = time_info
            h, m = map(int, start_t.split(":"))
            start_minutes = h * 60 + m

            if prev_start_minutes is None or start_minutes <= prev_start_minutes:
                day_index += 1
            prev_start_minutes = start_minutes

            event_day = start_date + timedelta(days=day_index)

            content_cells = [
                c.strip()
                for idx, c in enumerate(cells)
                if idx != time_idx
                and c.strip()
                and c.strip() not in {"-", "—", "–"}
                and not ROMAN_PAIR_RE.match(c.strip())
                and not MODE_CELL_RE.match(c.strip())
            ]
            if not content_cells:
                continue

            raw_content = "\n".join(content_cells)
            for entry_line in _split_multi_entry_cell(raw_content):
                title, location, notes, group_tag = _parse_university_entry(entry_line)
                if title:
                    items.append(
                        ParsedScheduleItem(
                            event_date=event_day.isoformat(),
                            start_time=start_t,
                            end_time=end_t,
                            title=title,
                            location=location,
                            notes=notes,
                            group_tag=group_tag,
                        )
                    )
    return items


def _parse_paragraphs(doc: Document, reference_date: date) -> list[ParsedScheduleItem]:
    items: list[ParsedScheduleItem] = []
    current_date: date | None = None

    for para in doc.paragraphs:
        text = _normalize_whitespace(para.text)
        if not text:
            continue

        time_info = extract_time_range(text)
        detected_date = detect_date_in_text(text, reference_date)

        if detected_date and not time_info:
            current_date = detected_date
            continue

        if detected_date and time_info:
            current_date = detected_date

        if current_date and time_info:
            start_t, end_t = time_info
            without_time = TIME_RANGE_RE.sub("", text)
            without_time = SINGLE_TIME_RE.sub("", without_time, count=1)
            without_time = without_time.strip(" -–—:|\t")
            title, location = _extract_location_and_clean(without_time)
            if title:
                items.append(
                    ParsedScheduleItem(
                        event_date=current_date.isoformat(),
                        start_time=start_t,
                        end_time=end_t,
                        title=title,
                        location=location,
                    )
                )
    return items


def extract_detected_groups(items: list[ParsedScheduleItem]) -> list[str]:
    return sorted({i.group_tag for i in items if i.group_tag})


def filter_items_by_group(
    items: list[ParsedScheduleItem], group: str | None
) -> list[ParsedScheduleItem]:
    if not group:
        return list(items)
    target = group.strip().upper()
    return [i for i in items if not i.group_tag or i.group_tag.upper() == target]


def extract_docx_text(source: bytes | str | Path) -> str:
    doc = Document(io.BytesIO(source)) if isinstance(source, bytes) else Document(str(source))
    lines: list[str] = []
    for p in doc.paragraphs:
        t = _normalize_whitespace(p.text)
        if t:
            lines.append(t)
    for t_idx, table in enumerate(doc.tables, start=1):
        lines.append(f"--- Таблица {t_idx} ---")
        for row in table.rows:
            cells = [_normalize_whitespace(c.replace("\n", " / ")) for c in _dedupe_row_cells(row)]
            if any(cells):
                lines.append(" | ".join(cells))
    return "\n".join(lines)


def parse_docx_schedule(
    source: bytes | str | Path,
    *,
    reference_date: date | None = None,
) -> list[ParsedScheduleItem]:
    ref = reference_date or date.today()
    doc = Document(io.BytesIO(source)) if isinstance(source, bytes) else Document(str(source))

    date_range = detect_date_range_in_doc(doc)
    effective_ref = date_range[0] if date_range else ref

    items: list[ParsedScheduleItem] = []
    for table in doc.tables:
        matrix_items = _parse_matrix_table(table, effective_ref)
        if matrix_items:
            items.extend(matrix_items)
        else:
            items.extend(_parse_row_table(table, effective_ref))

    if not items and doc.tables:
        anchor_monday = date_range[0] if date_range else _resolve_week_monday(ref)
        items.extend(_parse_sequential_day_blocks(doc, anchor_monday))

    if not items:
        items.extend(_parse_paragraphs(doc, effective_ref))

    seen: set[tuple[str, str, str, str]] = set()
    unique: list[ParsedScheduleItem] = []
    for item in items:
        key = (item.event_date, item.start_time, item.title.lower(), item.group_tag)
        if key not in seen:
            seen.add(key)
            unique.append(item)

    unique.sort(key=lambda x: (x.event_date, x.start_time, x.group_tag, x.title))
    return unique
