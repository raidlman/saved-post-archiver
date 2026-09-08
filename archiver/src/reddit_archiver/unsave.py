import logging

import praw

from .config import Settings
from .reddit_client import call_with_ratelimit_retry, jitter_sleep
from .state import Store

log = logging.getLogger(__name__)


def run_unsave_rotation(
    reddit: praw.Reddit,
    store: Store,
    settings: Settings,
    newest_first_submission_ids: list[str],
) -> int:
    """Unsaves the oldest-of-the-newest fully-verified archives, freeing up
    room in Reddit's ~1000-item saved window for older posts to surface on
    the *next* run. See the plan doc for why this must start from the newest
    end, and why nothing here re-fetches saved() within the same run.
    """
    candidates = store.unsave_candidates(
        newest_first_submission_ids,
        min_verify_count=settings.unsave_min_verify_count,
        batch_size=settings.unsave_batch_size,
    )

    if settings.dry_run:
        for submission_id in candidates:
            log.info("[DRY RUN] would unsave %s", submission_id)
        return len(candidates)

    unsaved_count = 0
    for submission_id in candidates:
        row = store.get(submission_id)
        if row is None or not _files_still_present(row):
            log.warning("skipping unsave of %s - live filesystem re-check failed", submission_id)
            continue

        try:
            submission = reddit.submission(id=submission_id)
            call_with_ratelimit_retry(submission.unsave)
        except Exception as exc:  # noqa: BLE001 - a failed unsave must never abort the run
            log.warning("unsave failed for %s: %s", submission_id, exc)
            store.set_media_status(submission_id, row["media_status"], row["media_file_count"], last_error=str(exc))
            continue

        store.mark_unsaved(submission_id)
        log.info("unsave: [%s] r/%s verified complete (verify_count=%s) -> unsaved", submission_id, row["subreddit"], row["verify_count"])
        unsaved_count += 1
        jitter_sleep(settings)

    return unsaved_count


def _files_still_present(row) -> bool:
    from pathlib import Path

    dir_path = row["dir_path"]
    if not dir_path:
        return False
    sentinel = Path(dir_path) / ".archive_complete"
    return sentinel.exists()
