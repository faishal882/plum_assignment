import argparse
import asyncio
import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from claims_backend.application.policy_admin import (
    PolicyActivationBlockedError,
    PolicyActivationForbiddenError,
    PolicyAdministrationApplication,
    PolicySourceNotFoundError,
    PolicyVersionNotFoundError,
)
from claims_backend.application.setup_import import (
    InvalidSetupSourceError,
    SetupDataApplication,
)
from claims_backend.config import Settings
from claims_backend.domain.policy import PolicyActivationEvent, PolicyVersionInspection
from claims_backend.domain.setup_data import MemberInspection, SetupImportReceipt
from claims_backend.infrastructure.postgres.identity import PostgresIdentityProvider
from claims_backend.infrastructure.postgres.policy_repository import (
    PostgresPolicyRepository,
)
from claims_backend.infrastructure.postgres.setup_import_repository import (
    PostgresSetupImportRepository,
)
from claims_backend.policy.compiler import PolicyCompiler


def main(arguments: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(arguments)
    result: object | None
    try:
        if args.command == "setup" and args.action == "import":
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
        elif args.command == "setup" and args.action == "inspect-import":
            result = asyncio.run(_inspect_import(UUID(args.import_id)))
        elif args.command == "setup":
            result = asyncio.run(_inspect_member(args.policy_id, args.member_id))
        elif args.action == "compile":
            overlay_path = Path(args.overlay)
            result = asyncio.run(
                _compile_policy(
                    args.source_sha,
                    overlay_path.read_bytes(),
                    overlay_path.name,
                )
            )
        elif args.action == "inspect":
            result = asyncio.run(_inspect_policy(UUID(args.policy_version_id)))
        elif args.action == "findings":
            inspected = asyncio.run(_inspect_policy(UUID(args.policy_version_id)))
            result = None if inspected is None else inspected.findings
        elif args.action == "activate":
            result = asyncio.run(_activate_policy(UUID(args.policy_version_id), args.actor))
        else:
            result = asyncio.run(_activation_events(UUID(args.policy_version_id)))
    except (
        InvalidSetupSourceError,
        OSError,
        ValueError,
        PolicySourceNotFoundError,
        PolicyVersionNotFoundError,
        PolicyActivationBlockedError,
        PolicyActivationForbiddenError,
    ) as error:
        print(json.dumps({"error": str(error)}, sort_keys=True))
        return 2

    if result is None:
        print(json.dumps({"error": "Record not found."}, sort_keys=True))
        return 1
    print(json.dumps(result, default=_json_default, sort_keys=True))
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

    policy = commands.add_parser("policy", help="Compile and activate policy versions.")
    policy_actions = policy.add_subparsers(dest="action", required=True)

    compile_command = policy_actions.add_parser(
        "compile",
        help="Compile an imported source with an approved overlay.",
    )
    compile_command.add_argument("--source-sha", required=True)
    compile_command.add_argument("--overlay", required=True)

    for action, help_text in (
        ("inspect", "Inspect a compiled policy version."),
        ("findings", "List structured compiler findings."),
        ("activation-events", "List policy activation audit events."),
    ):
        command = policy_actions.add_parser(action, help=help_text)
        command.add_argument("--policy-version-id", required=True)

    activate = policy_actions.add_parser(
        "activate",
        help="Activate a compiled policy version.",
    )
    activate.add_argument("--policy-version-id", required=True)
    activate.add_argument("--actor", required=True)
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


def _policy_application() -> tuple[
    PolicyAdministrationApplication,
    async_sessionmaker[AsyncSession],
    AsyncEngine,
]:
    settings = Settings.from_env()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    application = PolicyAdministrationApplication(
        PostgresPolicyRepository(factory),
        PolicyCompiler(),
    )
    return application, factory, engine


async def _compile_policy(
    source_sha256: str,
    overlay_bytes: bytes,
    overlay_name: str,
) -> PolicyVersionInspection:
    application, _, engine = _policy_application()
    try:
        return await application.compile(
            source_sha256,
            overlay_bytes,
            overlay_source_name=overlay_name,
        )
    finally:
        await engine.dispose()


async def _inspect_policy(
    policy_version_id: UUID,
) -> PolicyVersionInspection | None:
    application, _, engine = _policy_application()
    try:
        return await application.inspect_version(policy_version_id)
    finally:
        await engine.dispose()


async def _activate_policy(
    policy_version_id: UUID,
    actor: str,
) -> PolicyVersionInspection:
    application, factory, engine = _policy_application()
    try:
        async with factory() as session:
            principal = await PostgresIdentityProvider(session).resolve(actor)
        if principal is None:
            raise PolicyActivationForbiddenError
        return await application.activate(policy_version_id, principal)
    finally:
        await engine.dispose()


async def _activation_events(
    policy_version_id: UUID,
) -> tuple[PolicyActivationEvent, ...]:
    application, _, engine = _policy_application()
    try:
        return await application.list_activation_events(policy_version_id)
    finally:
        await engine.dispose()


def _json_default(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, date | datetime):
        return value.isoformat()
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


if __name__ == "__main__":
    raise SystemExit(main())
