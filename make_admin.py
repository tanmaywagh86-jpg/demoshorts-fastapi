"""Grant or remove admin rights for a user, or create a new admin user directly.

Usage:
    python make_admin.py <username>                       # make existing user an admin
    python make_admin.py <username> --password <password> # create or promote admin with password
    python make_admin.py <username> --revoke              # remove admin rights
"""

import argparse
import sys

from auth import hash_password
from database import SessionLocal
import models


def set_admin(
    username: str,
    is_admin: bool,
    password: str | None = None,
    db=None,
) -> bool:
    """Sets the admin flag for a user, or creates the user if password is provided."""
    manage_db = db is None
    session = SessionLocal() if manage_db else db
    try:
        user = (
            session.query(models.User)
            .filter(models.User.username == username)
            .first()
        )
        if user is None:
            if password:
                new_user = models.User(
                    username=username,
                    hashed_password=hash_password(password),
                    is_admin=is_admin,
                )
                session.add(new_user)
                session.commit()
                return True
            return False

        user.is_admin = is_admin
        if password:
            user.hashed_password = hash_password(password)
        session.commit()
        return True
    finally:
        if manage_db:
            session.close()


def main():
    parser = argparse.ArgumentParser(description="Grant or remove admin rights for a user")
    parser.add_argument("username")
    parser.add_argument("--password", "-p", help="Set or create user with password")
    parser.add_argument("--revoke", action="store_true", help="Remove admin rights")
    args = parser.parse_args()

    success = set_admin(
        args.username,
        is_admin=not args.revoke,
        password=args.password,
    )
    if not success:
        print(f"No user named '{args.username}'. Register the user first or pass --password <pwd> to create them.")
        sys.exit(1)

    print(f"'{args.username}' is {'no longer' if args.revoke else 'now'} an admin.")


if __name__ == "__main__":
    main()
