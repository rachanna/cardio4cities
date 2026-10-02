"""Claims and their details (LLD-1 §4.4).

Revision ID: 0004
Revises: 0003
"""

from alembic import op

from app.adapters.postgres.db import split_sql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE claim (
  claim_id text PRIMARY KEY, run_id text NOT NULL REFERENCES run,
  city_id text NOT NULL REFERENCES city, slot_id text NOT NULL REFERENCES ref_slot,
  source_id text NOT NULL REFERENCES source,
  kind text NOT NULL CHECK (kind IN ('statistic','relation','statement')),
  statement text NOT NULL, quote text NOT NULL,
  quote_lang text NOT NULL, quote_translation text,
  span_start int NOT NULL, span_end int NOT NULL CHECK (span_end > span_start),
  geography_level text NOT NULL CHECK (geography_level IN ('city_wide','sub_city_area','sub_city_population',
    'metro_region','district','state_province','national','global')),
  geography_name text NOT NULL,
  measure_type text NOT NULL,
  reference_start date, reference_end date, reference_precision text,
  period_type text NOT NULL CHECK (period_type IN ('point_in_time','period','cumulative','publication_date_proxy')),
  representativeness text NOT NULL,
  optional_labels jsonb NOT NULL DEFAULT '{}',
  flags text[] NOT NULL DEFAULT '{}',
  status text NOT NULL CHECK (status IN ('extracted','dropped','supported','refuted','insufficient','contested','superseded')),
  extractor_model text NOT NULL, prompt_version text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX claim_city_slot_idx ON claim (city_id, slot_id, status);
CREATE INDEX claim_run_idx ON claim (run_id);

CREATE TABLE statistic (
  claim_id text PRIMARY KEY REFERENCES claim,
  indicator_code text NOT NULL REFERENCES ref_indicator,
  value_as_written text NOT NULL, value_num numeric, unit text,
  lower numeric, upper numeric,
  comparability_key text
);
CREATE INDEX statistic_cmp_idx ON statistic (comparability_key);

CREATE TABLE entity (
  entity_id text PRIMARY KEY, city_id text NOT NULL REFERENCES city,
  entity_type text NOT NULL CHECK (entity_type IN ('Place','Organization','Person','Programme','Policy','Indicator')),
  canonical_name text NOT NULL, normalized_key text NOT NULL,
  graph_uuid uuid NOT NULL UNIQUE,
  attributes jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (city_id, entity_type, normalized_key)
);
CREATE TABLE entity_alias (
  city_id text NOT NULL REFERENCES city, surface_form text NOT NULL,
  entity_id text NOT NULL REFERENCES entity,
  method text NOT NULL CHECK (method IN ('exact','normalized','acronym','embedding','model','human')),
  score real, created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (city_id, surface_form)
);

CREATE TABLE relation (
  claim_id text PRIMARY KEY REFERENCES claim,
  subject_entity_id text NOT NULL REFERENCES entity,
  relation_type text NOT NULL,
  object_entity_id text NOT NULL REFERENCES entity,
  valid_from date, valid_to date, valid_from_is_proxy boolean NOT NULL DEFAULT false
);

CREATE TABLE verdict (
  claim_id text PRIMARY KEY REFERENCES claim,
  label text NOT NULL CHECK (label IN ('supported','refuted','insufficient')),
  rationale text NOT NULL CHECK (length(rationale) <= 400),
  scope_verified boolean NOT NULL, period_verified boolean NOT NULL,
  verifier_model text NOT NULL, verifier_family text NOT NULL,
  fallback_used boolean NOT NULL DEFAULT false, prompt_version text NOT NULL,
  checked_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE consistency (
  claim_id text PRIMARY KEY REFERENCES claim,
  outcome text NOT NULL CHECK (outcome IN ('agrees','novel','conflicts','not_comparable')),
  compared_with text[] NOT NULL DEFAULT '{}', reason text NOT NULL
);

CREATE TABLE contested_pair (
  pair_id text PRIMARY KEY, claim_a text NOT NULL REFERENCES claim, claim_b text NOT NULL REFERENCES claim,
  headline_claim text NOT NULL REFERENCES claim,
  reason text NOT NULL,
  review_status text NOT NULL DEFAULT 'open' CHECK (review_status IN ('open','resolved')),
  resolution_note text,
  CHECK (claim_a < claim_b), UNIQUE (claim_a, claim_b)
);

CREATE TABLE graph_link (
  claim_id text NOT NULL REFERENCES claim,
  edge_uuid uuid NOT NULL, written_at timestamptz NOT NULL DEFAULT now(),
  invalidated_at timestamptz,
  PRIMARY KEY (claim_id, edge_uuid)
);
"""

DOWNGRADE = """
DROP TABLE graph_link;
DROP TABLE contested_pair;
DROP TABLE consistency;
DROP TABLE verdict;
DROP TABLE relation;
DROP TABLE entity_alias;
DROP TABLE entity;
DROP TABLE statistic;
DROP TABLE claim;
"""


def upgrade() -> None:
    for statement in split_sql(UPGRADE):
        op.execute(statement)


def downgrade() -> None:
    for statement in split_sql(DOWNGRADE):
        op.execute(statement)
