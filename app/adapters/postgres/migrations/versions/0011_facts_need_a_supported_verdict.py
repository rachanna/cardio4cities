"""A fact needs a supported verdict (BD-18, code review RV-004).

`v_city_facts` showed every supported or contested claim of the latest run. A stop
between storing a verdict and setting the claim's status, followed by a resume that
judged the claim again, could leave a claim supported while its stored verdict said
refuted. The view now also requires the stored verdict to be `supported`, so a claim
whose status and verdict disagree is never shown, whatever wrote it.

Revision ID: 0011
Revises: 0010
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP VIEW v_city_facts")
    op.execute(
        "CREATE VIEW v_city_facts AS SELECT f.* FROM v_fact_evidence f"
        " JOIN city ON city.city_id = f.city_id AND city.latest_run_id = f.run_id"
        " WHERE f.status IN ('supported','contested') AND f.verdict = 'supported'"
    )


def downgrade() -> None:
    op.execute("DROP VIEW v_city_facts")
    op.execute(
        "CREATE VIEW v_city_facts AS SELECT f.* FROM v_fact_evidence f"
        " JOIN city ON city.city_id = f.city_id AND city.latest_run_id = f.run_id"
        " WHERE f.status IN ('supported','contested')"
    )
