"""Entry point: read stdin JSON, output quota lines."""

from __future__ import annotations

from .quota import read_quota
from .render import render_quota


def main() -> None:
    quota = read_quota()
    render_quota(quota)


if __name__ == "__main__":
    main()
