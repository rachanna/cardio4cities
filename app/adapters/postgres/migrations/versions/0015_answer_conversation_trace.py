"""Answers keep their conversation, turn and retrieval trace (LLD-5 §3.2, §10, §15;
CHG-01; D3-2).

Revision ID: 0015
Revises: 0014
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE answer ADD COLUMN conversation_id text NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE answer ADD COLUMN turn integer NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE answer ADD COLUMN trace jsonb NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE answer ALTER COLUMN conversation_id DROP DEFAULT")
    op.execute("CREATE UNIQUE INDEX answer_conversation_turn ON answer (conversation_id, turn)")


def downgrade() -> None:
    op.execute("DROP INDEX answer_conversation_turn")
    op.execute("ALTER TABLE answer DROP COLUMN trace")
    op.execute("ALTER TABLE answer DROP COLUMN turn")
    op.execute("ALTER TABLE answer DROP COLUMN conversation_id")
