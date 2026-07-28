import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from claims_backend.application.setup_import import (
    InvalidSetupSourceError,
    SetupDataApplication,
)
from claims_backend.config import Settings
from claims_backend.domain.setup_data import MemberInspection, SetupImportReceipt
from claims_backend.infrastructure.postgres.setup_import_repository import (
    PostgresSetupImportRepository,
)


def main(arguments: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(arguments)
    result: SetupImportReceipt | MemberInspection | None
    try:
        if args.action == "import":
            policy_path = Path(args.policy)
            member_data_path = None if args.member_data is None else Path(args.member_data)
            result = asyncio.run(
                _import(
                    policy_path.read_bytes(),
                    policy_path.name,
                    None if member_data_path is None else member_data_path.read_bytes(),
                    None if member_data_path is None else member_data_path.name,
                )
            )
        elif args.action == "inspect-import":
            result = asyncio.run(_inspect_import(UUID(args.import_id)))
        else:
            result = asyncio.run(_inspect_member(args.policy_id, args.member_id))
    except (InvalidSetupSourceError, OSError, ValueError) as error:
        print(json.dumps({"error": str(error)}, sort_keys=True))
        return 2

    if result is None:
        print(json.dumps({"error": "Record not found."}, sort_keys=True))
        return 1
    print(json.dumps(asdict(result), default=_json_default, sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claimsctl")
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("setup", help="Import and inspect setup data.")
    actions = setup.add_subparsers(dest="action", required=True)

    import_command = actions.add_parser("import", help="Import immutable setup sources.")
    import_command.add_argument("--policy", required=True)
    import_command.add_argument("--member-data")

    inspect_import = actions.add_parser(
        "inspect-import",
        help="Inspect an import receipt and its findings.",
    )
    inspect_import.add_argument("--import-id", required=True)

    inspect_member = actions.add_parser(
        "inspect-member",
        help="Inspect the latest imported member snapshot.",
    )
    inspect_member.add_argument("--policy-id", required=True)
    inspect_member.add_argument("--member-id", required=True)
    return parser


async def _import(
    policy_bytes: bytes,
    policy_name: str,
    member_data_bytes: bytes | None,
    member_data_name: str | None,
) -> SetupImportReceipt:
    application, engine = _application()
    try:
        return await application.import_sources(
            policy_bytes,
            source_name=policy_name,
            member_data_bytes=member_data_bytes,
            member_data_source_name=member_data_name,
        )
    finally:
        await engine.dispose()


async def _inspect_import(import_id: UUID) -> SetupImportReceipt | None:
    application, engine = _application()
    try:
        return await application.inspect_import(import_id)
    finally:
        await engine.dispose()


async def _inspect_member(
    policy_id: str,
    member_id: str,
) -> MemberInspection | None:
    application, engine = _application()
    try:
        return await application.inspect_member(policy_id, member_id)
    finally:
        await engine.dispose()


def _application() -> tuple[SetupDataApplication, AsyncEngine]:
    settings = Settings.from_env()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return SetupDataApplication(PostgresSetupImportRepository(factory)), engine


def _json_default(value: Any) -> str:
    if isinstance(value, UUID | date | datetime):
        return value.isoformat() if not isinstance(value, UUID) else str(value)
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


if __name__ == "__main__":
    raise SystemExit(main())
