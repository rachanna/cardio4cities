"""Search, crawl, sources, snapshots (LLD-1 §4.3).

Revision ID: 0003
Revises: 0002
"""

from alembic import op

from app.adapters.postgres.db import split_sql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE search_query (
  query_id text PRIMARY KEY, run_id text NOT NULL REFERENCES run,
  slot_id text NOT NULL REFERENCES ref_slot, query text NOT NULL, lang text NOT NULL,
  provider text NOT NULL, result_count int NOT NULL, replan_round int NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE crawl_decision (
  decision_id text PRIMARY KEY, run_id text NOT NULL REFERENCES run,
  url text NOT NULL, domain text NOT NULL,
  outcome text NOT NULL CHECK (outcome IN ('allowed','blocked_robots','blocked_content_usage',
    'blocked_login_or_paywall','blocked_private_address','unreachable_network',
    'unreachable_server_error','rate_limited')),
  rule text, reason text NOT NULL, robots_http_status int,
  decided_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX crawl_decision_run_idx ON crawl_decision (run_id, outcome);

CREATE TABLE source (
  source_id text PRIMARY KEY, run_id text NOT NULL REFERENCES run,
  url text NOT NULL, url_canonical text NOT NULL, domain text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('web_html','web_pdf','structured_api')),
  publisher_class text NOT NULL CHECK (publisher_class IN ('government','multilateral','academic','ngo','news','other')),
  title text, language text,
  published_date date, published_precision text,
  retrieved_at timestamptz NOT NULL, http_status int, content_type text,
  content_sha256 text, size_bytes int,
  parse_outcome text CHECK (parse_outcome IN ('parsed','unreadable','too_large','unsupported_type')),
  parsed_text text,
  found_via text NOT NULL,
  crawl_decision_id text REFERENCES crawl_decision,
  UNIQUE (run_id, url_canonical)
);

CREATE TABLE snapshot (
  source_id text PRIMARY KEY REFERENCES source,
  content_gz bytea NOT NULL,
  content_type text, sha256 text NOT NULL, size_bytes int NOT NULL,
  stored_at timestamptz NOT NULL DEFAULT now(),
  CHECK (size_bytes <= 10485760)
);
"""

DOWNGRADE = """
DROP TABLE snapshot;
DROP TABLE source;
DROP TABLE crawl_decision;
DROP TABLE search_query;
"""


def upgrade() -> None:
    for statement in split_sql(UPGRADE):
        op.execute(statement)


def downgrade() -> None:
    for statement in split_sql(DOWNGRADE):
        op.execute(statement)
