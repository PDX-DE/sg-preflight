from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import struct
import subprocess
import threading
import time
from typing import Callable

from PySide6.QtCore import QObject, Signal

from sg_preflight.desktop.preview_image_provider import PreviewImageProvider
from sg_preflight.profiles import RunProfile


PREVIEW_FRAME_LIMIT = 48
PREVIEW_WIDTH = 960
PREVIEW_HEIGHT = 540
PREVIEW_TIMEOUT_SECONDS = 30.0
PREVIEW_CACHE_LIMIT_BYTES = 256 * 1024 * 1024
_PROFILE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_CACHE_KEY_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_FRAME_NAME_PATTERN = re.compile(r"^frame-[0-9]{3}\.png$")
_HELPER_NAME = "sgfx_cine_ramses_preview_cli.exe"
_MANIFEST_KEYS = {
    "schema_version",
    "state",
    "frame_count",
    "width",
    "height",
    "frames",
    "ramses_version",
    "feature_level",
}


class PreviewRejected(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PreviewPublicState:
    state: str = "fallback"
    token: str = ""
    frame_count: int = 0
    frame_index: int = 0
    label: str = "Static profile preview"


@dataclass(frozen=True, slots=True)
class PreviewRequestHandle:
    request_id: str


@dataclass(frozen=True, slots=True)
class _PreviewRequest:
    request_id: str
    generation: int
    profile_id: str
    scene_path: Path
    source_sha256: str
    output_root: Path
    frame_limit: int
    reduced_motion: bool


@dataclass(frozen=True, slots=True)
class _PendingPreview:
    request_id: str
    generation: int
    profile_id: str
    profile: RunProfile | None
    reduced_motion: bool
    allow_launch: bool


@dataclass(frozen=True, slots=True)
class _AcceptedPreview:
    cache_key: str
    frames: tuple[Path, ...]


ProfileResolver = Callable[[str], RunProfile | None]
Runner = Callable[..., object]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse(path: Path) -> bool:
    try:
        metadata = os.lstat(path)
    except OSError:
        return True
    if stat.S_ISLNK(metadata.st_mode):
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _contained(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        return False


def _accepted_file(path: Path, root: Path) -> Path:
    lexical_root = root.absolute()
    lexical = path.absolute()
    if not lexical.is_relative_to(lexical_root):
        raise PreviewRejected("file containment")
    current = lexical_root
    if _is_reparse(current):
        raise PreviewRejected("linked root")
    for part in lexical.relative_to(lexical_root).parts:
        current = current / part
        if _is_reparse(current):
            raise PreviewRejected("linked path")
    resolved_root = root.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
        raise PreviewRejected("file containment")
    return resolved


def _png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise PreviewRejected("frame format")
    return struct.unpack(">II", header[16:24])


class PreviewCoordinator(QObject):
    state_changed = Signal(object)

    def __init__(
        self,
        *,
        cache_root: Path | str,
        helper_path: Path | str,
        image_provider: PreviewImageProvider,
        profile_resolver: ProfileResolver | None = None,
        runner: Runner | None = None,
        cache_limit_bytes: int = PREVIEW_CACHE_LIMIT_BYTES,
        timeout_seconds: float = PREVIEW_TIMEOUT_SECONDS,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if cache_limit_bytes < 1:
            raise ValueError("cache_limit_bytes must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._cache_root = Path(cache_root).resolve()
        self._helper_path = Path(helper_path).resolve()
        self._image_provider = image_provider
        self._profile_resolver = profile_resolver
        self._runner = runner
        self._cache_limit_bytes = int(cache_limit_bytes)
        self._timeout_seconds = float(timeout_seconds)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sgfx-preview")
        self._lock = threading.RLock()
        self._state = PreviewPublicState()
        self._current_request_id = ""
        self._generation = 0
        self._profile_id = ""
        self._futures: set[Future[_AcceptedPreview]] = set()
        self._active_process: subprocess.Popen[str] | None = None
        self._active_runner: object | None = None
        self._closed = False

    def public_state(self) -> PreviewPublicState:
        with self._lock:
            return self._state

    def request(
        self,
        *,
        profile: RunProfile,
        generation: int,
        reduced_motion: bool,
        allow_launch: bool = True,
    ) -> PreviewRequestHandle:
        return self._start(
            _PendingPreview(
                request_id=secrets.token_urlsafe(18),
                generation=int(generation),
                profile_id=str(profile.profile_id),
                profile=profile,
                reduced_motion=bool(reduced_motion),
                allow_launch=bool(allow_launch),
            )
        )

    def request_profile(
        self,
        profile_id: str,
        *,
        generation: int,
        reduced_motion: bool,
        allow_launch: bool,
    ) -> PreviewRequestHandle:
        return self._start(
            _PendingPreview(
                request_id=secrets.token_urlsafe(18),
                generation=int(generation),
                profile_id=str(profile_id),
                profile=None,
                reduced_motion=bool(reduced_motion),
                allow_launch=bool(allow_launch),
            )
        )

    def _start(self, pending: _PendingPreview) -> PreviewRequestHandle:
        self._stop_active()
        with self._lock:
            if self._closed:
                return PreviewRequestHandle(pending.request_id)
            self._current_request_id = pending.request_id
            self._generation = pending.generation
            self._profile_id = pending.profile_id
            self._image_provider.clear()
            self._state = PreviewPublicState("loading", "", 0, 0, "Preparing 3D profile preview")
            future = self._executor.submit(self._prepare, pending)
            self._futures.add(future)
            future.add_done_callback(
                lambda completed, request=pending: self._complete(request, completed)
            )
        self.state_changed.emit(self._state)
        return PreviewRequestHandle(pending.request_id)

    def invalidate(self, *, generation: int) -> None:
        self._stop_active()
        with self._lock:
            if self._closed:
                return
            self._current_request_id = ""
            self._generation = int(generation)
            self._profile_id = ""
            self._image_provider.clear()
            self._state = PreviewPublicState()
        self.state_changed.emit(self._state)

    def preempt(self) -> None:
        with self._lock:
            generation = self._generation
        self.invalidate(generation=generation)

    def select_frame(self, frame_index: int) -> bool:
        with self._lock:
            if self._closed or self._state.state != "ready" or self._state.frame_count < 1:
                return False
            index = max(0, min(int(frame_index), self._state.frame_count - 1))
            if index == self._state.frame_index:
                return True
            self._state = PreviewPublicState(
                self._state.state,
                self._state.token,
                self._state.frame_count,
                index,
                self._state.label,
            )
            state = self._state
        self.state_changed.emit(state)
        return True

    def wait_for_idle(self, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        while True:
            with self._lock:
                futures = tuple(self._futures)
            if not futures:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            wait(futures, timeout=remaining)

    def shutdown(self) -> None:
        self._stop_active()
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._current_request_id = ""
            self._image_provider.clear()
            self._state = PreviewPublicState()
            futures = tuple(self._futures)
        for future in futures:
            future.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _stop_active(self) -> None:
        with self._lock:
            process = self._active_process
            runner = self._active_runner
            current_future = next((future for future in self._futures if not future.done()), None)
        if current_future is not None:
            current_future.cancel()
        if process is not None:
            try:
                process.terminate()
            except OSError:
                pass
        terminate = getattr(runner, "terminate", None)
        if callable(terminate):
            try:
                terminate()
            except RuntimeError:
                pass

    def _resolve_profile(self, pending: _PendingPreview) -> RunProfile:
        profile = pending.profile
        if profile is None and self._profile_resolver is not None:
            profile = self._profile_resolver(pending.profile_id)
        if not isinstance(profile, RunProfile):
            raise PreviewRejected("profile")
        if (
            not _PROFILE_PATTERN.fullmatch(profile.profile_id)
            or profile.profile_id.casefold() != pending.profile_id.casefold()
        ):
            raise PreviewRejected("profile")
        return profile

    def _prepare(self, pending: _PendingPreview) -> _AcceptedPreview:
        profile = self._resolve_profile(pending)
        project_root = profile.source_project_root().resolve()
        scene_path = _accepted_file(project_root / "export" / "exported.ramses", project_root)
        helper_path = self._helper_path
        if helper_path.name != _HELPER_NAME:
            raise PreviewRejected("helper")
        helper_path = _accepted_file(helper_path, helper_path.parent)
        frame_limit = 1 if pending.reduced_motion else PREVIEW_FRAME_LIMIT
        source_sha256 = _file_sha256(scene_path)
        helper_sha256 = _file_sha256(helper_path)
        cache_key = hashlib.sha256(
            json.dumps(
                {
                    "schema_version": 1,
                    "profile_id": profile.profile_id,
                    "source_sha256": source_sha256,
                    "helper_sha256": helper_sha256,
                    "frame_limit": frame_limit,
                    "width": PREVIEW_WIDTH,
                    "height": PREVIEW_HEIGHT,
                    "reduced_motion": pending.reduced_motion,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if not self._cache_root.exists():
            if not pending.allow_launch:
                raise PreviewRejected("cache miss")
            self._cache_root.mkdir(parents=True, exist_ok=True)
        if _is_reparse(self._cache_root):
            raise PreviewRejected("cache root")
        cache_entry = self._cache_root / cache_key
        request = _PreviewRequest(
            pending.request_id,
            pending.generation,
            profile.profile_id,
            scene_path,
            source_sha256,
            cache_entry,
            frame_limit,
            pending.reduced_motion,
        )
        try:
            frames = self._accepted_frames(cache_entry, request)
        except PreviewRejected:
            frames = ()
        if frames:
            try:
                os.utime(cache_entry, None)
            except OSError:
                pass
            self._evict_cache(keep=cache_key)
            return _AcceptedPreview(cache_key, frames)
        if not pending.allow_launch:
            raise PreviewRejected("cache miss")

        pending_root = self._cache_root / f".pending-{pending.request_id}"
        self._remove_generated(pending_root)
        pending_root.mkdir(parents=True, exist_ok=False)
        request = _PreviewRequest(
            request.request_id,
            request.generation,
            request.profile_id,
            request.scene_path,
            request.source_sha256,
            pending_root,
            request.frame_limit,
            request.reduced_motion,
        )
        command = (
            str(helper_path),
            "--scene",
            str(scene_path),
            "--output-root",
            str(pending_root),
            "--width",
            str(PREVIEW_WIDTH),
            "--height",
            str(PREVIEW_HEIGHT),
            "--frames",
            str(frame_limit),
            *(("--reduced-motion",) if pending.reduced_motion else ()),
        )
        try:
            return_code = self._invoke_runner(request.request_id, command)
            if return_code != 0:
                raise PreviewRejected("helper exit")
            if _file_sha256(scene_path) != request.source_sha256 or _file_sha256(helper_path) != helper_sha256:
                raise PreviewRejected("input changed")
            accepted = self._accepted_frames(pending_root, request)
            self._remove_generated(cache_entry)
            pending_root.replace(cache_entry)
            frames = tuple(cache_entry / frame.name for frame in accepted)
            self._evict_cache(keep=cache_key)
            return _AcceptedPreview(cache_key, frames)
        except Exception:
            self._remove_generated(pending_root)
            raise

    def _invoke_runner(self, request_id: str, command: tuple[str, ...]) -> int:
        creationflags = 0
        if os.name == "nt":
            creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) | int(
                getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
            )
        runner = self._runner
        if runner is not None:
            with self._lock:
                if request_id == self._current_request_id:
                    self._active_runner = runner
            try:
                result = runner(
                    command,
                    timeout=self._timeout_seconds,
                    creationflags=creationflags,
                )
            finally:
                with self._lock:
                    if self._active_runner is runner:
                        self._active_runner = None
            return int(getattr(result, "returncode", result))

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            cwd=str(self._helper_path.parent),
            creationflags=creationflags,
        )
        with self._lock:
            if request_id == self._current_request_id:
                self._active_process = process
        try:
            process.communicate(timeout=self._timeout_seconds)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
            raise
        finally:
            with self._lock:
                if self._active_process is process:
                    self._active_process = None
        return int(process.returncode or 0)

    def _accepted_frames(
        self,
        output_root: Path,
        request: _PreviewRequest,
    ) -> tuple[Path, ...]:
        if not output_root.is_dir() or _is_reparse(output_root):
            raise PreviewRejected("output")
        manifest_path = _accepted_file(
            output_root / "preview-manifest.json",
            output_root,
        )
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise PreviewRejected("manifest") from error
        if not isinstance(payload, dict) or set(payload) != _MANIFEST_KEYS:
            raise PreviewRejected("manifest shape")
        frame_names = payload.get("frames")
        frame_count = payload.get("frame_count")
        width = payload.get("width")
        height = payload.get("height")
        if (
            payload.get("schema_version") != 1
            or payload.get("state") != "rendered"
            or not isinstance(frame_names, list)
            or isinstance(frame_count, bool)
            or not isinstance(frame_count, int)
            or frame_count != len(frame_names)
            or not 1 <= frame_count <= request.frame_limit
            or isinstance(width, bool)
            or not isinstance(width, int)
            or isinstance(height, bool)
            or not isinstance(height, int)
            or not 1 <= width <= PREVIEW_WIDTH
            or not 1 <= height <= PREVIEW_HEIGHT
            or (request.reduced_motion and frame_count != 1)
            or not isinstance(payload.get("ramses_version"), str)
            or not 1 <= len(payload.get("ramses_version", "")) <= 128
            or isinstance(payload.get("feature_level"), bool)
            or not isinstance(payload.get("feature_level"), int)
            or payload.get("feature_level", -1) < 0
        ):
            raise PreviewRejected("manifest values")
        frames: list[Path] = []
        frame_bytes = 0
        expected_names = {"preview-manifest.json", *frame_names}
        try:
            output_items = tuple(output_root.iterdir())
        except OSError as error:
            raise PreviewRejected("output listing") from error
        if (
            {item.name for item in output_items} != expected_names
            or any(not item.is_file() or _is_reparse(item) for item in output_items)
        ):
            raise PreviewRejected("unexpected output")
        for name in frame_names:
            if not isinstance(name, str) or not _FRAME_NAME_PATTERN.fullmatch(name):
                raise PreviewRejected("frame name")
            frame = _accepted_file(output_root / name, output_root)
            dimensions = _png_dimensions(frame)
            if dimensions != (width, height):
                raise PreviewRejected("frame dimensions")
            frame_bytes += frame.stat().st_size
            frames.append(frame)
        if frame_bytes > self._cache_limit_bytes:
            raise PreviewRejected("cache budget")
        return tuple(frames)

    def _remove_generated(self, path: Path) -> None:
        if not path.exists() or not _contained(path, self._cache_root) or _is_reparse(path):
            return
        name = path.name
        if not (name.startswith(".pending-") or _CACHE_KEY_PATTERN.fullmatch(name)):
            return
        try:
            shutil.rmtree(path)
        except OSError:
            pass

    def _evict_cache(self, *, keep: str) -> None:
        entries: list[tuple[float, int, Path]] = []
        total = 0
        try:
            candidates = tuple(self._cache_root.iterdir())
        except OSError:
            return
        for candidate in candidates:
            if (
                not candidate.is_dir()
                or not _CACHE_KEY_PATTERN.fullmatch(candidate.name)
                or _is_reparse(candidate)
            ):
                continue
            size = 0
            safe = True
            for item in candidate.rglob("*"):
                if _is_reparse(item):
                    safe = False
                    break
                if item.is_file():
                    size += item.stat().st_size
            if not safe:
                continue
            total += size
            entries.append((candidate.stat().st_mtime, size, candidate))
        for _modified, size, candidate in sorted(entries):
            if total <= self._cache_limit_bytes:
                break
            if candidate.name == keep:
                continue
            self._remove_generated(candidate)
            total -= size

    def _complete(
        self,
        pending: _PendingPreview,
        future: Future[_AcceptedPreview],
    ) -> None:
        try:
            accepted = future.result()
        except Exception:
            accepted = None
        with self._lock:
            self._futures.discard(future)
            if (
                self._closed
                or pending.request_id != self._current_request_id
                or pending.generation != self._generation
                or pending.profile_id.casefold() != self._profile_id.casefold()
            ):
                return
            self._current_request_id = ""
            if accepted is None:
                self._image_provider.clear()
                self._state = PreviewPublicState()
            else:
                token = secrets.token_urlsafe(24)
                if not self._image_provider.register(token, accepted.frames):
                    self._state = PreviewPublicState()
                else:
                    self._state = PreviewPublicState(
                        "ready",
                        token,
                        len(accepted.frames),
                        0,
                        "3D profile preview",
                    )
            state = self._state
        self.state_changed.emit(state)
