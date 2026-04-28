"""Docker container smoke tests.

These tests verify that the Docker images work correctly. They are marked
as slow and skipped in CI — run them manually with ``pytest -m slow``.
"""

from __future__ import annotations

import subprocess

import pytest

pytestmark = pytest.mark.slow

IMAGE_ENTRY = "mfreitas/tdf2mzml:0.5"
IMAGE_NOENTRY = "mfreitas/tdf2mzml:0.5_noentry"


def _docker_run(image: str, cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "run", "--rm", *cmd, image],
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestDockerImages:
    """Smoke tests for Docker container functionality."""

    def test_ps_command_exists_entry(self) -> None:
        result = _docker_run(IMAGE_ENTRY, ["--entrypoint", "ps"])
        assert result.returncode == 0

    def test_ps_command_exists_noentry(self) -> None:
        result = subprocess.run(
            ["docker", "run", "--rm", IMAGE_NOENTRY, "ps", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "procps" in result.stdout

    def test_entrypoint_help(self) -> None:
        result = subprocess.run(
            ["docker", "run", "--rm", IMAGE_ENTRY, "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "tdf2mzml" in result.stdout

    def test_noentry_help(self) -> None:
        result = subprocess.run(
            ["docker", "run", "--rm", IMAGE_NOENTRY, "tdf2mzml", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "tdf2mzml" in result.stdout
