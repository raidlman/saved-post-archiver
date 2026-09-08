import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .native import DeadLinkError, direct_download

log = logging.getLogger(__name__)

DIRECT_IMAGE_HOSTS = ("i.redd.it", "i.imgur.com", "preview.redd.it")
DIRECT_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")

_DEAD_MARKERS = (
    "404", "410", "not found", "unavailable", "has been removed",
    "deleted", "no longer exist", "this post has been removed",
)


class DeadMedia(Exception):
    """Host confirmed the content is gone - permanent, not retried."""


@dataclass
class MediaFile:
    path: Path  # absolute path in the final post directory
    source_url: str | None = None


@dataclass
class DispatchResult:
    media_status: str  # complete | partial | unavailable | link_only
    files: list[MediaFile] = field(default_factory=list)
    thumbnail: Path | None = None
    error: str | None = None


def _run(cmd: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    log.debug("running: %s", " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _looks_dead(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(marker in lowered for marker in _DEAD_MARKERS)


def _last_error_line(stderr: str) -> str:
    lines = [line for line in stderr.strip().splitlines() if line.strip()]
    return lines[-1] if lines else "unknown error"


def _try_ytdlp(url: str, tmp_dir: Path, max_video_size_mb: int) -> list[tuple[Path, str | None]] | None:
    cmd = [
        "yt-dlp", "--no-playlist", "--no-warnings", "--restrict-filenames",
        "--max-filesize", f"{max_video_size_mb}M",
        "--write-info-json", "--write-thumbnail",
        "--merge-output-format", "mp4",
        "-o", str(tmp_dir / "%(autonumber)03d.%(ext)s"),
        url,
    ]
    result = _run(cmd)
    if result.returncode != 0:
        if _looks_dead(result.stderr):
            raise DeadMedia(_last_error_line(result.stderr))
        log.debug("yt-dlp declined %s: %s", url, _last_error_line(result.stderr))
        return None
    return _collect_from_infojson(tmp_dir)


def _try_gallerydl(url: str, tmp_dir: Path) -> list[tuple[Path, str | None]] | None:
    cmd = [
        "gallery-dl", "--dest", str(tmp_dir), "--write-metadata",
        "-o", "filename={num:>03}.{extension}",
        url,
    ]
    result = _run(cmd)
    if result.returncode != 0:
        if _looks_dead(result.stderr):
            raise DeadMedia(_last_error_line(result.stderr))
        log.debug("gallery-dl declined %s: %s", url, _last_error_line(result.stderr))
        return None
    files = _collect_from_gdl_json(tmp_dir)
    return files or None


def _collect_from_infojson(tmp_dir: Path) -> list[tuple[Path, str | None]]:
    files: list[tuple[Path, str | None]] = []
    for info_path in sorted(tmp_dir.glob("*.info.json")):
        try:
            data = json.loads(info_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        stem = info_path.name[: -len(".info.json")]
        ext = data.get("ext")
        media_path = tmp_dir / f"{stem}.{ext}" if ext else None
        if media_path is None or not media_path.exists():
            # fall back to a glob, excluding the thumbnail (image ext) and sidecar json
            media_path = next(
                (p for p in tmp_dir.glob(f"{stem}.*")
                 if ".info" not in p.name and p.suffix.lower() not in (".json", *DIRECT_IMAGE_EXTS)),
                None,
            )
        if media_path is None:
            continue
        source_url = data.get("url") or data.get("webpage_url")
        files.append((media_path, source_url))
    return files


def _collect_from_gdl_json(tmp_dir: Path) -> list[tuple[Path, str | None]]:
    files: list[tuple[Path, str | None]] = []
    for json_path in sorted(tmp_dir.glob("*.json")):
        media_path = tmp_dir / json_path.stem
        if not media_path.exists():
            continue
        try:
            data = json.loads(json_path.read_text())
        except (json.JSONDecodeError, OSError):
            data = {}
        source_url = data.get("url")
        files.append((media_path, source_url))
    return files


def _pick_thumbnail(tmp_dir: Path, video_paths: list[Path]) -> Path | None:
    for video_path in video_paths:
        candidate = next(
            (p for p in tmp_dir.glob(f"{video_path.stem}.*") if p != video_path and p.suffix.lower() in DIRECT_IMAGE_EXTS),
            None,
        )
        if candidate is not None:
            return candidate
    return None


def _place_files(tmp_files: list[tuple[Path, str | None]], media_dir: Path, thumbnail_src: Path | None) -> DispatchResult:
    media_dir.mkdir(parents=True, exist_ok=True)
    placed: list[MediaFile] = []
    for idx, (src, source_url) in enumerate(sorted(tmp_files, key=lambda t: t[0].name), start=1):
        dest = media_dir / f"{idx:03d}{src.suffix.lower()}"
        shutil.move(str(src), dest)
        placed.append(MediaFile(path=dest, source_url=source_url))

    thumbnail_dest = None
    if thumbnail_src is not None and thumbnail_src.exists():
        thumbnail_dest = media_dir / f"thumbnail{thumbnail_src.suffix.lower()}"
        shutil.move(str(thumbnail_src), thumbnail_dest)

    return DispatchResult(media_status="complete", files=placed, thumbnail=thumbnail_dest)


def dispatch_media(submission, media_dir: Path, max_video_size_mb: int) -> DispatchResult:
    """Implements the dispatch cascade from the plan, ordered to maximize capture.

    `submission` is the already crosspost-resolved PRAW Submission.
    """
    if getattr(submission, "is_self", False):
        return DispatchResult(media_status="link_only", files=[])

    url = submission.url

    with tempfile.TemporaryDirectory(prefix="reddit-archiver-") as tmp:
        tmp_dir = Path(tmp)

        try:
            if getattr(submission, "is_gallery", False):
                found = _try_gallerydl(url, tmp_dir)
                if found:
                    return _place_files(found, media_dir, None)

            elif getattr(submission, "is_video", False):
                found = _try_ytdlp(url, tmp_dir, max_video_size_mb)
                if found:
                    video_paths = [p for p, _ in found]
                    thumb = _pick_thumbnail(tmp_dir, video_paths)
                    return _place_files(found, media_dir, thumb)

            elif any(host in url for host in DIRECT_IMAGE_HOSTS) or url.lower().endswith(DIRECT_IMAGE_EXTS):
                dest = media_dir / f"001{Path(url).suffix.lower() or '.jpg'}"
                try:
                    if direct_download(url, dest):
                        return DispatchResult(media_status="complete", files=[MediaFile(path=dest)])
                except DeadLinkError as exc:
                    raise DeadMedia(str(exc)) from exc
                found = _try_gallerydl(url, tmp_dir)
                if found:
                    return _place_files(found, media_dir, None)

            else:
                found = _try_ytdlp(url, tmp_dir, max_video_size_mb)
                if found:
                    video_paths = [p for p, _ in found]
                    thumb = _pick_thumbnail(tmp_dir, video_paths)
                    return _place_files(found, media_dir, thumb)

                found = _try_gallerydl(url, tmp_dir)
                if found:
                    return _place_files(found, media_dir, None)

                dest = media_dir / f"001{Path(url).suffix.lower() or '.bin'}"
                try:
                    if direct_download(url, dest):
                        return DispatchResult(media_status="complete", files=[MediaFile(path=dest)])
                except DeadLinkError as exc:
                    raise DeadMedia(str(exc)) from exc

        except DeadMedia as exc:
            return DispatchResult(media_status="unavailable", error=str(exc))
        except subprocess.TimeoutExpired as exc:
            return DispatchResult(media_status="partial", error=f"timeout: {exc}")

    return DispatchResult(media_status="link_only", files=[])
