"""Answers with their conversation turn and retrieval trace (LLD-1 §4.5, LLD-5 §3.2, §10)."""

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class PostgresAnswerRepo:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def add_answer(self, answer: dict[str, Any]) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO answer (answer_id, city_id, run_id, question, question_type,"
                    " body, cited_claim_ids, graph_used, models, conversation_id, turn, trace)"
                    " VALUES (:answer_id, :city_id, :run_id, :question, :question_type,"
                    " CAST(:body AS jsonb), :cited_claim_ids, :graph_used,"
                    " CAST(:models AS jsonb), :conversation_id, :turn, CAST(:trace AS jsonb))"
                ),
                {
                    **answer,
                    "body": json.dumps(answer["body"], default=str),
                    "models": json.dumps(answer["models"], default=str),
                    "trace": json.dumps(answer["trace"], default=str),
                },
            )

    async def last_turn(self, conversation_id: str) -> dict[str, Any] | None:
        """The conversation's latest answer: its city, turn and classification only (the
        answer text is never carried into the next turn, RD-09)."""
        async with self._engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT city_id, turn, trace->'classification' AS classification"
                            " FROM answer WHERE conversation_id = :c ORDER BY turn DESC LIMIT 1"
                        ),
                        {"c": conversation_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row else None

    async def answer_row(self, answer_id: str) -> dict[str, Any] | None:
        async with self._engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text("SELECT * FROM answer WHERE answer_id = :a"), {"a": answer_id}
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row else None
