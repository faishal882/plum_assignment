from collections.abc import Iterator
from os import environ

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


@pytest.fixture(scope="session")
def postgres_database_url() -> Iterator[str]:
    database_url = environ.get(
        "CLAIMS_TEST_DATABASE_URL",
        "postgresql+psycopg://claims:claims@127.0.0.1:55432/claims",
    )
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    yield database_url


@pytest.fixture
def migrated_database_url(postgres_database_url: str) -> Iterator[str]:
    engine = create_engine(postgres_database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE claim_work_items, audit_events, claim_versions, claims "
                "RESTART IDENTITY CASCADE"
            )
        )
    yield postgres_database_url
    engine.dispose()
