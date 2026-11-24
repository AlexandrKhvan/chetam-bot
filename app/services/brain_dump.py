from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(slots=True)
class ParsedTaskDraft:
    title: str
    planned_date: str | None = None
    planned_time: str | None = None
    priority: int = 2


# Common Russian action verbs (infinitive & imperative) used to detect clause boundaries
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

# Explicit strong connectors between tasks inside a single run-on message
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

# Numbered inline list items: "1) ...", "2. ..."
INLINE_NUMBERED_RE = re.compile(r"(?:^|\s)(\d{1,2})[.)]\s+")

# Comma or "и" followed directly by a known action verb or infinitive phrase
COMMA_VERB_RE = re.compile(
    rf",\s+(?=(?:(?:не\s+забыть|надо|нужно|срочно|важно|сегодня|завтра|послезавтра)\s+)?(?:{ACTION_VERB_PATTERN})\b)",
    re.IGNORECASE,
)
AND_VERB_RE = re.compile(
    rf"\s+и\s+(?=(?:(?:не\s+забыть|надо|нужно|срочно|важно|сегодня|завтра|послезавтра)\s+)?(?:{ACTION_VERB_PATTERN})\b)",
    re.IGNORECASE,
)

# Lead-in filler words to strip cleanly from the start of each extracted task
LEAD_IN_RE = re.compile(
    r"^(?:[-•*—–]+\s*|\d{1,2}[.)]\s*|"
    r"(?:ну|короче|типа|кстати|вообще|потом|затем|ещ[её]|также|плюс|заодно|"
    r"а|и|но|да|надо\s+бы|надо|нужно|необходимо|хочу|не\s+забыть|не\s+забудь|напомни)\b[\s,:;-]*)+",
    re.IGNORECASE,
)

URGENT_RE = re.compile(r"(?:^|\s)(срочно|важно|критично|asap|urgent)(?=\s|$|[!.,:;])|!{2,}", re.IGNORECASE)
TIME_WITH_PREP_RE = re.compile(r"\b(?:в|к|на|at)\s*(\d{1,2})[:.](\d{2})\b", re.IGNORECASE)
BARE_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})\b|\b(\d{1,2}):(\d{2})$")
DATE_DAY_MONTH_RE = re.compile(r"\b(?:на\s+)?(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b")

DAY_HEADER_RE = re.compile(r"^(сегодня|завтра|послезавтра)\s*[:—–-]\s*(.*)$", re.IGNORECASE)
RELATIVE_DATE_RE = re.compile(
    r"\b(?:на\s+)?(послезавтра|завтра|сегодня|завтрашн\w*|сегодняшн\w*)\b",
    re.IGNORECASE,
)


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
        # Only remove standalone "сегодня"/"завтра"/"послезавтра", keep adjectives like "к завтрашнему семинару"
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

    # 1. Split inline numbered lists: "1) foo 2) bar"
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

    # 2. Split on semicolons
    semicolon_parts = [p.strip() for p in re.split(r"\s*;\s*", text) if p.strip()]
    if len(semicolon_parts) > 1:
        result = []
        for p in semicolon_parts:
            result.extend(_split_chunk_into_clauses(p))
        return result

    # 3. Split on sentence boundaries (period/exclamation/question followed by a new clause)
    # Avoid splitting numeric dates like "25.11" or initials like "А.Б."
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

    # 4. Split on strong Russian connectors ("потом", "ещё", "также", "и надо", "не забыть"...)
    conn_parts = [p.strip(" ,") for p in STRONG_CONNECTOR_RE.split(text) if p and p.strip(" ,")]
    if len(conn_parts) > 1:
        result = []
        for p in conn_parts:
            result.extend(_split_chunk_into_clauses(p))
        return result

    # 5. Split on ", <action_verb>" or " и <action_verb>" when both sides are meaningful
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
    extracting date, time, and urgency hints along the way."""
    if not raw_text or not raw_text.strip():
        return []

    drafts: list[ParsedTaskDraft] = []
    inherited_date: str | None = None

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Support section headers like "Сегодня:" or "Завтра: сделать X, купить Y"
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
            priority, work = _extract_priority(clause)
            planned_time, work = _extract_time(work)
            planned_date, work = _extract_date(work, today)
            if planned_date is None and inherited_date is not None:
                planned_date = inherited_date

            title = _clean_title(work)
            if not title or len(title) < 2:
                continue
            drafts.append(
                ParsedTaskDraft(
                    title=title,
                    planned_date=planned_date,
                    planned_time=planned_time,
                    priority=priority,
                )
            )

    # Deduplicate exact duplicates while preserving order
    seen: set[str] = set()
    unique: list[ParsedTaskDraft] = []
    for d in drafts:
        key = d.title.lower()
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return unique
