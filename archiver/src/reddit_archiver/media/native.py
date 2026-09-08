import logging
from pathlib import Path

import requests

log = logging.getLogger(__name__)

_IMAGE_CONTENT_TYPES = ("image/",)
_VIDEO_CONTENT_TYPES = ("video/",)


class DeadLinkError(Exception):
    """Raised when the host confirms the content no longer exists (404/410)."""


def direct_download(url: str, dest: Path, timeout: int = 30) -> bool:
    """Plain HTTP GET for content that's already a direct media link.

    Returns True on success. Raises DeadLinkError on a confirmed-dead link so
    callers can distinguish "gone forever" from "try the next tool".
    """
    try:
        resp = requests.get(url, stream=True, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    except requests.RequestException as exc:
        log.debug("direct_download transport error for %s: %s", url, exc)
        return False

    if resp.status_code in (404, 410):
        resp.close()
        raise DeadLinkError(f"{resp.status_code} for {url}")
    if resp.status_code != 200:
        resp.close()
        log.debug("direct_download got HTTP %s for %s", resp.status_code, url)
        return False

    content_type = resp.headers.get("content-type", "")
    if not (content_type.startswith(_IMAGE_CONTENT_TYPES) or content_type.startswith(_VIDEO_CONTENT_TYPES)):
        resp.close()
        log.debug("direct_download unexpected content-type %s for %s", content_type, url)
        return False

    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 256):
            f.write(chunk)
    resp.close()
    return dest.stat().st_size > 0
