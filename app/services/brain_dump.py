from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass(slots=True)
class ParsedTaskDraft:
    title: str
    planned_date: str | None = None
    planned_time: str | None = None
    deadline_date: str | None = None
    tags: list[str] = field(default_factory=list)
    recurrence_rule: str = ""
    priority: int = 2


ACTION_VERBS = (
    "сделать", "делать", "доделать", "переделать",
    "купить", "докупить", "заказать", "оплатить", "перевести", "пополнить",
    "написать", "дописать", "отписать", "ответить", "отправить", "скинуть", "переслать",
    "позвонить", "набрать", "спросить", "узнать", "уточнить", "договориться",
    "сходить", "зайти", "поехать", "съездить", "забрать", "отнести", "передать", "встретиться",
    "проверить", "посмотреть", "глянуть", "прочитать", "дочитать", "почитать", "изучить",
    "повторить", "выучить", "подготовить", "подготовиться", "решить", "дорешать", "сдать", "закрыть",
    "убрать", "убраться", "помыть", "постирать", "погладить", "приготовить", "разобрать", "собрать",
    "записаться", "продлить", "поменять", "обновить", "скачать", "установить", "настроить", "починить",
    "задеплоить", "запушить", "закоммитить", "протестить", "протестировать", "найти", "оформить",
    "заполнить", "пройти", "потренить", "потренироваться", "погулять", "поспать", "отдохнуть",
    "выкинуть", "вынести", "покормить", "полить", "взять", "положить", "подумать", "спланировать",
    "buy", "call", "check", "clean", "do", "email", "finish", "fix", "get", "go", "make",
    "pay", "pick", "prepare", "read", "review", "send", "study", "text", "write",
)

ACTION_VERB_PATTERN = "|".join(re.escape(v) for v in ACTION_VERBS)

STRONG_CONNECTOR_RE = re.compile(
    r"(?:,\s*|\s+)(?:"
    r"а\s+потом|и\s+потом|потом|затем|"
    r"а\s+ещ[её]|и\s+ещ[её]|ещ[её]\s+надо|ещ[её]\s+нужно|ещ[её]|"
    r"а\s+также|и\s+также|также\s+надо|также\s+нужно|также|"
    r"плюс\s+надо|плюс\s+нужно|плюс\s+ещ[её]|плюс|"
    r"заодно|кстати|"
    r"и\s+не\s+забыть|не\s+забыть|и\s+не\s+забудь|не\s+забудь|"
    r"и\s+надо|и\s+нужно|надо\s+бы|нужно\s+ещ[её]"
    r")\b",
    re.IGNORECASE,
)

INLINE_NUMBERED_RE = re.compile(r"(?:^|\s)(\d{1,2})[.)]\s+")

COMMA_VERB_RE = re.compile(
    rf",\s+(?=(?:(?:не\s+забыть|надо|нужно|срочно|важно|сегодня|завтра|послезавтра)\s+)?(?:{ACTION_VERB_PATTERN})\b)",
    re.IGNORECASE,
)
AND_VERB_RE = re.compile(
    rf"\s+и\s+(?=(?:(?:не\s+забыть|надо|нужно|срочно|важно|сегодня|завтра|послезавтра)\s+)?(?:{ACTION_VERB_PATTERN})\b)",
    re.IGNORECASE,
)

LEAD_IN_RE = re.compile(
    r"^(?:[-•*—–]+\s*|\d{1,2}[.)]\s*|"
    r"(?:ну|короче|типа|кстати|вообще|потом|затем|ещ[её]|также|плюс|заодно|"
    r"а|и|но|да|надо\s+бы|надо|нужно|необходимо|хочу|не\s+забыть|не\s+забудь|напомни)\b[\s,:;-]*)+",
    re.IGNORECASE,
)

TAG_RE = re.compile(r"(?:^|\s)#([а-яёa-z0-9_]{2,24})\b", re.IGNORECASE)
URGENT_RE = re.compile(r"(?:^|\s)(срочно|важно|критично|asap|urgent)(?=\s|$|[!.,:;])|!{2,}", re.IGNORECASE)
TIME_WITH_PREP_RE = re.compile(r"\b(?:в|к|на|at)\s*(\d{1,2})[:.](\d{2})\b", re.IGNORECASE)
BARE_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})\b|\b(\d{1,2}):(\d{2})$")
DATE_DAY_MONTH_RE = re.compile(r"\b(?:на\s+)?(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b")

DAY_HEADER_RE = re.compile(r"^(сегодня|завтра|послезавтра)\s*[:—–-]\s*(.*)$", re.IGNORECASE)
RELATIVE_DATE_RE = re.compile(
    r"\b(?:на\s+)?(послезавтра|завтра|сегодня|завтрашн\w*|сегодняшн\w*)\b",
    re.IGNORECASE,
)

# Deadlines: "до 30.11", "дедлайн 05.12", "к пятнице", "до понедельника", "дедлайн через 4 дня"
DEADLINE_NUM_RE = re.compile(
    r"\b(?:дедлайн|deadline|до|к|by)\s+(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b",
    re.IGNORECASE,
)
DEADLINE_REL_DAYS_RE = re.compile(
    r"\b(?:дедлайн|deadline|сдать)\s+через\s+(\d{1,2})\s*(?:дн(?:я|ей)?|день|days?)\b",
    re.IGNORECASE,
)
DEADLINE_WEEKDAY_RE = re.compile(
    r"\b(?:дедлайн|до|к)\s+(понедельник[ау]?|вторник[ау]?|сред[ыеу]|четверг[ау]?|пятниц[ыеу]|суббот[ыеу]|воскресень[яю])\b",
    re.IGNORECASE,
)
WEEKDAY_STEM_MAP = {
    "понедельник": 0,
    "вторник": 1,
    "сред": 2,
    "четверг": 3,
    "пятниц": 4,
    "суббот": 5,
    "воскресень": 6,
}

# Recurrence / habits
REC_DAILY_RE = re.compile(r"\b(?:каждый\s+день|ежедневно|daily|every\s+day)\b", re.IGNORECASE)
REC_WEEKDAYS_RE = re.compile(r"\b(?:по\s+будням|weekdays)\b", re.IGNORECASE)
REC_DAYS_RE = re.compile(
    r"\b((?:(?:пн|вт|ср|чт|пт|сб|вс)(?:[\s,/]+|$)){2,})",
    re.IGNORECASE,
)
SHORT_WD_MAP = {"пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6}


def _next_weekday(today: date, target_wd: int) -> date:
    delta = (target_wd - today.weekday()) % 7
    if delta == 0:
        delta = 7
    return today + timedelta(days=delta)


def _extract_tags(text: str) -> tuple[list[str], str]:
    found = [m.group(1).lower() for m in TAG_RE.finditer(text)]
    if not found:
        return [], text
    cleaned = TAG_RE.sub(" ", text)
    return list(dict.fromkeys(found)), re.sub(r"\s{2,}", " ", cleaned).strip()


def _extract_recurrence(text: str) -> tuple[str, str]:
    if REC_DAILY_RE.search(text):
        cleaned = REC_DAILY_RE.sub(" ", text)
        return "daily", re.sub(r"\s{2,}", " ", cleaned).strip()
    if REC_WEEKDAYS_RE.search(text):
        cleaned = REC_WEEKDAYS_RE.sub(" ", text)
        return "weekdays", re.sub(r"\s{2,}", " ", cleaned).strip()
    m_days = REC_DAYS_RE.search(text)
    if m_days:
        tokens = re.findall(r"пн|вт|ср|чт|пт|сб|вс", m_days.group(1).lower())
        days = sorted({SHORT_WD_MAP[t] for t in tokens if t in SHORT_WD_MAP})
        if len(days) >= 2:
            cleaned = (text[: m_days.start()] + " " + text[m_days.end() :]).strip()
            return "days:" + ",".join(str(d) for d in days), re.sub(r"\s{2,}", " ", cleaned).strip()
    return "", text


def _extract_deadline(text: str, today: date) -> tuple[str | None, str]:
    m_num = DEADLINE_NUM_RE.search(text)
    if m_num:
        d_val, mo_val = int(m_num.group(1)), int(m_num.group(2))
        y_str = m_num.group(3)
        y_val = (
            int(y_str) + (2000 if int(y_str) < 100 else 0)
            if y_str
            else (today.year + 1 if today.month == 12 and mo_val == 1 else today.year)
        )
        try:
            dl = date(y_val, mo_val, d_val)
            cleaned = (text[: m_num.start()] + " " + text[m_num.end() :]).strip()
            return dl.isoformat(), re.sub(r"\s{2,}", " ", cleaned).strip()
        except ValueError:
            pass

    m_rel = DEADLINE_REL_DAYS_RE.search(text)
    if m_rel:
        days_n = int(m_rel.group(1))
        dl = today + timedelta(days=days_n)
        cleaned = (text[: m_rel.start()] + " " + text[m_rel.end() :]).strip()
        return dl.isoformat(), re.sub(r"\s{2,}", " ", cleaned).strip()

    m_wd = DEADLINE_WEEKDAY_RE.search(text)
    if m_wd:
        word = m_wd.group(1).lower()
        for stem, wd in WEEKDAY_STEM_MAP.items():
            if word.startswith(stem):
                dl = _next_weekday(today, wd)
                cleaned = (text[: m_wd.start()] + " " + text[m_wd.end() :]).strip()
                return dl.isoformat(), re.sub(r"\s{2,}", " ", cleaned).strip()

    return None, text


def _extract_time(text: str) -> tuple[str | None, str]:
    m = TIME_WITH_PREP_RE.search(text)
    if m:
        h, minute = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= minute <= 59:
            cleaned = (text[: m.start()] + " " + text[m.end() :]).strip()
            return f"{h:02d}:{minute:02d}", re.sub(r"\s{2,}", " ", cleaned)

    m2 = BARE_TIME_RE.search(text)
    if m2:
        h_s = m2.group(1) or m2.group(3)
        m_s = m2.group(2) or m2.group(4)
        h, minute = int(h_s), int(m_s)
        if 0 <= h <= 23 and 0 <= minute <= 59:
            cleaned = (text[: m2.start()] + " " + text[m2.end() :]).strip()
            return f"{h:02d}:{minute:02d}", re.sub(r"\s{2,}", " ", cleaned)
    return None, text


def _extract_date(text: str, today: date) -> tuple[str | None, str]:
    m_rel = RELATIVE_DATE_RE.search(text)
    if m_rel:
        word = m_rel.group(1).lower()
        if word.startswith("послезавтра"):
            target = (today + timedelta(days=2)).isoformat()
        elif word.startswith("завтра"):
            target = (today + timedelta(days=1)).isoformat()
        else:
            target = today.isoformat()
        if word in {"сегодня", "завтра", "послезавтра"}:
            cleaned = (text[: m_rel.start()] + " " + text[m_rel.end() :]).strip()
            cleaned = re.sub(r"\s{2,}", " ", cleaned)
        else:
            cleaned = text
        return target, cleaned

    m_num = DATE_DAY_MONTH_RE.search(text)
    if m_num:
        d_val, mo_val = int(m_num.group(1)), int(m_num.group(2))
        y_str = m_num.group(3)
        y_val = int(y_str) + (2000 if y_str and int(y_str) < 100 else 0) if y_str else today.year
        try:
            parsed = date(y_val, mo_val, d_val)
            cleaned = (text[: m_num.start()] + " " + text[m_num.end() :]).strip()
            return parsed.isoformat(), re.sub(r"\s{2,}", " ", cleaned)
        except ValueError:
            pass

    return None, text


def _extract_priority(text: str) -> tuple[int, str]:
    if URGENT_RE.search(text):
        cleaned = URGENT_RE.sub(" ", text)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.;:!-")
        return 1, cleaned or text.strip()
    return 2, text


def _split_chunk_into_clauses(chunk: str) -> list[str]:
    text = chunk.strip()
    if not text:
        return []

    numbered_matches = list(INLINE_NUMBERED_RE.finditer(text))
    if len(numbered_matches) >= 2:
        pieces: list[str] = []
        prefix = text[: numbered_matches[0].start()].strip()
        if prefix:
            pieces.append(prefix)
        for idx, m in enumerate(numbered_matches):
            end_pos = numbered_matches[idx + 1].start() if idx + 1 < len(numbered_matches) else len(text)
            seg = text[m.end() : end_pos].strip()
            if seg:
                pieces.append(seg)
        result: list[str] = []
        for p in pieces:
            result.extend(_split_chunk_into_clauses(p))
        return result

    semicolon_parts = [p.strip() for p in re.split(r"\s*;\s*", text) if p.strip()]
    if len(semicolon_parts) > 1:
        result = []
        for p in semicolon_parts:
            result.extend(_split_chunk_into_clauses(p))
        return result

    sentence_parts = [
        p.strip()
        for p in re.split(r"(?<=[а-яёa-z0-9]{2})[.!?]+\s+(?=[А-ЯЁA-Zа-яёa-z])", text)
        if p.strip()
    ]
    if len(sentence_parts) > 1:
        result = []
        for p in sentence_parts:
            result.extend(_split_chunk_into_clauses(p))
        return result

    conn_parts = [p.strip(" ,") for p in STRONG_CONNECTOR_RE.split(text) if p and p.strip(" ,")]
    if len(conn_parts) > 1:
        result = []
        for p in conn_parts:
            result.extend(_split_chunk_into_clauses(p))
        return result

    comma_parts = [p.strip(" ,") for p in COMMA_VERB_RE.split(text) if p.strip(" ,")]
    if len(comma_parts) > 1:
        result = []
        for p in comma_parts:
            result.extend(_split_chunk_into_clauses(p))
        return result

    and_parts = [p.strip(" ,") for p in AND_VERB_RE.split(text) if p.strip(" ,")]
    if len(and_parts) > 1 and all(len(p.split()) >= 2 for p in and_parts):
        return and_parts

    return [text]


def _clean_title(text: str) -> str:
    cleaned = LEAD_IN_RE.sub("", text.strip()).strip(" ,.;:-—–")
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    if not cleaned:
        return ""
    return cleaned[0].upper() + cleaned[1:]


def split_brain_dump(raw_text: str, *, today: date) -> list[ParsedTaskDraft]:
    """Splits a messy brain-dump message into clean, atomic ParsedTaskDraft objects,
    extracting #tags, deadlines (with auto-urgency <= 3d), recurrence, date, time, and priority."""
    if not raw_text or not raw_text.strip():
        return []

    drafts: list[ParsedTaskDraft] = []
    inherited_date: str | None = None

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        m_hdr = DAY_HEADER_RE.match(line)
        if m_hdr:
            word = m_hdr.group(1).lower()
            if word == "послезавтра":
                inherited_date = (today + timedelta(days=2)).isoformat()
            elif word == "завтра":
                inherited_date = (today + timedelta(days=1)).isoformat()
            else:
                inherited_date = today.isoformat()
            rest = m_hdr.group(2).strip()
            if not rest:
                continue
            line = rest

        clauses = _split_chunk_into_clauses(line)
        for clause in clauses:
            tags, work = _extract_tags(clause)
            recurrence_rule, work = _extract_recurrence(work)
            priority, work = _extract_priority(work)
            planned_time, work = _extract_time(work)
            deadline_date, work = _extract_deadline(work, today)
            planned_date, work = _extract_date(work, today)

            if recurrence_rule and planned_date is None:
                planned_date = today.isoformat()
            elif planned_date is None and inherited_date is not None:
                planned_date = inherited_date

            # Auto-escalate urgency if deadline is <= 3 days away
            if deadline_date:
                try:
                    days_left = (date.fromisoformat(deadline_date) - today).days
                    if days_left <= 3:
                        priority = 1
                except ValueError:
                    pass

            title = _clean_title(work)
            if not title or len(title) < 2:
                continue
            drafts.append(
                ParsedTaskDraft(
                    title=title,
                    planned_date=planned_date,
                    planned_time=planned_time,
                    deadline_date=deadline_date,
                    tags=tags,
                    recurrence_rule=recurrence_rule,
                    priority=priority,
                )
            )

    seen: set[str] = set()
    unique: list[ParsedTaskDraft] = []
    for d in drafts:
        key = d.title.lower()
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return unique
