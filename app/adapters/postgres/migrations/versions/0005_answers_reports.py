"""Answers and reports (LLD-1 §4.5).

Revision ID: 0005
Revises: 0004
"""

from alembic import op

from app.adapters.postgres.db import split_sql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE answer (
  answer_id text PRIMARY KEY, city_id text NOT NULL REFERENCES city,
  run_id text NOT NULL REFERENCES run,
  question text NOT NULL, question_type text NOT NULL,
  body jsonb NOT NULL,
  cited_claim_ids text[] NOT NULL DEFAULT '{}',
  graph_used boolean NOT NULL, models jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE report (
  report_id text PRIMARY KEY, city_id text NOT NULL REFERENCES city,
  run_id text NOT NULL REFERENCES run, format text NOT NULL CHECK (format IN ('md','html','pdf')),
  content bytea NOT NULL, sha256 text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
"""

DOWNGRADE = """
DROP TABLE report;
DROP TABLE answer;
"""


def upgrade() -> None:
    for statement in split_sql(UPGRADE):
        op.execute(statement)


def downgrade() -> None:
    for statement in split_sql(DOWNGRADE):
        op.execute(statement)
