"""Generate loopback-only local Compose settings; do not print credentials."""

import os
import secrets
from pathlib import Path

target = Path(__file__).resolve().parents[1] / ".env"
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as file:
    file.write("POSTGRES_PASSWORD=" + secrets.token_urlsafe(32) + "\n")
    file.write(
        "APP_ORIGIN=http://127.0.0.1:8080\nSECURE_COOKIES=false\nERP_BIND_ADDRESS=127.0.0.1\n"
    )
print("Created local .env. Configure TLS and Secure cookies before LAN use.")
