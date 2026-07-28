from dataclasses import dataclass
from os import environ


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=environ.get(
                "CLAIMS_DATABASE_URL",
                "postgresql+psycopg://claims:claims@127.0.0.1:55432/claims",
            )
        )
