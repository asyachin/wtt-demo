#!/usr/bin/env python3
"""Rotate the local DEV PostgreSQL password safely."""

import os
import secrets
import string
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "app/docker-compose.yml"
ENV_LINK = ROOT / "app/.env.dev"

ALPHABET = string.ascii_letters + string.digits


def generate_password(length: int = 32) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def read_env(path: Path) -> tuple[list[str], dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    values = {}

    for line in lines:
        if not line or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator:
            if key in values:
                raise ValueError(f"Duplicate environment variable: {key}")
            values[key] = value

    return lines, values


def change_db_password(user: str, password: str) -> None:
    """Change PostgreSQL password without exposing it in command arguments."""
    command = [
        "docker",
        "compose",
        "--project-directory",
        str(ROOT / "app"),
        "--env-file",
        str(ENV_LINK),
        "-f",
        str(COMPOSE),
        "exec",
        "-T",
        "db",
        "psql",
        "-U",
        "postgres",
        "-d",
        "postgres",
        "-v",
        "ON_ERROR_STOP=1",
    ]

    # Both the username and generated password are alphanumeric.
    sql = f"ALTER ROLE {user} PASSWORD '{password}';\n"

    subprocess.run(
        command,
        input=sql,
        text=True,
        check=True,
        stdout=subprocess.DEVNULL,
    )


def write_env(path: Path, lines: list[str]) -> None:
    fd, temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=".env.dev.",
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write("\n".join(lines) + "\n")
            output.flush()
            os.fsync(output.fileno())

        os.chmod(temporary, 0o600)
        os.replace(temporary, path)

    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> None:
    if not ENV_LINK.is_symlink():
        raise RuntimeError("Expected app/.env.dev to be a symlink")

    path = ENV_LINK.resolve(strict=True)

    if path.stat().st_uid != os.getuid():
        raise RuntimeError("DEV environment file belongs to another user")

    lines, values = read_env(path)

    user = values.get("POSTGRES_USER")
    old_password = values.get("POSTGRES_PASSWORD")

    if not user or not old_password:
        raise RuntimeError("Missing PostgreSQL credentials")

    if not user.replace("_", "").isalnum():
        raise RuntimeError("Invalid PostgreSQL username")

    new_password = generate_password()

    matches = [index for index, line in enumerate(lines) if line.startswith("POSTGRES_PASSWORD=")]

    if len(matches) != 1:
        raise RuntimeError("Expected exactly one POSTGRES_PASSWORD")

    lines[matches[0]] = f"POSTGRES_PASSWORD={new_password}"

    # Perform the database change first, retaining the old password
    # in memory for rollback if writing the environment file fails.
    change_db_password(user, new_password)

    try:
        write_env(path, lines)
    except Exception:
        try:
            change_db_password(user, old_password)
        except Exception as rollback_error:
            raise RuntimeError(
                "Password rotation failed and database rollback also failed. "
                "Manual recovery is required."
            ) from rollback_error
        raise

    print("PASS: PostgreSQL password rotated")
    print("PASS: DEV environment updated")
    print("NEXT: Recreate application containers")


if __name__ == "__main__":
    main()
