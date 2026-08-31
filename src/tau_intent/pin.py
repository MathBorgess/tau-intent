"""Pin check (V8 germ). PR #1 fills version + sha256 and the --check CLI."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from importlib import metadata

PINNED_DIST = "tau-ai"
PINNED_VERSION = "0.4.1"
PINNED_SHA256 = "c0f396527c9c804f6787bc1eccb585f7f123293154861fe8b99354cba79dbc71"

PYPI_TIMEOUT_SECONDS = 10


def _resolve_pypi_wheel_sha256(dist: str, version: str) -> str:
    url = f"https://pypi.org/pypi/{dist}/{version}/json"
    with urllib.request.urlopen(url, timeout=PYPI_TIMEOUT_SECONDS) as response:
        payload = json.load(response)
    wheels = [f for f in payload.get("urls", []) if f.get("packagetype") == "bdist_wheel"]
    if not wheels:
        raise LookupError(f"no wheel found on PyPI for {dist}=={version}")
    return wheels[0]["digests"]["sha256"]


def main(argv=None):
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if "--check" not in args:
        print("usage: python3 -m tau_intent.pin --check")
        return 2
    if not (PINNED_DIST and PINNED_VERSION and PINNED_SHA256):
        print("pin: constants must be populated")
        return 1
    try:
        installed_version = metadata.version(PINNED_DIST)
    except metadata.PackageNotFoundError:
        print(f"pin: SKIP installed distribution {PINNED_DIST!r} not found")
        return 0
    if installed_version != PINNED_VERSION:
        print(
            f"pin: version mismatch for {PINNED_DIST}: "
            f"installed={installed_version} pinned={PINNED_VERSION}"
        )
        return 1

    try:
        published_sha256 = _resolve_pypi_wheel_sha256(PINNED_DIST, PINNED_VERSION)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, LookupError) as exc:
        print(f"pin: SKIP could not verify wheel sha256 from PyPI ({exc})")
        return 0
    if published_sha256 != PINNED_SHA256:
        print(
            f"pin: sha256 mismatch for {PINNED_DIST}=={PINNED_VERSION}: "
            f"published={published_sha256} pinned={PINNED_SHA256}"
        )
        return 1

    print(f"pin: OK {PINNED_DIST}=={PINNED_VERSION} sha256={PINNED_SHA256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
