"""Pin check (V8 germ). PR #1 fills version + sha256 and the --check CLI."""

PINNED_DIST = "tau-ai"
PINNED_VERSION = "0.4.1"
PINNED_SHA256 = ""


def main(argv=None):
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if "--check" not in args:
        print("usage: python3 -m tau_intent.pin --check")
        return 2
    if not PINNED_SHA256:
        print("pin: sha256 not recorded yet (PR #1)")
        return 1
    print(f"pin: {PINNED_DIST}=={PINNED_VERSION} sha256={PINNED_SHA256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
