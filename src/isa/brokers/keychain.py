"""Secret storage in the macOS Keychain (via /usr/bin/security). Secrets never touch disk or stdout."""

from __future__ import annotations

import shutil
import subprocess

SERVICE = "india-stock-analyzer"


class KeychainError(RuntimeError):
    pass


class Keychain:
    """Generic-password items under one service name."""

    def __init__(self, service: str = SERVICE):
        self.service = service
        self.tool = shutil.which("security") or "/usr/bin/security"

    def get(self, account: str) -> str | None:
        try:
            r = subprocess.run([self.tool, "find-generic-password", "-s", self.service, "-a", account, "-w"],
                               capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise KeychainError(f"macOS Keychain not available: {exc}") from exc
        if r.returncode != 0:
            return None
        return r.stdout.rstrip("\n")

    def set(self, account: str, secret: str) -> None:
        r = subprocess.run([self.tool, "add-generic-password", "-U", "-s", self.service, "-a", account,
                            "-w", secret], capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            raise KeychainError(f"could not store {account} in the Keychain")

    def delete(self, account: str) -> bool:
        r = subprocess.run([self.tool, "delete-generic-password", "-s", self.service, "-a", account],
                           capture_output=True, text=True, timeout=20)
        return r.returncode == 0


class MemoryStore:
    """In-memory stand-in for tests."""

    def __init__(self, items: dict[str, str] | None = None):
        self.items = dict(items or {})

    def get(self, account: str) -> str | None:
        return self.items.get(account)

    def set(self, account: str, secret: str) -> None:
        self.items[account] = secret

    def delete(self, account: str) -> bool:
        return self.items.pop(account, None) is not None
