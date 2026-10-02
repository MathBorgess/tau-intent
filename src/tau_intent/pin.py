"""Pin check (V8 germ). Declared tau-ai wheel, never a local edit of tau."""

from __future__ import annotations

import base64
import hashlib
import os
import sys

PINNED_DIST = "tau-ai"
PINNED_VERSION = "0.4.7"
PINNED_SHA256 = "4899ca3cc1c965e27c175fefad8754a68b441d9af49838f6624cc0e1adb59ce9"
#: huggingface/tau commit of the pinned release. The 0.4.1 value (0a67734...) is
#: the origin of the schema copies in tools.py and is kept there as ORIGIN_SHA.
#: The 0.4.7 tag commit could not be resolved offline, so it is declared
#: unverified (None) rather than guessed; the wheel sha256 is the real pin.
PINNED_GIT: str | None = None


def local_edits(dist_name: str = PINNED_DIST) -> list[str]:
    """Files of the installed distribution whose bytes differ from its RECORD.

    This is what "no local edit of tau" means operationally: the wheel's own
    manifest is the reference, so a patched or missing file is reported.
    """
    from importlib.metadata import distribution

    dist = distribution(dist_name)
    edited: list[str] = []
    for entry in dist.files or []:
        if entry.hash is None or entry.hash.mode != "sha256":
            continue  # RECORD itself, bytecode: not part of the wheel's content
        try:
            data = dist.locate_file(entry).read_bytes()
        except OSError:
            edited.append(f"{entry} (missing)")
            continue
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        if digest != entry.hash.value:
            edited.append(str(entry))
    return sorted(edited)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--check" not in args:
        print("usage: python3 -m tau_intent.pin --check [--require-installed]")
        return 2
    require_installed = "--require-installed" in args
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
        # CI runs with --require-installed: a SKIP there means the pin was not
        # exercised, which is exactly what the 3.11 job used to hide.
        return 1 if require_installed else 0

    if installed != PINNED_VERSION:
        print(f"pin: mismatch installed={installed} declared={PINNED_VERSION}")
        return 1

    edited = local_edits()
    if edited:
        print(f"pin: local edit of {PINNED_DIST}: {', '.join(edited[:10])}")
        return 1

    print(
        f"pin: OK {PINNED_DIST}=={PINNED_VERSION} sha256={PINNED_SHA256} "
        f"git={PINNED_GIT or 'unverified'} files-match-RECORD"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
