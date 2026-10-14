
#!/usr/bin/env python3
"""Rotate PostgreSQL password and synchronize the Kubernetes Secret."""

import base64
import json
import secrets
import string
import subprocess
import sys

NAMESPACE = "vote-dev"
SECRET_NAME = "postgres-credentials"
POSTGRES_POD = "postgres-0"


def kubectl(*args, data=None):
    result = subprocess.run(
        ["kubectl", *args],
        input=data,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout


def set_db_password(password):
    # Password is passed through stdin, not through command-line arguments.
    escaped = password.replace("'", "''")
    sql = f"ALTER ROLE postgres WITH PASSWORD '{escaped}';\n"

    kubectl(
        "exec",
        "-i",
        "-n",
        NAMESPACE,
        POSTGRES_POD,
        "--",
        "psql",
        "-U",
        "postgres",
        "-d",
        "postgres",
        "-v",
        "ON_ERROR_STOP=1",
        data=sql,
    )


def main():
    current = json.loads(
        kubectl(
            "get",
            "secret",
            SECRET_NAME,
            "-n",
            NAMESPACE,
            "-o",
            "json",
        )
    )

    old_password = base64.b64decode(
        current["data"]["POSTGRES_PASSWORD"]
    ).decode()

    alphabet = string.ascii_letters + string.digits
    new_password = "".join(
        secrets.choice(alphabet) for _ in range(40)
    )

    replacement = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": SECRET_NAME,
            "namespace": NAMESPACE,
            "resourceVersion": current["metadata"]["resourceVersion"],
        },
        "type": current.get("type", "Opaque"),
        "data": dict(current["data"]),
    }

    replacement["data"]["POSTGRES_PASSWORD"] = base64.b64encode(
        new_password.encode()
    ).decode()

    print("1/2 Updating PostgreSQL role password...", flush=True)
    set_db_password(new_password)

    print("2/2 Updating Kubernetes Secret...", flush=True)

    try:
        kubectl(
            "replace",
            "-f",
            "-",
            data=json.dumps(replacement),
        )
    except subprocess.CalledProcessError:
        print(
            "Secret update failed; attempting database rollback.",
            file=sys.stderr,
        )
        try:
            set_db_password(old_password)
            print("Database password rollback successful.", file=sys.stderr)
        except subprocess.CalledProcessError:
            print(
                "CRITICAL: database rollback failed; "
                "manual recovery is required.",
                file=sys.stderr,
            )
        raise

    print("Rotation successful. New password was not printed.")


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, KeyError, ValueError) as exc:
        # Do not print subprocess stderr: it could contain sensitive data.
        print(
            f"Rotation failed: {type(exc).__name__}",
            file=sys.stderr,
        )
        sys.exit(1)
