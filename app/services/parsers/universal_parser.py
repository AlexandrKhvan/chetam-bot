from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import openpyxl
from pypdf import PdfReader

from app.db.models import ParsedScheduleItem
from app.services.parsers.docx_parser import (
    MODE_CELL_RE,
    ROMAN_PAIR_RE,
    SINGLE_TIME_RE,
    TIME_RANGE_RE,
    _extract_location_and_clean,
    _normalize_whitespace,
    detect_date_in_text,
    detect_meeting_info_in_text,
    extract_docx_text,
    extract_time_range,
    parse_docx_schedule,
)
from app.services.parsers.vision_parser import VisionScheduleParser
from app.services.time_utils import get_zoneinfo


def _unfold_ics_lines(raw_text: str) -> list[str]:
    unfolded: list[str] = []
    for raw_line in raw_text.replace("\r\n", "\n").split("\n"):
        if raw_line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += raw_line[1:]
        else:
            unfolded.append(raw_line)
    return unfolded


def _parse_ics_datetime(prop_name: str, value: str, user_tz: ZoneInfo) -> datetime | None:
    val = value.strip()
    tz = user_tz
    if "TZID=" in prop_name:
        m = re.search(r"TZID=([^;:]+)", prop_name)
        if m:
            tz = get_zoneinfo(m.group(1))
    if val.endswith("Z"):
        try:
            dt = datetime.strptime(val, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            return dt.astimezone(user_tz)
        except ValueError:
            return None
    if "T" in val:
        try:
            dt = datetime.strptime(val[:15], "%Y%m%dT%H%M%S").replace(tzinfo=tz)
            return dt.astimezone(user_tz)
        except ValueError:
            return None
    if len(val) == 8 and val.isdigit():
        try:
            d = datetime.strptime(val, "%Y%m%d").date()
            return datetime(d.year, d.month, d.day, 9, 0, tzinfo=user_tz)
        except ValueError:
            return None
    return None


def parse_ics_schedule(raw_bytes: bytes, *, tz_name: str = "Asia/Yekaterinburg") -> list[ParsedScheduleItem]:
    """Parses standard .ics (iCalendar) exports from Google/Apple/Yandex/University calendars."""
    text = raw_bytes.decode("utf-8", errors="replace")
    lines = _unfold_ics_lines(text)
    user_tz = get_zoneinfo(tz_name)

    items: list[ParsedScheduleItem] = []
    in_event = False
    ev: dict[str, tuple[str, str]] = {}

    for line in lines:
        stripped = line.strip()
        if stripped == "BEGIN:VEVENT":
            in_event = True
            ev = {}
            continue
        if stripped == "END:VEVENT" and in_event:
            in_event = False
            start_prop = ev.get("DTSTART")
            summary_prop = ev.get("SUMMARY")
            if not start_prop or not summary_prop:
                continue
            dt_start = _parse_ics_datetime(start_prop[0], start_prop[1], user_tz)
            if not dt_start:
                continue
            end_prop = ev.get("DTEND")
            dt_end = _parse_ics_datetime(end_prop[0], end_prop[1], user_tz) if end_prop else None
            title = summary_prop[1].replace("\\,", ",").replace("\\;", ";").replace("\\n", " ").strip()
            location = ev.get("LOCATION", ("", ""))[1].replace("\\,", ",").strip()
            description = ev.get("DESCRIPTION", ("", ""))[1].replace("\\n", "\n").strip()
            meeting_info = detect_meeting_info_in_text(f"{location}\n{description}")
            items.append(
                ParsedScheduleItem(
                    event_date=dt_start.date().isoformat(),
                    start_time=dt_start.strftime("%H:%M"),
                    end_time=dt_end.strftime("%H:%M") if dt_end else "",
                    title=title,
                    location=location[:120],
                    notes=description[:200],
                    meeting_info=meeting_info,
                )
            )
            continue
        if in_event and ":" in line:
            prop, val = line.split(":", 1)
            base_key = prop.split(";", 1)[0].upper()
            ev[base_key] = (prop, val)

    items.sort(key=lambda x: (x.event_date, x.start_time, x.title))
    return items


def _parse_grid_rows(rows: list[list[str]], reference_date: date) -> list[ParsedScheduleItem]:
    """Universal 2D grid parser for Excel (.xlsx) and CSV tables (supports matrix and row-oriented layouts)."""
    clean_rows = [[_normalize_whitespace(str(c or "")) for c in r] for r in rows]
    clean_rows = [r for r in clean_rows if any(r)]
    if not clean_rows:
        return []

    # 1. Try matrix layout: find header row where >= 2 columns look like weekdays/dates
    for hdr_idx, hdr in enumerate(clean_rows[:5]):
        col_dates: dict[int, date] = {}
        for col_idx, cell in enumerate(hdr):
            if col_idx == 0:
                continue
            d = detect_date_in_text(cell, reference_date)
            if d:
                col_dates[col_idx] = d
        if len(col_dates) >= 2:
            items: list[ParsedScheduleItem] = []
            for row in clean_rows[hdr_idx + 1 :]:
                if not row:
                    continue
                t_info = extract_time_range(row[0])
                if not t_info:
                    continue
                start_t, end_t = t_info
                for col_idx, day_d in col_dates.items():
                    if col_idx >= len(row):
                        continue
                    content = row[col_idx].strip()
                    if not content or content in {"-", "—", "–"}:
                        continue
                    title, loc = _extract_location_and_clean(content)
                    if title:
                        items.append(
                            ParsedScheduleItem(
                                event_date=day_d.isoformat(),
                                start_time=start_t,
                                end_time=end_t,
                                title=title,
                                location=loc,
                                meeting_info=detect_meeting_info_in_text(content),
                            )
                        )
            if items:
                items.sort(key=lambda x: (x.event_date, x.start_time, x.title))
                return items

    # 2. Row-oriented layout: Day | Time | Subject | Room
    items = []
    current_date: date | None = None
    for row in clean_rows:
        non_empty = [c for c in row if c]
        if len(non_empty) == 1:
            maybe_d = detect_date_in_text(non_empty[0], reference_date)
            if maybe_d and not extract_time_range(non_empty[0]):
                current_date = maybe_d
                continue

        row_d = detect_date_in_text(row[0], reference_date) if row else None
        rest = list(row)
        if row_d and not extract_time_range(row[0]):
            current_date = row_d
            rest = row[1:]
        elif row_d and current_date is None:
            current_date = row_d

        if current_date is None:
            continue

        time_idx: int | None = None
        time_info: tuple[str, str] | None = None
        for idx, cell in enumerate(rest):
            t = extract_time_range(cell)
            if t:
                time_idx = idx
                time_info = t
                break
        if not time_info or time_idx is None:
            continue

        start_t, end_t = time_info
        others = [
            c
            for idx, c in enumerate(rest)
            if idx != time_idx
            and c
            and c not in {"-", "—", "–"}
            and not ROMAN_PAIR_RE.match(c)
            and not MODE_CELL_RE.match(c)
        ]
        if not others:
            continue
        title, loc = _extract_location_and_clean(others[0])
        if not loc and len(others) > 1:
            loc = others[1]
        meeting_info = detect_meeting_info_in_text(" ".join(others))
        if title:
            items.append(
                ParsedScheduleItem(
                    event_date=current_date.isoformat(),
                    start_time=start_t,
                    end_time=end_t,
                    title=title,
                    location=loc,
                    meeting_info=meeting_info,
                )
            )
    items.sort(key=lambda x: (x.event_date, x.start_time, x.title))
    return items


def parse_xlsx_schedule(raw_bytes: bytes, *, reference_date: date) -> list[ParsedScheduleItem]:
    wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=True, read_only=True)
    all_items: list[ParsedScheduleItem] = []
    for sheet in wb.worksheets:
        rows = [["" if v is None else str(v) for v in row] for row in sheet.iter_rows(values_only=True)]
        all_items.extend(_parse_grid_rows(rows, reference_date))
    wb.close()
    all_items.sort(key=lambda x: (x.event_date, x.start_time, x.title))
    return all_items


def parse_csv_schedule(raw_bytes: bytes, *, reference_date: date) -> list[ParsedScheduleItem]:
    for enc in ("utf-8-sig", "cp1251", "latin-1"):
        try:
            text = raw_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw_bytes.decode("utf-8", errors="replace")

    sample = text[:1024]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [row for row in reader]
    return _parse_grid_rows(rows, reference_date)


def parse_plain_text_schedule(text: str, *, reference_date: date) -> list[ParsedScheduleItem]:
    """Parses free-form pasted or PDF-extracted schedule text line by line."""
    items: list[ParsedScheduleItem] = []
    current_date: date | None = None
    doc_meeting = detect_meeting_info_in_text(text)

    for raw_line in text.splitlines():
        line = _normalize_whitespace(raw_line)
        if not line:
            continue

        time_info = extract_time_range(line)
        detected_date = detect_date_in_text(line, reference_date)

        if detected_date and not time_info:
            current_date = detected_date
            continue

        if detected_date and time_info:
            current_date = detected_date

        if current_date and time_info:
            start_t, end_t = time_info
            # Support optional "| location" separator
            location = ""
            if "|" in line:
                main_part, location = [p.strip() for p in line.split("|", 1)]
            else:
                main_part = line
            without_time = TIME_RANGE_RE.sub("", main_part)
            without_time = SINGLE_TIME_RE.sub("", without_time, count=1)
            # Strip leading weekday/date token if present before time
            without_time = re.sub(
                r"^(?:понедельник|вторник|среда|четверг|пятница|суббота|воскресенье|пн|вт|ср|чт|пт|сб|вс|сегодня|завтра|\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?)[\s,.:-]*",
                "",
                without_time.strip(),
                flags=re.IGNORECASE,
            ).strip(" -–—:|\t")
            title, detected_loc = _extract_location_and_clean(without_time)
            final_loc = location or detected_loc
            m_info = detect_meeting_info_in_text(line) or (
                doc_meeting if ("zoom" in final_loc.lower() or "zoom" in title.lower()) else ""
            )
            if title:
                items.append(
                    ParsedScheduleItem(
                        event_date=current_date.isoformat(),
                        start_time=start_t,
                        end_time=end_t,
                        title=title,
                        location=final_loc,
                        meeting_info=m_info,
                    )
                )

    items.sort(key=lambda x: (x.event_date, x.start_time, x.title))
    return items


def parse_pdf_schedule(raw_bytes: bytes, *, reference_date: date) -> tuple[list[ParsedScheduleItem], str]:
    reader = PdfReader(io.BytesIO(raw_bytes))
    extracted = "\n".join((page.extract_text() or "") for page in reader.pages)
    items = parse_plain_text_schedule(extracted, reference_date=reference_date)
    return items, extracted


async def parse_schedule_file(
    filename: str,
    raw_bytes: bytes,
    *,
    reference_date: date,
    tz_name: str = "Asia/Yekaterinburg",
    vision_parser: VisionScheduleParser | None = None,
) -> tuple[list[ParsedScheduleItem], str, str]:
    """Universal file entrypoint. Returns (items, source_code, human_label)."""
    lower = filename.lower()
    if lower.endswith(".ics"):
        return parse_ics_schedule(raw_bytes, tz_name=tz_name), "ics", f"календарь {filename}"
    if lower.endswith(".xlsx"):
        items = parse_xlsx_schedule(raw_bytes, reference_date=reference_date)
        return items, "xlsx", f"Excel {filename}"
    if lower.endswith(".csv"):
        items = parse_csv_schedule(raw_bytes, reference_date=reference_date)
        return items, "xlsx", f"CSV {filename}"
    if lower.endswith(".txt"):
        text = raw_bytes.decode("utf-8", errors="replace")
        items = parse_plain_text_schedule(text, reference_date=reference_date)
        return items, "manual", f"текст {filename}"
    if lower.endswith(".pdf"):
        items, extracted = parse_pdf_schedule(raw_bytes, reference_date=reference_date)
        if not items and vision_parser and vision_parser.is_enabled and extracted.strip():
            items = await vision_parser.parse_text(extracted, reference_date=reference_date)
            return items, "pdf", f"PDF {filename} · AI"
        return items, "pdf", f"PDF {filename}"
    if lower.endswith(".docx"):
        items = parse_docx_schedule(raw_bytes, reference_date=reference_date)
        if not items and vision_parser and vision_parser.is_enabled:
            plain = extract_docx_text(raw_bytes)
            if plain:
                items = await vision_parser.parse_text(plain, reference_date=reference_date)
                return items, "docx", f"{filename} · AI"
        return items, "docx", f"файл {filename}"
    if lower.endswith((".png", ".jpg", ".jpeg", ".webp")):
        if not vision_parser or not vision_parser.is_enabled:
            raise RuntimeError("VISION_NOT_CONFIGURED")
        mime = "image/png" if lower.endswith(".png") else ("image/webp" if lower.endswith(".webp") else "image/jpeg")
        items = await vision_parser.parse_image(raw_bytes, mime_type=mime, reference_date=reference_date)
        return items, "photo", "фото · AI"

    raise ValueError(f"Unsupported schedule format: {filename}")
