import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

_USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


class Role(StrEnum):
    MEMBER = "MEMBER"
    REVIEWER = "REVIEWER"
    OPERATOR = "OPERATOR"


class InvalidUsernameError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: UUID
    username: str
    roles: frozenset[Role]
    member_id: str | None


def normalize_username(username: str) -> str:
    normalized = username.strip().casefold()
    if not _USERNAME_PATTERN.fullmatch(normalized):
        raise InvalidUsernameError("Username must contain 3-64 supported characters.")
    return normalized
