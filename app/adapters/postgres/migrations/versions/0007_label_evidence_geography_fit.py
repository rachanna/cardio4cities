"""Label evidence spans and geography fit on claims (BD-10).

Revision ID: 0007
Revises: 0006
"""

from alembic import op

from app.adapters.postgres.db import split_sql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_EVIDENCE = """
CREATE VIEW v_fact_evidence AS
SELECT c.claim_id, c.city_id, c.run_id, c.slot_id, c.kind, c.statement, c.quote, c.quote_lang,
       c.quote_translation, c.span_start, c.span_end, c.geography_level, c.geography_name,
       c.measure_type, c.reference_start, c.reference_end, c.period_type, c.representativeness,
       c.optional_labels, c.flags, c.status, {extra}
       s.value_as_written, s.value_num, s.unit, s.indicator_code, s.comparability_key,
       v.label AS verdict, v.rationale, v.verifier_model, v.fallback_used, v.prompt_version AS checker_prompt,
       src.source_id, src.url, src.title, src.publisher_class, src.published_date, src.retrieved_at,
       src.content_sha256, src.kind AS source_kind
FROM claim c
JOIN source src ON src.source_id = c.source_id
LEFT JOIN statistic s ON s.claim_id = c.claim_id
LEFT JOIN verdict v ON v.claim_id = c.claim_id;

CREATE VIEW v_city_facts AS
SELECT f.* FROM v_fact_evidence f
JOIN city ON city.city_id = f.city_id AND city.latest_run_id = f.run_id
WHERE f.status IN ('supported','contested');
"""

UPGRADE = """
DROP VIEW v_city_facts;
DROP VIEW v_fact_evidence;
-- where each label is stated, when outside the quote: {"period": [start, end], ...}
ALTER TABLE claim ADD COLUMN label_spans jsonb NOT NULL DEFAULT '{}';
-- how the area a figure describes relates to the city: relation, place, distance_km
ALTER TABLE claim ADD COLUMN geography_fit jsonb;
""" + _EVIDENCE.format(extra="c.label_spans, c.geography_fit,")

DOWNGRADE = """
DROP VIEW v_city_facts;
DROP VIEW v_fact_evidence;
ALTER TABLE claim DROP COLUMN geography_fit;
ALTER TABLE claim DROP COLUMN label_spans;
""" + _EVIDENCE.format(extra="")


def upgrade() -> None:
    for statement in split_sql(UPGRADE):
        op.execute(statement)


def downgrade() -> None:
    for statement in split_sql(DOWNGRADE):
        op.execute(statement)
