"""Searches, claims, statistics and verdicts of a run (LLD-1 §4.3-4.4)."""

import json
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.domain.models import Claim, Relation, Statistic, Verdict


def _claim(row: Any) -> Claim:
    """A claim row (with its label columns) as the domain model."""
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
    return Claim.model_validate(
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
                    " ON CONFLICT (query_id) DO NOTHING"
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

    async def add_claim(
        self, claim: Claim, statistic: Statistic | None, relation: Relation | None = None
    ) -> None:
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
                "population_subgroup",
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
                    " :label_spans, :geography_fit) ON CONFLICT (claim_id) DO NOTHING"
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
                        " :n, :u, :lo, :hi, :k) ON CONFLICT (claim_id) DO NOTHING"
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
            if relation is not None:
                await conn.execute(
                    text(
                        "INSERT INTO relation (claim_id, subject_entity_id, relation_type,"
                        " object_entity_id, valid_from, valid_to, valid_from_is_proxy,"
                        " programme_status) VALUES (:c, :s, :t, :o, :f, :u, :p, :ps)"
                        " ON CONFLICT (claim_id) DO NOTHING"
                    ),
                    {
                        "c": relation.claim_id,
                        "s": relation.subject_entity_id,
                        "t": relation.relation_type.value,
                        "o": relation.object_entity_id,
                        "f": relation.valid_from,
                        "u": relation.valid_to,
                        "p": relation.valid_from_is_proxy,
                        "ps": relation.programme_status.value
                        if relation.programme_status
                        else None,
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

    async def stored_verdict(self, claim_id: str) -> dict[str, Any] | None:
        """The verdict already stored for a claim: label, verifier_model, fallback_used."""
        async with self._engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT label, verifier_model, fallback_used FROM verdict"
                            " WHERE claim_id = :c"
                        ),
                        {"c": claim_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row else None

    async def add_verdict(self, verdict: Verdict) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO verdict (claim_id, label, rationale, scope_verified,"
                    " period_verified, verifier_model, verifier_family, fallback_used,"
                    " prompt_version) VALUES (:claim_id, :label, :rationale, :scope_verified,"
                    " :period_verified, :verifier_model, :verifier_family, :fallback_used,"
                    " :prompt_version) ON CONFLICT (claim_id) DO NOTHING"
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
        claim = _claim(row)
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

    # --- relations and graph links (D2-4, LLD-1 §6.3) ---------------------------------

    async def relation(self, claim_id: str) -> Relation | None:
        async with self._engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text("SELECT * FROM relation WHERE claim_id = :c"), {"c": claim_id}
                    )
                )
                .mappings()
                .one_or_none()
            )
        return Relation.model_validate(dict(row)) if row else None

    async def statistic_claims(self, run_id: str, statuses: list[str]) -> list[str]:
        """Statistic claims of the run with one of `statuses`, every slot and Wave 0."""
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT c.claim_id FROM claim c JOIN statistic s USING (claim_id)"
                    " WHERE c.run_id = :r AND c.status = ANY(:s) ORDER BY c.claim_id"
                ),
                {"r": run_id, "s": statuses},
            )
            return [str(x) for x in rows.scalars()]

    async def record_consistency(
        self, claim_id: str, outcome: str, compared_with: list[str], reason: str
    ) -> None:
        """The latest consistency decision for a claim (LLD-1 §4.4); a later round
        replaces it."""
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO consistency (claim_id, outcome, compared_with, reason)"
                    " VALUES (:c, :o, :w, :r) ON CONFLICT (claim_id) DO UPDATE SET"
                    " outcome = EXCLUDED.outcome, compared_with = EXCLUDED.compared_with,"
                    " reason = EXCLUDED.reason"
                ),
                {"c": claim_id, "o": outcome, "w": compared_with, "r": reason},
            )

    async def set_superseded_on(self, claim_id: str, on: date) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text("UPDATE relation SET superseded_on = :d WHERE claim_id = :c"),
                {"d": on, "c": claim_id},
            )

    async def superseded_live_links(self, run_id: str) -> list[str]:
        """Superseded claims of the run whose graph edge is not yet end-dated."""
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT g.claim_id FROM graph_link g JOIN claim c USING (claim_id)"
                    " WHERE c.run_id = :r AND c.status = 'superseded'"
                    " AND g.invalidated_at IS NULL ORDER BY g.claim_id"
                ),
                {"r": run_id},
            )
            return [str(x) for x in rows.scalars()]

    async def contested_links(self, run_id: str) -> list[str]:
        """Contested claims of the run that have a graph edge."""
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT g.claim_id FROM graph_link g JOIN claim c USING (claim_id)"
                    " WHERE c.run_id = :r AND c.status = 'contested' ORDER BY g.claim_id"
                ),
                {"r": run_id},
            )
            return [str(x) for x in rows.scalars()]

    async def relation_claims(self, run_id: str, statuses: list[str]) -> list[str]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT c.claim_id FROM claim c JOIN relation r USING (claim_id)"
                    " WHERE c.run_id = :r AND c.status = ANY(:s) ORDER BY c.created_at"
                ),
                {"r": run_id, "s": statuses},
            )
            return [str(x) for x in rows.scalars()]

    async def add_graph_link(self, claim_id: str, edge_uuid: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO graph_link (claim_id, edge_uuid) VALUES (:c, :e)"
                    " ON CONFLICT DO NOTHING"
                ),
                {"c": claim_id, "e": edge_uuid},
            )

    async def graph_link(self, claim_id: str) -> str | None:
        async with self._engine.connect() as conn:
            row = await conn.execute(
                text("SELECT edge_uuid FROM graph_link WHERE claim_id = :c LIMIT 1"),
                {"c": claim_id},
            )
            value = row.scalar_one_or_none()
        return str(value) if value else None

    async def invalidate_graph_link(self, claim_id: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE graph_link SET invalidated_at = now()"
                    " WHERE claim_id = :c AND invalidated_at IS NULL"
                ),
                {"c": claim_id},
            )

    async def claims_without_graph_link(self, run_id: str) -> list[str]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT c.claim_id FROM claim c LEFT JOIN statistic s USING (claim_id)"
                    " LEFT JOIN relation r USING (claim_id)"
                    " WHERE c.run_id = :r AND c.status IN ('supported','contested','superseded')"
                    " AND (r.claim_id IS NOT NULL OR (s.indicator_code IS NOT NULL"
                    "      AND s.indicator_code <> 'OTHER'))"
                    " AND NOT EXISTS (SELECT 1 FROM graph_link g WHERE g.claim_id = c.claim_id)"
                    " ORDER BY c.created_at"
                ),
                {"r": run_id},
            )
            return [str(x) for x in rows.scalars()]

    # --- retrieval indexes (CHG-01, LLD-5 §4.1-4.2) -------------------------------------

    async def refresh_search_tsv(self, claim_id: str) -> None:
        """The `simple` configuration: no stemming, no stop words, so acronyms and numbers
        match exactly (RD-07)."""
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE claim c SET search_tsv = to_tsvector('simple', concat_ws(' ',"
                    " c.statement, c.quote_translation,"
                    " (SELECT i.name FROM statistic s"
                    "   JOIN ref_indicator i ON i.code = s.indicator_code"
                    "   WHERE s.claim_id = c.claim_id),"
                    " (SELECT es.canonical_name || ' ' || eo.canonical_name FROM relation r"
                    "   JOIN entity es ON es.entity_id = r.subject_entity_id"
                    "   JOIN entity eo ON eo.entity_id = r.object_entity_id"
                    "   WHERE r.claim_id = c.claim_id)))"
                    " WHERE c.claim_id = :c"
                ),
                {"c": claim_id},
            )

    async def claim_index_row(self, claim_id: str) -> dict[str, Any] | None:
        async with self._engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT c.claim_id, c.city_id, c.run_id, c.slot_id, c.kind, c.status,"
                            " c.geography_level, c.statement, c.quote, c.quote_translation,"
                            " c.reference_end, s.indicator_code"
                            " FROM claim c LEFT JOIN statistic s USING (claim_id)"
                            " WHERE c.claim_id = :c"
                        ),
                        {"c": claim_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row else None

    # --- coverage (D2-5, LLD-2 §11) -----------------------------------------------------

    async def slot_claims(self, run_id: str, slot_id: str) -> list[tuple[Claim, str]]:
        """Every claim row of the slot in the run, with its source's publisher class."""
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT c.*, so.publisher_class AS source_class FROM claim c"
                    " JOIN source so USING (source_id)"
                    " WHERE c.run_id = :r AND c.slot_id = :s ORDER BY c.claim_id"
                ),
                {"r": run_id, "s": slot_id},
            )
            return [(_claim(r), str(r["source_class"])) for r in rows.mappings()]

    async def contested_claim_ids(self, run_id: str) -> set[str]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT p.claim_a, p.claim_b FROM contested_pair p"
                    " JOIN claim c ON c.claim_id = p.claim_a WHERE c.run_id = :r"
                ),
                {"r": run_id},
            )
            return {c for r in rows for c in (r.claim_a, r.claim_b)}

    async def queries(self, query_ids: list[str]) -> list[tuple[str, str]]:
        """(text, language) of the given searches, in the order given."""
        if not query_ids:
            return []
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT query_id, query, lang FROM search_query WHERE query_id = ANY(:ids)"),
                {"ids": query_ids},
            )
            found = {r.query_id: (r.query, r.lang) for r in rows}
        return [found[q] for q in query_ids if q in found]
