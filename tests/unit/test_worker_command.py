import pytest

from claims_backend.worker import command


def test_worker_command_returns_configuration_error(monkeypatch, capsys) -> None:
    async def fail() -> int:
        raise ValueError("missing setting")

    monkeypatch.setattr(command, "_run_once", fail)

    assert command.main(["run-once"]) == 2
    assert "configuration error: missing setting" in capsys.readouterr().out


def test_worker_command_lists_continuous_loop() -> None:
    with pytest.raises(SystemExit, match="0"):
        command.main(["--help"])
