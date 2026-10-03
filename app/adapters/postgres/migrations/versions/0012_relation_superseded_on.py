"""The date a superseded relation's edge ends (BD-19, code review RV-030).

The end date of an edge not yet written lived only in the superseding slot's state, so
another slot, or a resumed run, could write the superseded claim's edge as current.
`relation.superseded_on` keeps it in Postgres, and graph writes read it from there.

Revision ID: 0012
Revises: 0011
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE relation ADD COLUMN superseded_on date")


def downgrade() -> None:
    op.execute("ALTER TABLE relation DROP COLUMN superseded_on")
