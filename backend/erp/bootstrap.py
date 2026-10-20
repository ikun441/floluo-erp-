import argparse
from getpass import getpass
from sqlalchemy import select
from sqlalchemy.orm import Session
from .audit import append
from .config import Settings
from .database import lock_gate, make_engine
from .models import Gate, PolicyRevision, Role, User, UserRole, uid
from .permissions import RESOURCES
from .schemas import UserInput
from .services import PASSWORDS


def initialize(db, username, password):
    gate = lock_gate(db)
    if db.scalar(select(User.id).limit(1)) is not None or gate.revision_id:
        raise ValueError("bootstrap already completed; use authenticated administration")
    validated = UserInput(username=username, password=password)
    user = User(id=uid(), username=validated.username, password_hash=PASSWORDS.hash(password))
    role = Role(id=uid(), name="系统管理员")
    db.add_all([user, role])
    db.flush()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    rules = [{"id": "bootstrap-" + name, "subject": {"kind": "role", "id": role.id}, "effect": "allow",
              "resource": name, "actions": sorted(res.actions), "scope": "all",
              "fields": {field: "write" for field in res.fields}}
             for name, res in RESOURCES.items()]
    revision = PolicyRevision(id=uid(), number=1, author_id=user.id, rules=rules)
    db.add(revision)
    db.flush()
    gate.revision_id = revision.id
    append(db, user.id, uid(), "bootstrap", 200)
    db.commit()
    return user.id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    args = parser.parse_args()
    password = getpass("管理员密码（至少14字符）: ")
    if password != getpass("再次输入: "):
        raise SystemExit("passwords differ")
    engine = make_engine(Settings().database_url)
    with Session(engine) as db:
        initialize(db, args.username, password)
    print("Administrator initialized; no sample business data created.")


if __name__ == "__main__":
    main()
