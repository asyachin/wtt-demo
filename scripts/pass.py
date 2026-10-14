#!/usr/bin/env python3
"""Generate a cryptographically secure password."""

import argparse
import secrets
import string

DEFAULT_LENGTH = 13
MIN_LENGTH = 13

# python scripts/pass.py --length 13


def generate_password(length: int = DEFAULT_LENGTH) -> str:
    """Generate an alphanumeric password using a secure random source."""
    if length < MIN_LENGTH:
        raise ValueError(f"Password length must be at least {MIN_LENGTH} characters")

    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a secure alphanumeric password.")
    parser.add_argument(
        "--length",
        type=int,
        default=DEFAULT_LENGTH,
        help=f"Password length (default: {DEFAULT_LENGTH}, minimum: {MIN_LENGTH})",
    )
    args = parser.parse_args()

    try:
        password = generate_password(args.length)
    except ValueError as exc:
        parser.error(str(exc))

    print(password)


if __name__ == "__main__":
    main()
