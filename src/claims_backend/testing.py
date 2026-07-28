from sqlalchemy.engine import make_url


class UnsafeTestDatabaseError(RuntimeError):
    pass


def assert_safe_test_database(
    application_database_url: str,
    test_database_url: str,
    *,
    allow_destructive_override: bool,
) -> None:
    """Reject a test target that resolves to the normal application database."""
    application = make_url(application_database_url)
    test = make_url(test_database_url)
    application_identity = (
        application.get_backend_name(),
        application.host,
        application.port,
        application.database,
        application.username,
    )
    test_identity = (
        test.get_backend_name(),
        test.host,
        test.port,
        test.database,
        test.username,
    )
    if application_identity == test_identity and not allow_destructive_override:
        raise UnsafeTestDatabaseError(
            "CLAIMS_TEST_DATABASE_URL targets CLAIMS_DATABASE_URL. "
            "Use a separate disposable database or set "
            "CLAIMS_ALLOW_DESTRUCTIVE_TEST_DATABASE=1 explicitly."
        )
