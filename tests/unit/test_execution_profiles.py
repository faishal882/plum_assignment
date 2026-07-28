import pytest

from claims_backend.runtime.profiles import (
    ExecutionProfile,
    ProfileAuthorizationError,
    resolve_execution_profile,
)


def test_local_profile_is_migrated_to_recorded_local() -> None:
    assert resolve_execution_profile("LOCAL", run_live_aws=False) is ExecutionProfile.RECORDED_LOCAL


def test_recorded_profiles_are_network_free() -> None:
    assert (
        resolve_execution_profile("RECORDED_LOCAL", run_live_aws=False).allows_external_network
        is False
    )
    assert (
        resolve_execution_profile("RENDERED_RECORDED", run_live_aws=False).allows_external_network
        is False
    )


def test_live_profile_requires_explicit_paid_authorization() -> None:
    with pytest.raises(ProfileAuthorizationError, match="CLAIMS_RUN_LIVE_AWS=1"):
        resolve_execution_profile("LIVE_INTELLIGENCE", run_live_aws=False)

    assert (
        resolve_execution_profile("LIVE_INTELLIGENCE", run_live_aws=True)
        is ExecutionProfile.LIVE_INTELLIGENCE
    )


def test_unknown_profile_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        resolve_execution_profile("UNSAFE", run_live_aws=False)
