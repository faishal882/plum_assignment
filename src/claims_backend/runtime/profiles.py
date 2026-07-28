from enum import StrEnum


class ExecutionProfile(StrEnum):
    RECORDED_LOCAL = "RECORDED_LOCAL"
    LIVE_INTELLIGENCE = "LIVE_INTELLIGENCE"
    UNIT = "UNIT"
    STRUCTURED_COMPONENT = "STRUCTURED_COMPONENT"
    RENDERED_RECORDED = "RENDERED_RECORDED"

    @property
    def allows_external_network(self) -> bool:
        return self is ExecutionProfile.LIVE_INTELLIGENCE

    @property
    def uses_recorded_providers(self) -> bool:
        return self in {
            ExecutionProfile.RECORDED_LOCAL,
            ExecutionProfile.UNIT,
            ExecutionProfile.STRUCTURED_COMPONENT,
            ExecutionProfile.RENDERED_RECORDED,
        }


class ProfileAuthorizationError(ValueError):
    pass


def resolve_execution_profile(
    value: str,
    *,
    run_live_aws: bool,
) -> ExecutionProfile:
    normalized = "RECORDED_LOCAL" if value == "LOCAL" else value
    try:
        profile = ExecutionProfile(normalized)
    except ValueError as error:
        raise ValueError("execution_profile is unsupported") from error
    if profile is ExecutionProfile.LIVE_INTELLIGENCE and not run_live_aws:
        raise ProfileAuthorizationError("LIVE_INTELLIGENCE requires CLAIMS_RUN_LIVE_AWS=1.")
    return profile
