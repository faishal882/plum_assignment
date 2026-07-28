import pytest

from claims_backend.testing import UnsafeTestDatabaseError, assert_safe_test_database


def test_same_database_is_rejected_without_explicit_override() -> None:
    with pytest.raises(UnsafeTestDatabaseError, match="CLAIMS_TEST_DATABASE_URL"):
        assert_safe_test_database(
            "postgresql+psycopg://claims:claims@localhost:55432/claims",
            "postgresql+psycopg://claims:claims@localhost:55432/claims",
            allow_destructive_override=False,
        )


def test_same_database_requires_explicit_destructive_override() -> None:
    assert_safe_test_database(
        "postgresql+psycopg://claims:claims@localhost:55432/claims",
        "postgresql+psycopg://claims:claims@localhost:55432/claims",
        allow_destructive_override=True,
    )


def test_distinct_database_is_safe() -> None:
    assert_safe_test_database(
        "postgresql+psycopg://claims:claims@localhost:55432/claims",
        "postgresql+psycopg://claims:claims@localhost:55432/claims_test",
        allow_destructive_override=False,
    )
