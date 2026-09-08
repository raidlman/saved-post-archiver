import json
import time
from pathlib import Path

from .state import Store


class RunStats:
    def __init__(self) -> None:
        self.started_at = time.time()
        self.saved_seen = 0
        self.new_complete = 0
        self.new_link_only = 0
        self.new_partial = 0
        self.new_unavailable = 0
        self.unsaved_this_run = 0

    def record_new(self, media_status: str) -> None:
        if media_status == "complete":
            self.new_complete += 1
        elif media_status == "link_only":
            self.new_link_only += 1
        elif media_status == "partial":
            self.new_partial += 1
        elif media_status == "unavailable":
            self.new_unavailable += 1

    def render(self, store: Store, dry_run: bool) -> str:
        duration = time.time() - self.started_at
        counts = store.status_counts()
        total_archived = counts.get("complete", 0) + counts.get("link_only", 0)
        prefix = "[DRY RUN] " if dry_run else ""
        new_total = self.new_complete + self.new_link_only + self.new_partial + self.new_unavailable

        lines = [
            f"=== {prefix}reddit-archiver run summary ===",
            f"Saved posts seen this run:      {self.saved_seen}",
            f"New posts processed:            {new_total}",
            f"  complete:                     {self.new_complete}",
            f"  link_only:                    {self.new_link_only}",
            f"  partial (will retry):         {self.new_partial}",
            f"  unavailable (needs review):   {self.new_unavailable}",
            f"Posts unsaved this run:         {self.unsaved_this_run}",
            f"Run duration:                   {int(duration // 60)}m{int(duration % 60)}s",
            "--- Cumulative totals ---",
            f"Total archived (complete+link_only): {total_archived}",
            f"Total needing manual review (unavailable): {counts.get('unavailable', 0)}",
            f"Total still pending/partial:    {counts.get('pending', 0) + counts.get('downloading', 0) + counts.get('partial', 0)}",
            f"Total ever unsaved by this tool: {store.total_unsaved()}",
        ]
        return "\n".join(lines)

    def write_json(self, path: Path, store: Store, dry_run: bool) -> None:
        counts = store.status_counts()
        payload = {
            "generated_at": int(time.time()),
            "dry_run": dry_run,
            "saved_seen": self.saved_seen,
            "new_complete": self.new_complete,
            "new_link_only": self.new_link_only,
            "new_partial": self.new_partial,
            "new_unavailable": self.new_unavailable,
            "unsaved_this_run": self.unsaved_this_run,
            "status_counts": counts,
            "total_unsaved": store.total_unsaved(),
        }
        path.write_text(json.dumps(payload, indent=2))
