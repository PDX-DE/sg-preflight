"""Entry point for `python -m sg_preflight`, delegating to the CLI's main()."""

from sg_preflight.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
