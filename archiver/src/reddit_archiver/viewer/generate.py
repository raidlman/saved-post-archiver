import json
import logging
import shutil
from pathlib import Path

from ..config import Settings
from ..postdir import read_post_json
from ..state import Store

log = logging.getLogger(__name__)

_STATIC_ASSETS_DIR = Path(__file__).parent / "static_assets"


def _web_path(data_dir: Path, dir_path: str, relative: str) -> str:
    rel_dir = Path(dir_path).relative_to(data_dir)
    return "/" + (rel_dir / relative).as_posix()


def generate_viewer(store: Store, settings: Settings) -> None:
    settings.viewer_dir.mkdir(parents=True, exist_ok=True)

    for asset in _STATIC_ASSETS_DIR.iterdir():
        shutil.copy(asset, settings.viewer_dir / asset.name)

    entries = []
    for row in store.all_posts():
        dir_path = row["dir_path"]
        post_json = read_post_json(Path(dir_path)) if dir_path else None
        if post_json is None:
            continue

        media_files = [
            {"path": _web_path(settings.data_dir, dir_path, f["path"]), "source_url": f.get("source_url")}
            for f in post_json.get("media_files", [])
        ]
        thumbnail = None
        if post_json.get("thumbnail"):
            thumbnail = _web_path(settings.data_dir, dir_path, post_json["thumbnail"])

        body_text = None
        if post_json.get("is_self"):
            body_path = Path(dir_path) / "body.md"
            if body_path.exists():
                body_text = body_path.read_text()

        entries.append({
            "id": row["submission_id"],
            "title": post_json.get("title"),
            "author": row["author"],
            "subreddit": row["subreddit"],
            "permalink": post_json.get("permalink"),
            "url": post_json.get("url"),
            "score": row["score"],
            "created_utc": row["created_utc"],
            "over_18": bool(row["over_18"]),
            "is_self": bool(row["is_self"]),
            "is_crosspost": post_json.get("is_crosspost", False),
            "crosspost_seen_via_subreddit": post_json.get("crosspost_seen_via_subreddit"),
            "media_status": row["media_status"],
            "media_files": media_files,
            "thumbnail": thumbnail,
            "body_text": body_text,
        })

    (settings.viewer_dir / "data.json").write_text(json.dumps(entries, ensure_ascii=False))
    log.info("viewer regenerated: %d posts", len(entries))
