"""Entry point for `python -m sg_preflight.cli`, delegating straight to `_common.main`."""

from __future__ import annotations

from sg_preflight.cli._common import main


raise SystemExit(main())
