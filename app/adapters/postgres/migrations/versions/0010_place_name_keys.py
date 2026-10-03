"""Place name keys for geography fit (BD-17, code review RV-002).

`ref_place.name_keys` holds the normalised keys (`app.domain.place_names.place_key`) of a
place's name, ASCII name and alternate names. Claims' area names are normalised by the
same function, so the lookup compares like with like ("St. Ostra" is "st ostra" on both
sides). The gazetteer sync fills the column; the next reference load backfills it.

Revision ID: 0010
Revises: 0009
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ref_place ADD COLUMN name_keys text[] NOT NULL DEFAULT '{}'")
    op.execute("CREATE INDEX ref_place_name_keys_gin ON ref_place USING gin (name_keys)")


def downgrade() -> None:
    op.execute("DROP INDEX ref_place_name_keys_gin")
    op.execute("ALTER TABLE ref_place DROP COLUMN name_keys")
