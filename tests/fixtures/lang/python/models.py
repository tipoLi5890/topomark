"""Data models for the app."""

from __future__ import annotations

__all__ = ["User", "make_user", "MAX_USERS"]

MAX_USERS = 100
_SECRET = 'x'
LONG = f"{MAX_USERS!r:>10} {'nested'} {\"dq\"}"


class User:
    """A user record."""

    class Meta:
        table = "users"

    def __init__(self, name: str) -> None:
        self.name = name

    @property
    def title(self) -> str:
        return f"{self.name}"

    async def save(
        self,
        force: bool = False,
    ) -> bool:
        def inner():
            pass
        return True


def make_user(name):
    return User(name)


def _private():
    s = """not a def
def fake():
    pass
"""
    return s


async def fetch_all() -> list[User]:
    return []
