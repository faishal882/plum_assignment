import argparse
import asyncio
import signal
from collections.abc import Sequence

from claims_backend.config import ConfigurationError, Settings
from claims_backend.runtime.composition import create_process_runtime
from claims_backend.worker.application import create_claim_worker


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claims-worker")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("run-once", help="Lease and process at most one due claim.")
    subcommands.add_parser("run-loop", help="Continuously process due claims.")
    parsed = parser.parse_args(arguments)
    try:
        if parsed.command == "run-once":
            return asyncio.run(_run_once())
        return asyncio.run(_run_loop())
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


async def _run_loop() -> int:
    runtime = create_process_runtime(Settings.from_env(), process_name="worker")
    worker = create_claim_worker(runtime)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop_event.set)
    try:
        await worker.setup()
        await worker.run_loop(stop_event)
    finally:
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(signum)
        await worker.close()
    return 0
