"""Cities, runs, events (LLD-1 §4.2).

Revision ID: 0002
Revises: 0001
"""

from alembic import op

from app.adapters.postgres.db import split_sql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE city (
  city_id text PRIMARY KEY,
  gazetteer_id text NOT NULL UNIQUE REFERENCES ref_place,
  identity jsonb NOT NULL,
  latest_run_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE run (
  run_id text PRIMARY KEY,
  city_id text NOT NULL REFERENCES city,
  status text NOT NULL CHECK (status IN ('queued','running','completed','stopped_by_budget','failed')),
  started_at timestamptz, finished_at timestamptz,
  budget jsonb NOT NULL,
  versions jsonb NOT NULL,
  error text
);
CREATE INDEX run_city_idx ON run (city_id, started_at DESC);
ALTER TABLE city ADD CONSTRAINT city_latest_run_fk FOREIGN KEY (latest_run_id) REFERENCES run;

CREATE TABLE run_event (
  run_id text NOT NULL REFERENCES run,
  seq bigint NOT NULL,
  event_id text NOT NULL UNIQUE,
  type text NOT NULL,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (run_id, seq)
);

CREATE TABLE run_seq (
  run_id text PRIMARY KEY REFERENCES run,
  next_seq bigint NOT NULL DEFAULT 1
);

CREATE TABLE run_summary (
  run_id text PRIMARY KEY REFERENCES run,
  summary jsonb NOT NULL
);

CREATE TABLE slot_result (
  run_id text NOT NULL REFERENCES run,
  slot_id text NOT NULL REFERENCES ref_slot,
  status text NOT NULL CHECK (status IN ('answered','answered_wider_geo','answered_negative','blocked','unreachable')),
  flags text[] NOT NULL DEFAULT '{}',
  replans_used int NOT NULL DEFAULT 0,
  queries_tried text[] NOT NULL DEFAULT '{}',
  sources_checked text[] NOT NULL DEFAULT '{}',
  best_claim_ids text[] NOT NULL DEFAULT '{}',
  gap_note text,
  PRIMARY KEY (run_id, slot_id)
);
"""

DOWNGRADE = """
DROP TABLE slot_result;
DROP TABLE run_summary;
DROP TABLE run_seq;
DROP TABLE run_event;
ALTER TABLE city DROP CONSTRAINT city_latest_run_fk;
DROP TABLE run;
DROP TABLE city;
"""


def upgrade() -> None:
    for statement in split_sql(UPGRADE):
        op.execute(statement)


def downgrade() -> None:
    for statement in split_sql(DOWNGRADE):
        op.execute(statement)
