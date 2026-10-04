"""The snapshot size limit lives in config, not in the schema (BD-34, code review RV-083).

Migration 0003 wrote `CHECK (size_bytes <= 10485760)`, which hard-coded the tunable
`snapshots.max_bytes`. The snapshot store refuses an oversized body before it writes, so
the constraint is dropped.

Revision ID: 0014
Revises: 0013
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE snapshot DROP CONSTRAINT IF EXISTS snapshot_size_bytes_check")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE snapshot ADD CONSTRAINT snapshot_size_bytes_check"
        " CHECK (size_bytes <= 10485760)"
    )
