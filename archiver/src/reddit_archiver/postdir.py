import json
import re
from datetime import UTC, datetime
from pathlib import Path

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(title: str, max_len: int = 60) -> str:
    slug = _SLUG_RE.sub("-", title.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "untitled"


def folder_name(created_utc: int, submission_id36: str, title: str) -> str:
    date_str = datetime.fromtimestamp(created_utc, tz=UTC).strftime("%Y-%m-%d")
    return f"{date_str}_{submission_id36}_{slugify(title)}"


def post_dir(by_subreddit_dir: Path, subreddit: str, created_utc: int, submission_id36: str, title: str) -> Path:
    return by_subreddit_dir / subreddit / folder_name(created_utc, submission_id36, title)


def write_post_json(post_dir_path: Path, data: dict) -> None:
    post_dir_path.mkdir(parents=True, exist_ok=True)
    (post_dir_path / "post.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))


def read_post_json(post_dir_path: Path) -> dict | None:
    path = post_dir_path / "post.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
