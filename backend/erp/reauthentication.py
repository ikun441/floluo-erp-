"""Shared password reauthentication with persistent attempt budgets and account lockout."""

from datetime import UTC, timedelta

from .audit import digest
from .models import Throttle, now
from .services import PASSWORDS


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def verify(db, user, password, bucket):
    time = now()
    key = digest(bucket + ":" + user.id)
    throttle = db.get(Throttle, key)
    if throttle is None:
        throttle = Throttle(key=key, failures=0, window_start=time)
        db.add(throttle)
    if utc(throttle.window_start) + timedelta(minutes=1) <= time:
        throttle.failures, throttle.window_start = 0, time
    if throttle.failures >= 5 or (user.locked_until and utc(user.locked_until) > time):
        return 429
    throttle.failures += 1
    if not PASSWORDS.verify(password, user.password_hash):
        user.failed_logins += 1
        if user.failed_logins >= 5:
            user.locked_until = time + timedelta(minutes=15)
        return 403
    user.failed_logins, user.locked_until = 0, None
    return None
