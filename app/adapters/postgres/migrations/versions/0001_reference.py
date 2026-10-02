"""Reference tables (LLD-1 §4.1).

Revision ID: 0001
Revises:
"""

from alembic import op

from app.adapters.postgres.db import split_sql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

UPGRADE = """
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;

CREATE TABLE ref_country (
  iso2 char(2) PRIMARY KEY, iso3 char(3) NOT NULL UNIQUE,
  name text NOT NULL, languages text[] NOT NULL DEFAULT '{}'
);
CREATE TABLE ref_admin1 (
  country_iso2 char(2) REFERENCES ref_country, admin1_code text, name text NOT NULL,
  PRIMARY KEY (country_iso2, admin1_code)
);
CREATE TABLE ref_place (
  gazetteer_id text PRIMARY KEY, name text NOT NULL, ascii_name text NOT NULL,
  alternate_names text[] NOT NULL DEFAULT '{}',
  country_iso2 char(2) NOT NULL REFERENCES ref_country,
  admin1_code text, admin2_code text, population bigint,
  lat double precision NOT NULL, lon double precision NOT NULL, timezone text
);
CREATE INDEX ref_place_name_trgm ON ref_place USING gin (ascii_name gin_trgm_ops);
CREATE INDEX ref_place_alt_gin ON ref_place USING gin (alternate_names);

CREATE TABLE ref_slot (
  slot_id text PRIMARY KEY, dimension text NOT NULL, question text NOT NULL,
  short_label text NOT NULL,
  answer_kind text NOT NULL CHECK (answer_kind IN ('statistic','relation','statement','mixed')),
  indicator_codes text[] NOT NULL DEFAULT '{}', relation_types text[] NOT NULL DEFAULT '{}',
  headline boolean NOT NULL DEFAULT false, accepted_levels text[] NOT NULL
);
CREATE TABLE ref_indicator (
  code text PRIMARY KEY, name text NOT NULL, comparability_key text NOT NULL, notes text
);
CREATE TABLE ref_source (
  provider text PRIMARY KEY, adapter text NOT NULL, config jsonb NOT NULL
);
"""

DOWNGRADE = """
DROP TABLE ref_source;
DROP TABLE ref_indicator;
DROP TABLE ref_slot;
DROP TABLE ref_place;
DROP TABLE ref_admin1;
DROP TABLE ref_country;
"""


def upgrade() -> None:
    for statement in split_sql(UPGRADE):
        op.execute(statement)


def downgrade() -> None:
    for statement in split_sql(DOWNGRADE):
        op.execute(statement)
