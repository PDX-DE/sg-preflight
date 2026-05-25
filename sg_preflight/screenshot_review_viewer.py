from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
from typing import Any

from sg_preflight.screenshot_triage import materialize_screenshot_triage


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


@dataclass(frozen=True)
class ScreenshotReviewItem:
    key: str
    classification: str
    visual_classification: str
    summary: str
    visual_summary: str
    expected_path: str = ""
    actual_path: str = ""
    diff_path: str = ""
    expected_uri: str = ""
    actual_uri: str = ""
    diff_uri: str = ""
    changed_pixel_ratio: float | None = None
    mean_abs_diff: float | None = None
    review_score: float | None = None
    anomaly_hints: tuple[str, ...] = ()
    manual_verdict: str = "not_run"


@dataclass(frozen=True)
class ScreenshotReviewViewer:
    profile_id: str
    project_root: str
    generated_at_utc: str
    expected_root: str
    item_count: int
    triage_json_path: str
    triage_html_path: str
    notes: tuple[str, ...]
    guardrails: tuple[str, ...]
    items: tuple[ScreenshotReviewItem, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScreenshotReviewViewerBundle:
    viewer: ScreenshotReviewViewer
    json_path: Path
    html_path: Path
    triage_json_path: Path
    triage_html_path: Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path_uri(path_value: str) -> str:
    if not path_value:
        return ""
    path = Path(path_value)
    if not path.exists():
        return ""
    return path.resolve().as_uri()


def _diff_lookup(diff_reference_roots: tuple[Path, ...]) -> dict[str, Path]:
    lookup: dict[str, Path] = {}
    for root in diff_reference_roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES:
                lookup.setdefault(path.with_suffix("").name.casefold(), path)
                try:
                    relative_key = path.relative_to(root).with_suffix("").as_posix().casefold()
                except ValueError:
                    continue
                lookup.setdefault(relative_key, path)
    return lookup


def build_screenshot_review_viewer(
    profile_id: str,
    project_root: Path,
    output_root: Path,
    *,
    expected_root: Path | None = None,
    candidate_roots: tuple[Path, ...] = (),
    diff_reference_roots: tuple[Path, ...] = (),
    priority_names: tuple[str, ...] = (),
    max_items: int = 80,
) -> ScreenshotReviewViewerBundle:
    output_root.mkdir(parents=True, exist_ok=True)
    triage_output_root = output_root / "triage"
    triage_bundle = materialize_screenshot_triage(
        profile_id,
        project_root,
        triage_output_root,
        expected_root=expected_root,
        candidate_roots=candidate_roots,
        diff_reference_roots=diff_reference_roots,
        priority_names=priority_names,
    )
    diff_lookup = _diff_lookup(diff_reference_roots)

    items: list[ScreenshotReviewItem] = []
    for pair in triage_bundle.report.pairs[:max_items]:
        diff_path = pair.diff_image_path
        if not diff_path:
            diff_path = str(
                diff_lookup.get(pair.key.casefold())
                or diff_lookup.get(Path(pair.key).with_suffix("").name.casefold())
                or ""
            )
        items.append(
            ScreenshotReviewItem(
                key=pair.key,
                classification=pair.classification,
                visual_classification=pair.visual_classification,
                summary=pair.summary,
                visual_summary=pair.visual_summary,
                expected_path=pair.baseline_path,
                actual_path=pair.candidate_path,
                diff_path=diff_path,
                expected_uri=_path_uri(pair.baseline_path),
                actual_uri=_path_uri(pair.candidate_path),
                diff_uri=_path_uri(diff_path),
                changed_pixel_ratio=pair.changed_pixel_ratio,
                mean_abs_diff=pair.mean_abs_diff,
                review_score=pair.review_score,
                anomaly_hints=pair.anomaly_hints,
            )
        )

    viewer = ScreenshotReviewViewer(
        profile_id=profile_id,
        project_root=str(project_root.resolve()),
        generated_at_utc=_utc_now(),
        expected_root=triage_bundle.report.expected_root,
        item_count=len(items),
        triage_json_path=str(triage_bundle.json_path),
        triage_html_path=str(triage_bundle.html_path),
        notes=(
            "Side-by-side viewer for local screenshot evidence.",
            "Manual review remains required.",
            "Decision: not approval — evidence only.",
            "Use expected, actual, and diff panes together before recording any reviewer verdict.",
        ),
        guardrails=(
            "Manual review remains required.",
            "Decision: not approval — evidence only.",
            "BMW Git access is read-only. SGFX never modifies BMW source.",
            "Activity log is local-only — never posted to Jira, SVN, or BMW Git.",
        ),
        items=tuple(items),
    )
    json_path = output_root / "screenshot-review-viewer.json"
    html_path = output_root / "screenshot-review-viewer.html"
    json_path.write_text(json.dumps(viewer.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    html_path.write_text(_html(viewer), encoding="utf-8")
    return ScreenshotReviewViewerBundle(
        viewer=viewer,
        json_path=json_path,
        html_path=html_path,
        triage_json_path=triage_bundle.json_path,
        triage_html_path=triage_bundle.html_path,
    )


def _image_pane(label: str, slot: str) -> str:
    return f"""
      <section class="pane" data-pane="{escape(slot)}">
        <header>
          <span>{escape(label)}</span>
          <a data-open="{escape(slot)}" href="#" target="_blank" rel="noreferrer">open</a>
        </header>
        <div class="viewport" data-viewport="{escape(slot)}">
          <div class="missing" data-missing="{escape(slot)}">missing</div>
          <img data-image="{escape(slot)}" alt="{escape(label)} screenshot">
        </div>
        <footer data-path="{escape(slot)}"></footer>
      </section>
    """


def _script_json_payload(payload: str) -> str:
    return payload.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def _html(viewer: ScreenshotReviewViewer) -> str:
    payload = _script_json_payload(json.dumps(viewer.to_dict(), ensure_ascii=False))
    item_buttons = "\n".join(
        (
            f'<button type="button" data-key="{escape(item.key)}">'
            f"<strong>{escape(item.key)}</strong>"
            f"<span>{escape(item.classification)} / {escape(item.visual_classification)}</span>"
            "</button>"
        )
        for item in viewer.items
    )
    guardrails = "".join(f"<li>{escape(line)}</li>" for line in viewer.guardrails)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Screenshot review viewer - {escape(viewer.profile_id)}</title>
  <style>
    :root {{
      --bg: #161616;
      --panel: #222;
      --panel-soft: #292929;
      --border: #3b3b3b;
      --fg: #e6e6e6;
      --muted: #aaa;
      --accent: #4ec9b0;
      --warning: #e8c07d;
    }}
    html, body {{ min-height: 100%; margin: 0; background: var(--bg); color: var(--fg); font: 14px/1.45 "Segoe UI", Arial, sans-serif; }}
    body {{ display: grid; grid-template-columns: 310px minmax(0, 1fr); }}
    aside {{ min-height: 100vh; border-right: 1px solid var(--border); background: var(--panel); padding: 18px 14px; box-sizing: border-box; }}
    main {{ min-width: 0; padding: 18px; box-sizing: border-box; }}
    h1 {{ font-size: 18px; margin: 0 0 6px; }}
    .meta, .hint, li {{ color: var(--muted); font-size: 12px; }}
    .list {{ display: flex; flex-direction: column; gap: 8px; margin-top: 14px; max-height: calc(100vh - 210px); overflow: auto; }}
    button[data-key] {{ text-align: left; border: 1px solid var(--border); border-radius: 6px; background: #1d1d1d; color: var(--fg); padding: 9px; cursor: pointer; }}
    button[data-key].active {{ border-color: var(--accent); background: #20302d; }}
    button[data-key] strong {{ display: block; overflow-wrap: anywhere; }}
    button[data-key] span {{ display: block; color: var(--muted); font-size: 12px; margin-top: 3px; }}
    .toolbar {{ display: flex; flex-wrap: wrap; align-items: center; gap: 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--panel); padding: 10px 12px; margin-bottom: 12px; }}
    .toolbar label {{ color: var(--muted); }}
    .toolbar input {{ width: 220px; }}
    .summary {{ border: 1px solid var(--border); border-radius: 8px; background: var(--panel); padding: 12px; margin-bottom: 12px; }}
    .summary h2 {{ font-size: 16px; margin: 0 0 6px; overflow-wrap: anywhere; }}
    .summary p {{ margin: 4px 0; color: var(--muted); }}
    .summary .score {{ color: var(--warning); }}
    .panes {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; min-height: 68vh; }}
    .pane {{ border: 1px solid var(--border); border-radius: 8px; background: var(--panel); min-width: 0; display: flex; flex-direction: column; }}
    .pane header {{ display: flex; justify-content: space-between; gap: 10px; padding: 9px 10px; border-bottom: 1px solid var(--border); color: var(--fg); font-weight: 650; }}
    .pane header a {{ color: var(--accent); font-weight: 400; text-decoration: none; }}
    .viewport {{ position: relative; flex: 1; min-height: 420px; overflow: hidden; background: #050505; cursor: grab; }}
    .viewport.dragging {{ cursor: grabbing; }}
    .viewport img {{ position: absolute; top: 50%; left: 50%; max-width: none; transform-origin: 0 0; user-select: none; -webkit-user-drag: none; }}
    .missing {{ position: absolute; inset: 0; display: none; align-items: center; justify-content: center; color: var(--muted); border: 1px dashed #444; margin: 16px; border-radius: 8px; }}
    .pane footer {{ min-height: 34px; border-top: 1px solid var(--border); padding: 8px 10px; color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }}
    ul {{ padding-left: 18px; margin: 10px 0 0; }}
    @media (max-width: 1180px) {{ body {{ grid-template-columns: 1fr; }} aside {{ min-height: auto; border-right: 0; border-bottom: 1px solid var(--border); }} .list {{ max-height: 240px; }} .panes {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body data-sgfx-screenshot-viewer="true">
  <aside>
    <h1>Screenshot review viewer</h1>
    <div class="meta">Profile {escape(viewer.profile_id)} | {viewer.item_count} item(s)</div>
    <ul>{guardrails}</ul>
    <div class="list" data-list>{item_buttons or '<p class="hint">No screenshot pairs were generated.</p>'}</div>
  </aside>
  <main>
    <div class="toolbar">
      <label for="zoom">Sync zoom</label>
      <input id="zoom" data-zoom type="range" min="25" max="400" value="100">
      <span data-zoom-label>100%</span>
      <button type="button" data-reset>Reset pan</button>
    </div>
    <section class="summary">
      <h2 data-title>No screenshot selected</h2>
      <p data-summary>Select a screenshot from the left list.</p>
      <p data-visual></p>
      <p class="score" data-score></p>
    </section>
    <section class="panes">
      {_image_pane("Expected", "expected")}
      {_image_pane("Actual", "actual")}
      {_image_pane("Diff", "diff")}
    </section>
  </main>
  <script id="sgfx-viewer-data" type="application/json">{payload}</script>
  <script>
    (() => {{
      const data = JSON.parse(document.getElementById('sgfx-viewer-data').textContent);
      const items = data.items || [];
      const byKey = new Map(items.map((item) => [item.key, item]));
      const title = document.querySelector('[data-title]');
      const summary = document.querySelector('[data-summary]');
      const visual = document.querySelector('[data-visual]');
      const score = document.querySelector('[data-score]');
      const zoomInput = document.querySelector('[data-zoom]');
      const zoomLabel = document.querySelector('[data-zoom-label]');
      const reset = document.querySelector('[data-reset]');
      const buttons = Array.from(document.querySelectorAll('button[data-key]'));
      const panes = ['expected', 'actual', 'diff'];
      const state = {{ scale: 1, x: 0, y: 0 }};

      const applyTransform = () => {{
        zoomLabel.textContent = `${{Math.round(state.scale * 100)}}%`;
        panes.forEach((name) => {{
          const image = document.querySelector(`[data-image="${{name}}"]`);
          if (!image || image.hidden) return;
          image.style.transform = `translate(${{state.x}}px, ${{state.y}}px) scale(${{state.scale}}) translate(-50%, -50%)`;
        }});
      }};

      const setPane = (name, uri, path) => {{
        const image = document.querySelector(`[data-image="${{name}}"]`);
        const missing = document.querySelector(`[data-missing="${{name}}"]`);
        const footer = document.querySelector(`[data-path="${{name}}"]`);
        const open = document.querySelector(`[data-open="${{name}}"]`);
        footer.textContent = path || 'missing';
        open.href = uri || '#';
        if (!uri) {{
          image.hidden = true;
          image.removeAttribute('src');
          missing.style.display = 'flex';
          return;
        }}
        missing.style.display = 'none';
        image.hidden = false;
        image.src = uri;
        image.onload = applyTransform;
      }};

      const select = (key) => {{
        const item = byKey.get(key) || items[0];
        if (!item) return;
        buttons.forEach((button) => button.classList.toggle('active', button.dataset.key === item.key));
        window.location.hash = encodeURIComponent(item.key);
        title.textContent = `${{item.key}} [${{item.classification}} / ${{item.visual_classification}}]`;
        summary.textContent = item.summary || '';
        visual.textContent = item.visual_summary || '';
        score.textContent = item.review_score ? `Review score: ${{item.review_score.toFixed(2)}}` : '';
        setPane('expected', item.expected_uri, item.expected_path);
        setPane('actual', item.actual_uri, item.actual_path);
        setPane('diff', item.diff_uri, item.diff_path);
        applyTransform();
      }};

      buttons.forEach((button) => button.addEventListener('click', () => select(button.dataset.key)));
      zoomInput.addEventListener('input', () => {{
        state.scale = Number(zoomInput.value) / 100;
        applyTransform();
      }});
      reset.addEventListener('click', () => {{
        state.x = 0;
        state.y = 0;
        applyTransform();
      }});

      document.querySelectorAll('.viewport').forEach((viewport) => {{
        let drag = null;
        viewport.addEventListener('pointerdown', (event) => {{
          drag = {{ x: event.clientX, y: event.clientY, baseX: state.x, baseY: state.y }};
          viewport.classList.add('dragging');
          viewport.setPointerCapture(event.pointerId);
        }});
        viewport.addEventListener('pointermove', (event) => {{
          if (!drag) return;
          state.x = drag.baseX + event.clientX - drag.x;
          state.y = drag.baseY + event.clientY - drag.y;
          applyTransform();
        }});
        viewport.addEventListener('pointerup', () => {{
          drag = null;
          viewport.classList.remove('dragging');
        }});
      }});

      const hashKey = decodeURIComponent(window.location.hash.replace(/^#/, ''));
      select(hashKey && byKey.has(hashKey) ? hashKey : (items[0] && items[0].key));
    }})();
  </script>
</body>
</html>
"""
