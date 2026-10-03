"""Fixtures for the offline research-run tests (D2-3): the database fixtures and one
research run of slot S04 (`thin_slice`)."""

from tests.contract.conftest import database_url, migrated, relational  # noqa: F401
from tests.support.thin_slice import thin_slice  # noqa: F401
