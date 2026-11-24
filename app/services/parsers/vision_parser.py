from __future__ import annotations

import base64
import json
import re
from datetime import date

import httpx

from app.config import Settings
from app.db.models import ParsedScheduleItem

SYSTEM_PROMPT = """Ты парсер учебного расписания. Извлеки все занятия/события из изображения или текста расписания.
Верни СТРОГО валидный JSON-массив объектов (без пояснений и без markdown) вида:
[
  {
    "event_date": "YYYY-MM-DD",
    "start_time": "HH:MM",
    "end_time": "HH:MM",
    "title": "Название предмета/занятия",
    "location": "Аудитория или ссылка (если есть, иначе пустая строка)",
    "notes": "Преподаватель/тип пары/подгруппа (если есть, иначе пустая строка)"
  }
]
Правила:
- Если указаны дни недели без конкретных дат, привяжи их к ближайшей учебной неделе относительно опорной даты (reference_date).
- Если указан год без столетия или только день.месяц, используй год из reference_date.
- Время всегда в 24-часовом формате HH:MM.
- Пустые слоты без занятий пропускай.
"""


def _extract_json_array(raw_text: str) -> list[dict]:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    data = json.loads(cleaned[start : end + 1])
    return data if isinstance(data, list) else []


def _dicts_to_items(raw_items: list[dict]) -> list[ParsedScheduleItem]:
    items: list[ParsedScheduleItem] = []
    for entry in raw_items:
        if not isinstance(entry, dict):
            continue
        event_date = str(entry.get("event_date", "")).strip()
        start_time = str(entry.get("start_time", "")).strip()
        title = str(entry.get("title", "")).strip()
        if not (event_date and start_time and title):
            continue
        try:
            date.fromisoformat(event_date)
        except ValueError:
            continue
        items.append(
            ParsedScheduleItem(
                event_date=event_date,
                start_time=start_time[:5],
                end_time=str(entry.get("end_time", "")).strip()[:5],
                title=title,
                location=str(entry.get("location", "")).strip(),
                notes=str(entry.get("notes", "")).strip(),
            )
        )
    items.sort(key=lambda x: (x.event_date, x.start_time, x.title))
    return items


class VisionScheduleParser:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def is_enabled(self) -> bool:
        return self.settings.has_vision_configured

    async def parse_image(
        self,
        image_bytes: bytes,
        *,
        mime_type: str = "image/jpeg",
        reference_date: date | None = None,
    ) -> list[ParsedScheduleItem]:
        if not self.is_enabled:
            raise RuntimeError("Vision parser is not configured")
        ref = (reference_date or date.today()).isoformat()
        user_prompt = (
            f"Опорная дата (сегодня): {ref}. "
            "Распознай расписание на изображении и верни JSON-массив."
        )
        if self.settings.vision_provider == "gemini":
            raw = await self._call_gemini(user_prompt, image_bytes=image_bytes, mime_type=mime_type)
        else:
            raw = await self._call_openai(user_prompt, image_bytes=image_bytes, mime_type=mime_type)
        return _dicts_to_items(_extract_json_array(raw))

    async def parse_text(
        self,
        schedule_text: str,
        *,
        reference_date: date | None = None,
    ) -> list[ParsedScheduleItem]:
        if not self.is_enabled:
            raise RuntimeError("Vision parser is not configured")
        ref = (reference_date or date.today()).isoformat()
        user_prompt = (
            f"Опорная дата (сегодня): {ref}.\n"
            f"Текст расписания из документа:\n{schedule_text[:15000]}"
        )
        if self.settings.vision_provider == "gemini":
            raw = await self._call_gemini(user_prompt)
        else:
            raw = await self._call_openai(user_prompt)
        return _dicts_to_items(_extract_json_array(raw))

    async def _call_gemini(
        self,
        prompt: str,
        *,
        image_bytes: bytes | None = None,
        mime_type: str = "image/jpeg",
    ) -> str:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.settings.gemini_model}:generateContent"
        )
        parts: list[dict] = [{"text": f"{SYSTEM_PROMPT}\n\n{prompt}"}]
        if image_bytes is not None:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": mime_type,
                        "data": base64.b64encode(image_bytes).decode("ascii"),
                    }
                }
            )
        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {"temperature": 0.1},
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                url,
                params={"key": self.settings.gemini_api_key},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return "[]"
        content_parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in content_parts)

    async def _call_openai(
        self,
        prompt: str,
        *,
        image_bytes: bytes | None = None,
        mime_type: str = "image/jpeg",
    ) -> str:
        url = f"{self.settings.openai_base_url.rstrip('/')}/chat/completions"
        user_content: list[dict] = [{"type": "text", "text": prompt}]
        if image_bytes is not None:
            b64 = base64.b64encode(image_bytes).decode("ascii")
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                }
            )
        payload = {
            "model": self.settings.openai_model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        }
        headers = {"Authorization": f"Bearer {self.settings.openai_api_key}"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            return "[]"
        return choices[0].get("message", {}).get("content", "[]")
