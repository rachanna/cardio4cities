"""Searches, claims, statistics and verdicts of a run (LLD-1 §4.3-4.4)."""

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.domain.models import Claim, Statistic, Verdict


class PostgresResearchRepo:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def add_search(
        self,
        query_id: str,
        run_id: str,
        slot_id: str,
        query: str,
        lang: str,
        provider: str,
        result_count: int,
        round_no: int,
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO search_query (query_id, run_id, slot_id, query, lang, provider,"
                    " result_count, replan_round) VALUES (:q, :r, :s, :t, :l, :p, :n, :rr)"
                ),
                {
                    "q": query_id,
                    "r": run_id,
                    "s": slot_id,
                    "t": query,
                    "l": lang,
                    "p": provider,
                    "n": result_count,
                    "rr": round_no,
                },
            )

    async def add_claim(self, claim: Claim, statistic: Statistic | None) -> None:
        labels = claim.labels
        optional = {
            k: v
            for k, v in labels.model_dump(mode="json").items()
            if k
            in (
                "population_age_min",
                "population_age_max",
                "population_sex",
                "population_group",
                "setting",
                "sample_size",
                "case_definition",
                "threshold_code",
                "method",
                "denominator_text",
                "denominator_stated",
            )
        }
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO claim (claim_id, run_id, city_id, slot_id, source_id, kind,"
                    " statement, quote, quote_lang, quote_translation, span_start, span_end,"
                    " geography_level, geography_name, measure_type, reference_start,"
                    " reference_end, reference_precision, period_type, representativeness,"
                    " optional_labels, flags, status, extractor_model, prompt_version,"
                    " label_spans, geography_fit) VALUES"
                    " (:claim_id, :run_id, :city_id, :slot_id, :source_id, :kind, :statement,"
                    " :quote, :quote_lang, :quote_translation, :span_start, :span_end,"
                    " :geography_level, :geography_name, :measure_type, :reference_start,"
                    " :reference_end, :reference_precision, :period_type, :representativeness,"
                    " :optional_labels, :flags, :status, :extractor_model, :prompt_version,"
                    " :label_spans, :geography_fit)"
                ),
                {
                    "claim_id": claim.claim_id,
                    "run_id": claim.run_id,
                    "city_id": claim.city_id,
                    "slot_id": claim.slot_id,
                    "source_id": claim.source_id,
                    "kind": claim.kind.value,
                    "statement": claim.statement,
                    "quote": claim.quote,
                    "quote_lang": claim.quote_lang,
                    "quote_translation": claim.quote_translation,
                    "span_start": claim.span_start,
                    "span_end": claim.span_end,
                    "geography_level": labels.geography_level.value,
                    "geography_name": labels.geography_name,
                    "measure_type": labels.measure_type.value,
                    "reference_start": labels.reference_start,
                    "reference_end": labels.reference_end,
                    "reference_precision": labels.reference_precision.value
                    if labels.reference_precision
                    else None,
                    "period_type": labels.period_type.value,
                    "representativeness": labels.representativeness.value,
                    "optional_labels": json.dumps(optional),
                    "flags": sorted(f.value for f in claim.flags),
                    "status": claim.status.value,
                    "extractor_model": claim.extractor_model,
                    "prompt_version": claim.prompt_version,
                    "label_spans": json.dumps({k: list(v) for k, v in claim.label_spans.items()}),
                    "geography_fit": claim.geography_fit.model_dump_json()
                    if claim.geography_fit
                    else None,
                },
            )
            if statistic is not None:
                await conn.execute(
                    text(
                        "INSERT INTO statistic (claim_id, indicator_code, value_as_written,"
                        " value_num, unit, lower, upper, comparability_key) VALUES (:c, :i, :w,"
                        " :n, :u, :lo, :hi, :k)"
                    ),
                    {
                        "c": statistic.claim_id,
                        "i": statistic.indicator_code,
                        "w": statistic.value_as_written,
                        "n": statistic.value_num,
                        "u": statistic.unit,
                        "lo": statistic.lower,
                        "hi": statistic.upper,
                        "k": None,
                    },
                )

    async def set_claim_status(self, claim_id: str, status: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text("UPDATE claim SET status = :s WHERE claim_id = :c"),
                {"s": status, "c": claim_id},
            )

    async def set_comparability_key(self, claim_id: str, key: str | None) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text("UPDATE statistic SET comparability_key = :k WHERE claim_id = :c"),
                {"k": key, "c": claim_id},
            )

    async def add_verdict(self, verdict: Verdict) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO verdict (claim_id, label, rationale, scope_verified,"
                    " period_verified, verifier_model, verifier_family, fallback_used,"
                    " prompt_version) VALUES (:claim_id, :label, :rationale, :scope_verified,"
                    " :period_verified, :verifier_model, :verifier_family, :fallback_used,"
                    " :prompt_version)"
                ),
                verdict.model_dump(mode="json"),
            )

    async def claim_statuses(self, run_id: str) -> dict[str, int]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT status, count(*) AS n FROM claim WHERE run_id = :r GROUP BY status"),
                {"r": run_id},
            )
            return {r.status: int(r.n) for r in rows}

    async def evidence(self, claim_id: str) -> dict[str, Any] | None:
        """One row of v_fact_evidence (LLD-1 §4.6) for a claim."""
        async with self._engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text("SELECT * FROM v_fact_evidence WHERE claim_id = :c"), {"c": claim_id}
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row else None

    async def claim_with_statistic(self, claim_id: str) -> tuple[Claim, Statistic | None]:
        async with self._engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT c.*, s.indicator_code, s.value_as_written, s.value_num, s.unit,"
                            " s.lower, s.upper FROM claim c LEFT JOIN statistic s USING (claim_id)"
                            " WHERE c.claim_id = :c"
                        ),
                        {"c": claim_id},
                    )
                )
                .mappings()
                .one()
            )
        labels = {
            "geography_level": row["geography_level"],
            "geography_name": row["geography_name"],
            "measure_type": row["measure_type"],
            "reference_start": row["reference_start"],
            "reference_end": row["reference_end"],
            "reference_precision": row["reference_precision"],
            "period_type": row["period_type"],
            "representativeness": row["representativeness"],
            **row["optional_labels"],
        }
        claim = Claim.model_validate(
            {
                **{
                    k: row[k]
                    for k in (
                        "claim_id",
                        "run_id",
                        "city_id",
                        "slot_id",
                        "source_id",
                        "kind",
                        "statement",
                        "quote",
                        "quote_lang",
                        "quote_translation",
                        "span_start",
                        "span_end",
                        "status",
                        "extractor_model",
                        "prompt_version",
                    )
                },
                "labels": labels,
                "flags": frozenset(row["flags"]),
                "label_spans": {k: tuple(v) for k, v in row["label_spans"].items()},
                "geography_fit": row["geography_fit"],
            }
        )
        statistic = None
        if row["indicator_code"] is not None:
            statistic = Statistic(
                claim_id=claim_id,
                indicator_code=row["indicator_code"],
                value_as_written=row["value_as_written"],
                value_num=row["value_num"],
                unit=row["unit"],
                lower=row["lower"],
                upper=row["upper"],
            )
        return claim, statistic

    async def add_contested_pair(
        self, pair_id: str, claim_a: str, claim_b: str, headline: str, reason: str
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO contested_pair (pair_id, claim_a, claim_b, headline_claim, reason)"
                    " VALUES (:p, :a, :b, :h, :r) ON CONFLICT (claim_a, claim_b) DO NOTHING"
                ),
                {"p": pair_id, "a": claim_a, "b": claim_b, "h": headline, "r": reason},
            )
