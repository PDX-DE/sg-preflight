from __future__ import annotations

import re
import subprocess
from pathlib import Path

from sg_preflight.profiles import mirror_repo_root, resolve_source_repo_root

RACO_PROBE_SCENE_CANDIDATES = (
    Path("AmbientLayer/BMW_Default/main/Main.rca"),
    Path("BaseScene.rca"),
)


def representative_raco_scene(root: Path) -> Path:
    resolved_root = root.resolve()
    source_root = resolve_source_repo_root(resolved_root)
    fallback_mirror_root = mirror_repo_root(resolved_root)
    candidate_roots: list[Path] = []
    for repo_root in (source_root, fallback_mirror_root):
        resolved_repo_root = repo_root.resolve()
        if resolved_repo_root in candidate_roots:
            continue
        candidate_roots.append(resolved_repo_root)

    for repo_root in candidate_roots:
        for relative_path in RACO_PROBE_SCENE_CANDIDATES:
            candidate = repo_root / relative_path
            if candidate.exists():
                return candidate

        ambient_root = repo_root / "AmbientLayer"
        if ambient_root.exists():
            match = next(ambient_root.rglob("Main.rca"), None)
            if match is not None:
                return match

        if repo_root.exists():
            match = next(repo_root.rglob("*.rca"), None)
            if match is not None:
                return match

    return Path()


def _sanitize_probe_output(stdout: str, stderr: str, return_code: int) -> str:
    combined = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part.strip()).strip()
    if not combined:
        return f"Probe exited with code {return_code}."
    single_line = re.sub(r"\x1b\[[0-9;]*m", "", " ".join(combined.split()))
    for needle in ("File Load Error:", "Project feature level", "Usage:"):
        match_index = single_line.find(needle)
        if match_index != -1:
            single_line = single_line[match_index:]
            break
    if len(single_line) > 600:
        return single_line[:597] + "..."
    return single_line


def probe_raco_runtime(
    executable: Path,
    scene_path: Path,
    *,
    gui: bool,
    timeout_seconds: float = 12.0,
) -> dict[str, str]:
    probe_payload = {
        "status": "missing",
        "detail": "",
        "probe_path": str(scene_path) if scene_path else "",
    }
    if not executable.exists():
        probe_payload["detail"] = "Executable path is not configured."
        return probe_payload

    if not scene_path.exists():
        probe_payload["status"] = "available"
        probe_payload["detail"] = "No representative SG .rca scene was found for a compatibility probe."
        return probe_payload

    args = [str(executable)]
    if gui:
        args.extend(("--project", str(scene_path)))
    else:
        args.extend(("-p", str(scene_path), "-l", "3"))

    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        probe_payload["status"] = "available"
        probe_payload["detail"] = (
            f"Representative SG scene probe stayed open beyond {int(timeout_seconds)}s and is treated as launchable."
        )
        return probe_payload
    except OSError as exc:
        probe_payload["detail"] = str(exc)
        return probe_payload

    probe_payload["detail"] = _sanitize_probe_output(completed.stdout, completed.stderr, completed.returncode)
    probe_payload["status"] = "available" if completed.returncode == 0 else "incompatible"
    return probe_payload
