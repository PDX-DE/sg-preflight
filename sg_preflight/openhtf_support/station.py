from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import html
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Iterator

from .dependency import require_openhtf, require_openhtf_module
from .phases import make_openhtf_phases


SGFX_STATION_TITLE = "SGFX QA Preflight"
SGFX_STATION_HEADER = "SGFX: Project Quality-Hero"
SGFX_STATION_FOOTER = "Manual review remains required. Decision: not approval - evidence only."


@dataclass(frozen=True)
class StartedSgfxStation:
    port: int
    raw_url: str
    sgfx_url: str
    health_url: str
    server: Any


class _NoopStationMulticast:
    address = "127.0.0.1"
    port = 0

    def start(self) -> None:
        return None

    def stop(self, *args: Any, **kwargs: Any) -> None:
        return None


def _load_openhtf_config(port: int) -> None:
    configuration = require_openhtf_module("openhtf.util.configuration")
    configuration.CONF.load(station_server_port=str(port), station_id="SGFX-QA-Preflight")


def _sgfx_station_html(*, profile_id: str, workspace: Path, raw_url: str) -> str:
    profile = html.escape(profile_id)
    workspace_text = html.escape(str(workspace))
    raw = html.escape(raw_url)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{SGFX_STATION_TITLE}</title>
  <style>
    body {{
      margin: 0;
      font-family: Segoe UI, Arial, sans-serif;
      color: #1d252c;
      background: #f5f7f8;
    }}
    main {{
      max-width: 920px;
      margin: 0 auto;
      padding: 32px 24px;
    }}
    h1 {{
      font-size: 28px;
      font-weight: 650;
      margin: 0 0 18px;
    }}
    dl {{
      display: grid;
      grid-template-columns: 140px 1fr;
      gap: 10px 18px;
      margin: 24px 0;
    }}
    dt {{
      font-weight: 650;
      color: #45515b;
    }}
    dd {{
      margin: 0;
      overflow-wrap: anywhere;
    }}
    .guardrail {{
      border-top: 1px solid #d7dde2;
      padding-top: 18px;
      margin-top: 26px;
      color: #38444d;
      font-weight: 600;
    }}
    a {{
      color: #145a8d;
    }}
  </style>
</head>
<body>
  <main>
    <h1>{SGFX_STATION_HEADER}</h1>
    <dl>
      <dt>Profile</dt>
      <dd>{profile}</dd>
      <dt>Workspace</dt>
      <dd>{workspace_text}</dd>
      <dt>Run scope</dt>
      <dd>delivery checklist, screenshot test state, daily digest, manual review companion</dd>
      <dt>OpenHTF core</dt>
      <dd><a href="{raw}">station runtime endpoint</a></dd>
    </dl>
    <p class="guardrail">{SGFX_STATION_FOOTER}</p>
  </main>
</body>
</html>
"""


def _add_sgfx_routes(server: Any, *, profile_id: str, workspace: Path) -> None:
    tornado_web = require_openhtf_module("tornado.web")
    raw_url = f"http://127.0.0.1:{server.port}/"
    page = _sgfx_station_html(profile_id=profile_id, workspace=workspace, raw_url=raw_url)

    class SgfxInfoHandler(tornado_web.RequestHandler):  # type: ignore[misc]
        def get(self) -> None:
            self.set_header("Content-Type", "text/html; charset=utf-8")
            self.write(page)

    class SgfxHealthHandler(tornado_web.RequestHandler):  # type: ignore[misc]
        def get(self) -> None:
            self.write({"status": "available", "title": SGFX_STATION_TITLE, "is_approval": False})

    server.application.add_handlers(
        r".*$",
        [
            (r"/sgfx", SgfxInfoHandler),
            (r"/sgfx/health", SgfxHealthHandler),
        ],
    )


def _wait_for_http(url: str, timeout_seconds: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status < 500:
                    return
        except Exception as exc:
            last_error = exc
            time.sleep(0.1)
    if last_error is not None:
        raise TimeoutError(f"Station server did not answer at {url}: {last_error}")
    raise TimeoutError(f"Station server did not answer at {url}")


def make_sgfx_test(
    *,
    profile_id: str,
    workspace: Path | str,
    bmw_root: Path | str | None = None,
    ui_mode: str = "clean",
) -> Any:
    htf = require_openhtf()
    from .plugs import SgfxStationContext, configure_sgfx_context

    context = SgfxStationContext(
        profile_id=profile_id,
        workspace=Path(workspace).resolve(),
        bmw_root=Path(bmw_root).resolve() if bmw_root else None,
        ui_mode=ui_mode,
    )
    configure_sgfx_context(context)
    return htf.Test(
        *make_openhtf_phases(),
        test_name="SGFX Project Quality-Hero",
        test_description="Local QA evidence run. Manual review remains required.",
    )


@contextmanager
def start_sgfx_station_server(
    *,
    profile_id: str,
    workspace: Path | str,
    history_path: Path | str,
    port: int = 0,
    enable_multicast: bool = False,
) -> Iterator[StartedSgfxStation]:
    station_server = require_openhtf_module("openhtf.output.servers.station_server")
    _load_openhtf_config(port)
    history = Path(history_path).resolve()
    history.mkdir(parents=True, exist_ok=True)
    server = station_server.StationServer(history)
    if not enable_multicast:
        try:
            server.station_multicast._sock.close()
        except Exception:
            pass
        server.station_multicast = _NoopStationMulticast()
    workspace_path = Path(workspace).resolve()
    _add_sgfx_routes(server, profile_id=profile_id, workspace=workspace_path)
    with server:
        started = StartedSgfxStation(
            port=int(server.port),
            raw_url=f"http://127.0.0.1:{server.port}/",
            sgfx_url=f"http://127.0.0.1:{server.port}/sgfx",
            health_url=f"http://127.0.0.1:{server.port}/sgfx/health",
            server=server,
        )
        _wait_for_http(started.health_url)
        yield started


def run_station(
    *,
    profile_id: str,
    workspace: Path | str,
    bmw_root: Path | str | None = None,
    ui_mode: str = "clean",
    port: int = 0,
    history_path: Path | str | None = None,
    open_browser: bool = True,
    once: bool = False,
) -> int:
    workspace_path = Path(workspace).resolve()
    history = Path(history_path).resolve() if history_path else workspace_path / "out" / "openhtf-history"
    with start_sgfx_station_server(
        profile_id=profile_id,
        workspace=workspace_path,
        history_path=history,
        port=port,
    ) as started:
        test = make_sgfx_test(profile_id=profile_id, workspace=workspace_path, bmw_root=bmw_root, ui_mode=ui_mode)
        test.add_output_callbacks(started.server.publish_final_state)
        if open_browser:
            webbrowser.open(started.sgfx_url)
        print(f"SGFX station: {started.sgfx_url}")
        print(f"OpenHTF runtime endpoint: {started.raw_url}")
        test.execute()
        if once:
            return 0
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            return 0
