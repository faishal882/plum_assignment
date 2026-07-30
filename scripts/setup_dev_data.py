#!/usr/bin/env python3
"""Idempotently prepare local policy/member data for development."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from claims_backend.application.policy_admin import PolicyAdministrationApplication
from claims_backend.application.setup_import import SetupDataApplication
from claims_backend.config import Settings
from claims_backend.infrastructure.postgres.identity import PostgresIdentityProvider
from claims_backend.infrastructure.postgres.models import PolicyVersionRow
from claims_backend.infrastructure.postgres.policy_repository import PostgresPolicyRepository
from claims_backend.infrastructure.postgres.setup_import_repository import (
    PostgresSetupImportRepository,
)
from claims_backend.policy.compiler import PolicyCompiler

POLICY_PATH = Path("problem_statement/policy_terms.json")
OVERLAY_PATH = Path("config/policy/assignment-overlay-v1.json")
POLICY_ID = "PLUM_GHI_2024"
ACTOR = "operator.local"


async def main() -> None:
    settings = Settings.from_env()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            active_id = await session.scalar(
                select(PolicyVersionRow.id).where(
                    PolicyVersionRow.policy_id == POLICY_ID,
                    PolicyVersionRow.status == "ACTIVE",
                )
            )
        if active_id is not None:
            print(json.dumps({"status": "already_ready", "policy_version_id": str(active_id)}))
            return

        setup = SetupDataApplication(PostgresSetupImportRepository(session_factory))
        policy_bytes = await asyncio.to_thread(POLICY_PATH.read_bytes)
        overlay_bytes = await asyncio.to_thread(OVERLAY_PATH.read_bytes)
        receipt = await setup.import_sources(
            policy_bytes,
            source_name=POLICY_PATH.name,
        )

        policy_admin = PolicyAdministrationApplication(
            PostgresPolicyRepository(session_factory),
            PolicyCompiler(),
        )
        compiled = await policy_admin.compile(
            receipt.policy_source_sha256,
            overlay_bytes,
            overlay_source_name=OVERLAY_PATH.name,
        )
        async with session_factory() as session:
            principal = await PostgresIdentityProvider(session).resolve(ACTOR)
        if principal is None:
            raise RuntimeError(f"Activation actor {ACTOR!r} is not available.")
        activated = await policy_admin.activate(compiled.policy_version_id, principal)
        print(
            json.dumps(
                {
                    "status": "ready",
                    "import_id": str(receipt.import_id),
                    "policy_version_id": str(activated.policy_version_id),
                    "members_created": receipt.member_versions_created,
                    "utilization_records_created": receipt.utilization_records_created,
                    "findings": [finding.code for finding in receipt.findings],
                },
                sort_keys=True,
            )
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
