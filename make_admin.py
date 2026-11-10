"""Grant or remove admin rights for a user.

Usage:
    python make_admin.py <username>            # make the user an admin
    python make_admin.py <username> --revoke   # remove admin rights
"""

import argparse
import sys

from database import SessionLocal
import models


def set_admin(username: str, is_admin: bool, db=None) -> bool:
    """Sets the admin flag for a user. Returns False if the user does not exist."""
    manage_db = db is None
    session = SessionLocal() if manage_db else db
    try:
        user = (
            session.query(models.User)
            .filter(models.User.username == username)
            .first()
        )
        if user is None:
            return False
        user.is_admin = is_admin
        session.commit()
        return True
    finally:
        if manage_db:
            session.close()


def main():
    parser = argparse.ArgumentParser(description="Grant or remove admin rights for a user")
    parser.add_argument("username")
    parser.add_argument("--revoke", action="store_true", help="Remove admin rights")
    args = parser.parse_args()

    if not set_admin(args.username, is_admin=not args.revoke):
        print(f"No user named '{args.username}'. Register the user first.")
        sys.exit(1)

    print(f"'{args.username}' is {'no longer' if args.revoke else 'now'} an admin.")


if __name__ == "__main__":
    main()
