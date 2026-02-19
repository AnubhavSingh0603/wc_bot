import os
import sys
import subprocess
from pathlib import Path


def run_main_smoke_tests():
    try:
        import discord  # type: ignore
    except Exception:
        # Skip in minimal environments without discord.py
        return

    # Ensure main.py --test exits 0 when token format is valid
    project_dir = Path(__file__).resolve().parent.parent
    env = dict(os.environ)
    env["DISCORD_TOKEN"] = "x" * 60
    env["DB_DIALECT"] = "sqlite"
    env["DB_PATH"] = ":memory:"

    p = subprocess.run(
        [sys.executable, "main.py", "--test"],
        cwd=str(project_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if p.returncode != 0:
        raise AssertionError(
            f"main.py --test failed. rc={p.returncode}\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}"
        )
