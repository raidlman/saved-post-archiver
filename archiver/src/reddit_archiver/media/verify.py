import json
import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_IMAGE_MAGIC = {
    b"\xff\xd8\xff": "jpeg",
    b"\x89PNG\r\n\x1a\n": "png",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
    b"RIFF": "webp",  # followed by "WEBP" at offset 8, checked separately
}

_VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov"}


def _looks_like_image(path: Path) -> bool:
    try:
        header = path.open("rb").read(16)
    except OSError:
        return False
    if header.startswith(b"RIFF"):
        return header[8:12] == b"WEBP"
    return any(header.startswith(magic) for magic in _IMAGE_MAGIC if not magic.startswith(b"RIFF"))


def _looks_like_video(path: Path) -> bool:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    if result.returncode != 0:
        return False
    try:
        streams = json.loads(result.stdout).get("streams", [])
    except json.JSONDecodeError:
        return False
    return any(s.get("codec_type") == "video" for s in streams)


def verify_media_files(paths: list[Path]) -> bool:
    """Re-checks actual files on disk - the DB flag caches this, never trusts it blindly."""
    for path in paths:
        if not path.exists() or path.stat().st_size == 0:
            log.warning("verify failed: %s missing or empty", path)
            return False
        if path.suffix.lower() in _VIDEO_EXTS:
            if not _looks_like_video(path):
                log.warning("verify failed: %s does not look like a valid video", path)
                return False
        elif not _looks_like_image(path):
            log.debug("verify: %s has no recognized image magic bytes (may be a non-image file, e.g. a gif->mp4)", path)
    return True


def write_sentinel(post_dir: Path) -> None:
    (post_dir / ".archive_complete").touch()
