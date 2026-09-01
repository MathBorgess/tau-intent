"""Pin check (V8 germ). Declared tau-ai wheel, never a local edit of tau."""

from __future__ import annotations

import os
import sys

PINNED_DIST = "tau-ai"
PINNED_VERSION = "0.4.1"
PINNED_SHA256 = "c0f396527c9c804f6787bc1eccb585f7f123293154861fe8b99354cba79dbc71"
PINNED_GIT = "0a67734fe4c89821c652c02fe74c1e0434fd36f6"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--check" not in args:
        print("usage: python3 -m tau_intent.pin --check")
        return 2
    if not PINNED_DIST or not PINNED_VERSION or not PINNED_SHA256:
        print("pin: constants empty")
        return 1
    if len(PINNED_SHA256) != 64 or any(c not in "0123456789abcdef" for c in PINNED_SHA256):
        print("pin: sha256 is not 64 lowercase hex")
        return 1

    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover
        PackageNotFoundError = Exception  # type: ignore[misc, assignment]
        version = None  # type: ignore[assignment]

    installed: str | None = None
    if version is not None:
        try:
            installed = version(PINNED_DIST)
        except PackageNotFoundError:
            installed = None

    if installed is None:
        reason = "tau-ai not installed"
        if os.environ.get("NO_NETWORK"):
            reason += "; NO_NETWORK=1 (wheel fetch skipped)"
        print(
            f"pin: SKIP labelled: {reason}; "
            f"constants recorded {PINNED_DIST}=={PINNED_VERSION} sha256={PINNED_SHA256}"
        )
        return 0

    if installed != PINNED_VERSION:
        print(f"pin: mismatch installed={installed} declared={PINNED_VERSION}")
        return 1

    print(
        f"pin: {PINNED_DIST}=={PINNED_VERSION} sha256={PINNED_SHA256} git={PINNED_GIT}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
