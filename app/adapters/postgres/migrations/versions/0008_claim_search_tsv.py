"""Keyword route over claims (CHG-01, LLD-5 §4.1, LLD-1 §4.4).

A plain tsvector column maintained by code, not a generated column: its text combines
the claim with `statistic`, `ref_indicator` and `entity` rows.

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE claim ADD COLUMN search_tsv tsvector")
    op.execute("CREATE INDEX claim_search_tsv_idx ON claim USING gin (search_tsv)")


def downgrade() -> None:
    op.execute("DROP INDEX claim_search_tsv_idx")
    op.execute("ALTER TABLE claim DROP COLUMN search_tsv")
