from __future__ import annotations

import logging
from datetime import date, timedelta
from html import escape

from app.db.database import Database
from app.services.history_service import HistoryService
from app.services.parsers.vision_parser import VisionScheduleParser
from app.services.task_service import TaskService
from app.services.time_utils import format_date_ru, format_weekday_short_ru

logger = logging.getLogger(__name__)

REVIEW_SYSTEM_PROMPT = (
    "Ты дружелюбный и лаконичный личный коуч по продуктивности для студента. "
    "Отвечай на русском языке, коротко (6–10 строк), структурированно и без воды. "
    "Подчеркни сильные стороны недели, мягко разбери частые переносы задач и дай 2 конкретных совета на следующую неделю. "
    "Не используй Markdown-заголовки с #, только простой текст и эмодзи."
)


class WeeklyReviewService:
    def __init__(
        self,
        db: Database,
        task_service: TaskService,
        history_service: HistoryService,
        ai_parser: VisionScheduleParser | None = None,
    ) -> None:
        self.db = db
        self.task_service = task_service
        self.history_service = history_service
        self.ai_parser = ai_parser

    async def build_weekly_review_html(self, user_id: int, today_iso: str) -> str:
        stats = await self.history_service.get_period_stats(user_id, today_iso, days=7)
        deadlines = await self.task_service.list_upcoming_deadlines(user_id, today_iso, limit=5)

        # Find most carried-over tasks
        async with self.db.connect() as conn:
            cur = await conn.execute(
                """
                SELECT title, carried_over_count FROM tasks
                WHERE user_id = ? AND status IN ('planned', 'inbox', 'pool') AND carried_over_count > 0
                ORDER BY carried_over_count DESC, id DESC
                LIMIT 5
                """,
                (user_id,),
            )
            chronic = [(r["title"], int(r["carried_over_count"])) for r in await cur.fetchall()]

        pct = round(stats.completion_rate * 100) if stats.total_planned else 0
        best_day = max(
            stats.daily_breakdown,
            key=lambda x: (x[1] / x[2] if x[2] else -1, x[1]),
            default=None,
        )

        header_lines = [
            "🧭 <b>Воскресное ревью недели</b>",
            f"🗓 {format_weekday_short_ru(stats.start_date)} — {format_weekday_short_ru(stats.end_date)}",
            "",
            f"✅ Закрыто: <b>{stats.total_done}</b> из <b>{stats.total_planned}</b> ({pct}%)",
            f"🔥 Текущий стрик: <b>{stats.streak_days} дн.</b>",
        ]
        if best_day and best_day[2] > 0:
            header_lines.append(
                f"🏆 Лучший день: <b>{format_weekday_short_ru(best_day[0])}</b> ({best_day[1]}/{best_day[2]})"
            )

        if chronic:
            header_lines.append("")
            header_lines.append("<b>🔄 Чаще всего откладывалось:</b>")
            for title, cnt in chronic[:3]:
                header_lines.append(f"  • {escape(title)} (↻{cnt})")

        if deadlines:
            today_d = date.fromisoformat(today_iso)
            header_lines.append("")
            header_lines.append("<b>⏳ Дедлайны на горизонте:</b>")
            for dl in deadlines[:4]:
                if dl.deadline_date:
                    diff = (date.fromisoformat(dl.deadline_date) - today_d).days
                    tag = f"через {diff} дн." if diff > 0 else ("сегодня!" if diff == 0 else f"просрочено {-diff} дн.")
                    header_lines.append(f"  • {escape(dl.title)} — <b>{tag}</b>")

        # Try AI-generated personalized coaching summary if AI provider is configured
        ai_comment = ""
        if self.ai_parser and self.ai_parser.is_enabled:
            prompt_lines = [
                f"Период: {stats.start_date} — {stats.end_date}",
                f"Выполнено: {stats.total_done} из {stats.total_planned} ({pct}%), стрик: {stats.streak_days} дн.",
                "По дням: "
                + ", ".join(f"{d}: {done}/{tot}" for d, done, tot in stats.daily_breakdown),
                "Часто переносимые задачи: "
                + (", ".join(f"{t} ({c}x)" for t, c in chronic) if chronic else "нет"),
                "Ближайшие дедлайны: "
                + (", ".join(f"{d.title} (до {d.deadline_date})" for d in deadlines) if deadlines else "нет"),
            ]
            try:
                ai_comment = (
                    await self.ai_parser.generate_text(REVIEW_SYSTEM_PROMPT, "\n".join(prompt_lines))
                ).strip()
            except Exception:
                logger.warning("AI weekly review generation failed, using smart heuristic", exc_info=True)

        header_lines.append("")
        if ai_comment:
            header_lines.append("<b>🤖 Разбор от AI:</b>")
            header_lines.append(escape(ai_comment))
        else:
            header_lines.append("<b>💡 Выводы и фокус на неделю:</b>")
            if stats.total_planned == 0:
                header_lines.append("• На этой неделе задач почти не было — попробуй начать с 2–3 главных дел на завтра.")
            elif pct >= 75:
                header_lines.append("• Отличный темп! Удерживаешь высокий процент выполнения — сохраняй вечерний ритуал.")
            elif pct >= 45:
                header_lines.append("• Хорошая база, но план на день иногда перегружен — ставь 3–4 ключевых дела, остальное держи в Пуле.")
            else:
                header_lines.append("• Нагрузка в плане дня была выше реальной — дроби крупные задачи на подзадачи по 20–30 мин.")
            if chronic:
                header_lines.append(
                    f"• Разбери задачу «{escape(chronic[0][0])}» на 2 маленьких шага или убери в Пул, чтобы не давила."
                )
            if deadlines:
                header_lines.append("• Выдели в расписании свободное окно под ближайший дедлайн заранее.")

        return "\n".join(header_lines)
