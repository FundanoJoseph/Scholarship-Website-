import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database import execute_or_raise, first, get_db, rows
from backend.main import normalize_email, validate_full_name, validate_password, validate_university_email
from backend.security import hash_password


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()

    email = validate_university_email(args.email)
    full_name = validate_full_name(args.name)
    password = getpass.getpass("New admin password: ")
    confirmation = getpass.getpass("Confirm admin password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match.")
    validate_password(password)

    database = get_db()
    admins = rows(
        execute_or_raise(
            database.table("users")
            .select("id")
            .eq("role", "admin")
            .is_("deleted_at", "null")
            .limit(1)
        )
    )
    if admins:
        raise SystemExit("An active Admin account already exists; no changes were made.")

    existing = first(
        execute_or_raise(
            database.table("users")
            .select("*")
            .eq("email", normalize_email(email))
            .is_("deleted_at", "null")
            .limit(1)
        )
    )
    values = {
        "full_name": full_name,
        "email": email,
        "role": "admin",
        "password_hash": hash_password(password),
    }
    if existing:
        result = execute_or_raise(
            database.table("users")
            .update({**values, "session_version": int(existing.get("session_version", 0)) + 1})
            .eq("id", existing["id"])
            .is_("deleted_at", "null")
            .select("id,email,role")
            .single()
        )
    else:
        result = execute_or_raise(
            database.table("users")
            .insert({**values, "student_id": "", "program": "", "year_level": ""})
            .select("id,email,role")
            .single()
        )
    print(f"Admin ready: {result.data['email']} ({result.data['id']})")


if __name__ == "__main__":
    main()
