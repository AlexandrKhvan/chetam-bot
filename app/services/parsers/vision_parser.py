from __future__ import annotations

import asyncio
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
    "notes": "Преподаватель/тип пары/подгруппа (если есть, иначе пустая строка)",
    "meeting_info": "Zoom ID/пароль или ссылка на онлайн-встречу (если есть, иначе пустая строка)",
    "group_tag": "Код группы если их несколько (например ВМ-21), иначе пустая строка"
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
                meeting_info=str(entry.get("meeting_info", "")).strip(),
                group_tag=str(entry.get("group_tag", "")).strip().upper(),
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

    @property
    def voice_enabled(self) -> bool:
        return self.settings.has_voice_configured

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
        raw = await self._invoke_model(
            SYSTEM_PROMPT, user_prompt, image_bytes=image_bytes, mime_type=mime_type
        )
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
        raw = await self._invoke_model(SYSTEM_PROMPT, user_prompt)
        return _dicts_to_items(_extract_json_array(raw))

    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        if not self.is_enabled:
            raise RuntimeError("AI provider is not configured")
        return await self._invoke_model(system_prompt, user_prompt)

    async def transcribe_audio(
        self, audio_bytes: bytes, *, mime_type: str = "audio/ogg", filename: str = "voice.ogg"
    ) -> str:
        """Transcribes voice note audio into clean Russian/English text using Gemini or OpenAI Whisper."""
        if self.settings.gemini_api_key.strip():
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self.settings.gemini_model}:generateContent"
            )
            payload = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": (
                                    "Точно расшифруй голосовое сообщение на языке оригинала (обычно русский). "
                                    "Верни только текст расшифровки без пояснений."
                                )
                            },
                            {
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": base64.b64encode(audio_bytes).decode("ascii"),
                                }
                            },
                        ]
                    }
                ],
                "generationConfig": {"temperature": 0.0},
            }
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    url, params={"key": self.settings.gemini_api_key}, json=payload
                )
                resp.raise_for_status()
                data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return ""
            parts = candidates[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts).strip()

        if self.settings.openai_api_key.strip():
            url = f"{self.settings.openai_base_url.rstrip('/')}/audio/transcriptions"
            headers = {"Authorization": f"Bearer {self.settings.openai_api_key}"}
            files = {"file": (filename, audio_bytes, mime_type)}
            form_data = {"model": "whisper-1", "language": "ru"}
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, headers=headers, files=files, data=form_data)
                resp.raise_for_status()
                return str(resp.json().get("text", "")).strip()

        raise RuntimeError("Voice transcription provider is not configured")

    async def _invoke_model(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        image_bytes: bytes | None = None,
        mime_type: str = "image/jpeg",
    ) -> str:
        if self.settings.vision_provider == "gemini":
            return await self._call_gemini(
                system_prompt, user_prompt, image_bytes=image_bytes, mime_type=mime_type
            )
        if self.settings.vision_provider == "bedrock":
            return await self._call_bedrock(
                system_prompt, user_prompt, image_bytes=image_bytes, mime_type=mime_type
            )
        return await self._call_openai(
            system_prompt, user_prompt, image_bytes=image_bytes, mime_type=mime_type
        )

    async def _call_gemini(
        self,
        system_prompt: str,
        prompt: str,
        *,
        image_bytes: bytes | None = None,
        mime_type: str = "image/jpeg",
    ) -> str:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.settings.gemini_model}:generateContent"
        )
        parts: list[dict] = [{"text": f"{system_prompt}\n\n{prompt}"}]
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
            return ""
        content_parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in content_parts)

    async def _call_openai(
        self,
        system_prompt: str,
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
                {"role": "system", "content": system_prompt},
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
            return ""
        return choices[0].get("message", {}).get("content", "")

    async def _call_bedrock(
        self,
        system_prompt: str,
        prompt: str,
        *,
        image_bytes: bytes | None = None,
        mime_type: str = "image/jpeg",
    ) -> str:
        def _sync_converse() -> str:
            import boto3

            client = boto3.client("bedrock-runtime", region_name=self.settings.aws_region)
            content: list[dict] = [{"text": prompt}]
            if image_bytes is not None:
                fmt = "png" if "png" in mime_type else ("webp" if "webp" in mime_type else "jpeg")
                content.append({"image": {"format": fmt, "source": {"bytes": image_bytes}}})
            resp = client.converse(
                modelId=self.settings.bedrock_model_id,
                system=[{"text": system_prompt}],
                messages=[{"role": "user", "content": content}],
                inferenceConfig={"temperature": 0.1, "maxTokens": 2500},
            )
            blocks = resp.get("output", {}).get("message", {}).get("content", [])
            return "".join(b.get("text", "") for b in blocks if "text" in b)

        return await asyncio.to_thread(_sync_converse)
