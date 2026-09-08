import sqlite3
import time
from collections.abc import Iterable
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
  submission_id        TEXT PRIMARY KEY,
  reached_via_saved_id TEXT,
  subreddit            TEXT NOT NULL,
  title                TEXT,
  author                TEXT,
  permalink             TEXT,
  score                 INTEGER,
  created_utc           INTEGER,
  over_18               INTEGER,
  is_self               INTEGER,
  media_status          TEXT NOT NULL DEFAULT 'pending',
  media_file_count      INTEGER DEFAULT 0,
  dir_path              TEXT,
  first_seen_saved_at   INTEGER,
  archived_at           INTEGER,
  verify_count          INTEGER DEFAULT 0,
  unsaved_at            INTEGER,
  last_error            TEXT
);
"""

TERMINAL_SUCCESS = ("complete", "link_only")
TERMINAL_DEAD = ("unavailable",)
TERMINAL = TERMINAL_SUCCESS + TERMINAL_DEAD


class Store:
    def __init__(self, db_path: Path, read_only: bool = False):
        uri = f"file:{db_path}?mode=ro" if read_only else f"file:{db_path}"
        self._conn = sqlite3.connect(uri, uri=True)
        self._conn.row_factory = sqlite3.Row
        if not read_only:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def get(self, submission_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM posts WHERE submission_id = ?", (submission_id,)
        ).fetchone()

    def upsert_downloading(
        self,
        submission_id: str,
        reached_via_saved_id: str,
        subreddit: str,
        title: str,
        author: str,
        permalink: str,
        score: int | None,
        created_utc: int,
        over_18: bool,
        is_self: bool,
        dir_path: str,
    ) -> None:
        now = int(time.time())
        self._conn.execute(
            """
            INSERT INTO posts (
                submission_id, reached_via_saved_id, subreddit, title, author,
                permalink, score, created_utc, over_18, is_self, media_status,
                dir_path, first_seen_saved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'downloading', ?, ?)
            ON CONFLICT(submission_id) DO UPDATE SET
                reached_via_saved_id = excluded.reached_via_saved_id,
                score = excluded.score,
                media_status = 'downloading'
            """,
            (
                submission_id, reached_via_saved_id, subreddit, title, author,
                permalink, score, created_utc, int(over_18), int(is_self),
                dir_path, now,
            ),
        )
        self._conn.commit()

    def set_media_status(
        self,
        submission_id: str,
        media_status: str,
        media_file_count: int = 0,
        last_error: str | None = None,
        mark_archived: bool = False,
    ) -> None:
        now = int(time.time()) if mark_archived else None
        self._conn.execute(
            """
            UPDATE posts
            SET media_status = ?, media_file_count = ?, last_error = ?,
                archived_at = COALESCE(?, archived_at)
            WHERE submission_id = ?
            """,
            (media_status, media_file_count, last_error, now, submission_id),
        )
        self._conn.commit()

    def bump_verify_count(self, submission_id: str) -> None:
        self._conn.execute(
            "UPDATE posts SET verify_count = verify_count + 1 WHERE submission_id = ?",
            (submission_id,),
        )
        self._conn.commit()

    def refresh_score(self, submission_id: str, score: int | None) -> None:
        self._conn.execute(
            "UPDATE posts SET score = ? WHERE submission_id = ?", (score, submission_id)
        )
        self._conn.commit()

    def mark_unsaved(self, submission_id: str) -> None:
        self._conn.execute(
            "UPDATE posts SET unsaved_at = ? WHERE submission_id = ?",
            (int(time.time()), submission_id),
        )
        self._conn.commit()

    def non_terminal_ids(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT submission_id FROM posts WHERE media_status IN ('pending', 'downloading')"
        ).fetchall()
        return [r["submission_id"] for r in rows]

    def unsave_candidates(self, ordered_submission_ids: Iterable[str], min_verify_count: int, batch_size: int) -> list[str]:
        candidates: list[str] = []
        for submission_id in ordered_submission_ids:
            if len(candidates) >= batch_size:
                break
            row = self.get(submission_id)
            if row is None:
                continue
            if row["unsaved_at"] is not None:
                continue
            if row["media_status"] not in TERMINAL_SUCCESS:
                continue
            if row["verify_count"] < min_verify_count:
                continue
            candidates.append(submission_id)
        return candidates

    def status_counts(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT media_status, COUNT(*) AS n FROM posts GROUP BY media_status"
        ).fetchall()
        return {r["media_status"]: r["n"] for r in rows}

    def total_unsaved(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM posts WHERE unsaved_at IS NOT NULL"
        ).fetchone()
        return row["n"]

    def all_posts(self) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM posts ORDER BY created_utc DESC"
        ).fetchall()
