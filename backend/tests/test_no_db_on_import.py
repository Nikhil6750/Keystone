"""Verifies that importing the application does not create the production SQLite file."""

from pathlib import Path


def test_importing_app_does_not_create_database_file() -> None:
    """`app.main` is imported by other test modules at collection time; by the time
    this test runs, that import must not have created `keystone.db` in the working
    directory (tables are only created via `initialize_database()`, which only runs
    inside the FastAPI lifespan on actual server startup).
    """
    assert not Path("keystone.db").exists()
