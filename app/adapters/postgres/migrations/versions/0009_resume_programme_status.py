"""Resume, programme status and the checkpointer's schema (D2-5, BD-14).

`run.resume_attempts`: a run left `running` is resumed once at start-up, never twice.
`relation.programme_status`: the status a supported claim states for a programme (T-06).
Schema `lg` holds LangGraph's checkpoint tables, created by its own setup call (LLD-1 §4).

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE run ADD COLUMN resume_attempts int NOT NULL DEFAULT 0")
    op.execute(
        "ALTER TABLE relation ADD COLUMN programme_status text CHECK (programme_status IN"
        " ('planned','piloting','running','ended','unknown'))"
    )
    op.execute("CREATE SCHEMA IF NOT EXISTS lg")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS lg CASCADE")
    op.execute("ALTER TABLE relation DROP COLUMN programme_status")
    op.execute("ALTER TABLE run DROP COLUMN resume_attempts")
