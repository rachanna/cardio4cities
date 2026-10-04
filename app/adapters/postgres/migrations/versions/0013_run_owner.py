"""Which process owns a run, and when it last said so (BD-25, code review RV-067).

One run at a time held only within a process: during a zero-downtime deploy the new
instance resumed the old instance's live run and ran it twice. A run now records its
owner and a heartbeat; another process takes it over only when the heartbeat is stale,
by an atomic update, and a partial unique index allows one active run in the database.

Revision ID: 0013
Revises: 0012
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE run ADD COLUMN owner text, ADD COLUMN heartbeat_at timestamptz")
    op.execute(
        "CREATE UNIQUE INDEX run_one_active ON run ((true)) WHERE status IN ('queued', 'running')"
    )


def downgrade() -> None:
    op.execute("DROP INDEX run_one_active")
    op.execute("ALTER TABLE run DROP COLUMN owner, DROP COLUMN heartbeat_at")
