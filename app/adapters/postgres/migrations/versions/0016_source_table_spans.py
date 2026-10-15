"""A source keeps the table positions its chunks were cut by (E-05, BD-56).

Chunking keeps each table whole using the parser's table offsets, which were never
stored, so the chunk collection could not be rebuilt from Postgres exactly. NULL means
the source was stored before this column existed.

Revision ID: 0016
Revises: 0015
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE source ADD COLUMN table_spans jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE source DROP COLUMN table_spans")
