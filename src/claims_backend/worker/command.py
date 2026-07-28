import argparse
import asyncio
from collections.abc import Sequence

from claims_backend.config import ConfigurationError, Settings
from claims_backend.runtime.composition import create_process_runtime
from claims_backend.worker.application import create_claim_worker


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claims-worker")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("run-once", help="Lease and process at most one due claim.")
    parsed = parser.parse_args(arguments)
    if parsed.command != "run-once":
        parser.error("Unsupported worker command.")
    try:
        return asyncio.run(_run_once())
    except (ConfigurationError, ValueError) as error:
        print(f"configuration error: {error}")
        return 2


async def _run_once() -> int:
    runtime = create_process_runtime(Settings.from_env(), process_name="worker")
    worker = create_claim_worker(runtime)
    try:
        await worker.setup()
        await worker.run_once()
    finally:
        await worker.close()
    return 0
