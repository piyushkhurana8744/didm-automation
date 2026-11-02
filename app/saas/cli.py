"""Command line for the first platform administrator (there is no web sign-up for this role).

    DATABASE_URL=... python -m app.saas.cli create-platform-admin --email you@example.com --name "Your Name"

The password is asked for on the terminal and never echoed or logged.
"""
import argparse
import getpass
import sys

from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal, init_db, utcnow
from .models import AuditEvent, User
from .passwords import hash_password, password_problem


def create_platform_admin(email: str, name: str, password: str) -> str:
    email = email.strip().lower()
    problem = password_problem(password)
    if problem:
        raise ValueError(problem)
    with SessionLocal() as db:
        user = db.scalars(select(User).where(User.email == email)).first()
        if user is None:
            user = User(email=email, name=name, status="active", email_verified_at=utcnow())
            db.add(user)
        user.password_hash = hash_password(password)
        user.is_platform_admin = True
        db.flush()
        db.add(AuditEvent(actor_user_id=None, action="platform.admin_granted", target_type="user", target_id=user.id,
                          details={"via": "cli"}))
        db.commit()
        return user.id


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m app.saas.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-platform-admin", help="create a platform admin, or promote an existing user")
    c.add_argument("--email", required=True)
    c.add_argument("--name", default="")
    args = p.parse_args(argv)
    init_db(settings.database_url, migrate=settings.migrate_on_start)
    pw = getpass.getpass("Password (10+ characters): ")
    if pw != getpass.getpass("Repeat password: "):
        print("Passwords do not match.", file=sys.stderr)
        return 1
    try:
        uid = create_platform_admin(args.email, args.name, pw)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Platform admin ready: {args.email.strip().lower()} (user id {uid})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
