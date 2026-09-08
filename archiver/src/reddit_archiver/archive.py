import logging
import time
from pathlib import Path

from .config import Settings, load_settings
from .crosspost import ResolvedSubmission, resolve_original
from .logging_setup import configure_logging
from .media.dispatch import dispatch_media
from .media.verify import verify_media_files, write_sentinel
from .postdir import post_dir, write_post_json
from .reddit_client import build_reddit, iter_saved_submissions, jitter_sleep
from .stats import RunStats
from .state import TERMINAL, TERMINAL_SUCCESS, Store
from .unsave import run_unsave_rotation
from .viewer.generate import generate_viewer

log = logging.getLogger(__name__)


def run(force_dry_run: bool = False) -> int:
    settings = load_settings()
    if force_dry_run:
        settings.dry_run = True
    configure_logging(settings.log_level)

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(settings.db_path)
    reddit = build_reddit(settings)
    stats = RunStats()

    try:
        _retry_incomplete(reddit, store, settings, stats)

        newest_first_ids: list[str] = []
        for submission in iter_saved_submissions(reddit):
            stats.saved_seen += 1
            resolved = resolve_original(reddit, submission, settings.crosspost_max_hops)
            original = resolved.submission
            newest_first_ids.append(original.id)

            existing = store.get(original.id)
            if existing is not None and existing["media_status"] in TERMINAL:
                if existing["media_status"] in TERMINAL_SUCCESS and not settings.dry_run:
                    store.refresh_score(original.id, getattr(original, "score", None))
                    dir_path = existing["dir_path"]
                    if dir_path and (Path(dir_path) / ".archive_complete").exists():
                        store.bump_verify_count(original.id)
                jitter_sleep(settings)
                continue

            _archive_one(store, settings, resolved, submission.id, stats)
            jitter_sleep(settings)

    except Exception:
        log.exception("archive pass failed - aborting before unsave/viewer regeneration")
        store.close()
        return 1

    unsaved = run_unsave_rotation(reddit, store, settings, newest_first_ids)
    stats.unsaved_this_run = unsaved

    if not settings.dry_run:
        generate_viewer(store, settings)

    summary = stats.render(store, settings.dry_run)
    log.info("\n%s", summary)
    if not settings.dry_run:
        stats.write_json(settings.last_run_stats_path, store, settings.dry_run)

    store.close()
    return 0


def _retry_incomplete(reddit, store: Store, settings: Settings, stats: RunStats) -> None:
    for submission_id in store.non_terminal_ids():
        try:
            submission = reddit.submission(id=submission_id)
            resolved = resolve_original(reddit, submission, settings.crosspost_max_hops)
            _archive_one(store, settings, resolved, submission_id, stats)
            jitter_sleep(settings)
        except Exception as exc:  # noqa: BLE001 - one bad retry must never abort the run
            log.warning("retry of interrupted submission %s failed: %s", submission_id, exc)


def _archive_one(store: Store, settings: Settings, resolved: ResolvedSubmission, reached_via_saved_id: str, stats: RunStats) -> None:
    original = resolved.submission
    subreddit = str(original.subreddit)
    created_utc = int(original.created_utc)
    title = original.title
    author = str(original.author) if original.author else "[deleted]"
    permalink = f"https://www.reddit.com{original.permalink}"
    dir_path = post_dir(settings.by_subreddit_dir, subreddit, created_utc, original.id, title)

    if settings.dry_run:
        log.info("[DRY RUN] [%s] r/%s u/%s \"%.60s\" -> would dispatch media to %s", original.id, subreddit, author, title, dir_path)
        stats.record_new("complete")
        return

    store.upsert_downloading(
        submission_id=original.id,
        reached_via_saved_id=reached_via_saved_id,
        subreddit=subreddit,
        title=title,
        author=author,
        permalink=permalink,
        score=getattr(original, "score", None),
        created_utc=created_utc,
        over_18=bool(getattr(original, "over_18", False)),
        is_self=bool(getattr(original, "is_self", False)),
        dir_path=str(dir_path),
    )

    media_dir = dir_path / "media"
    result = dispatch_media(original, media_dir, settings.max_video_size_mb)

    if getattr(original, "is_self", False):
        dir_path.mkdir(parents=True, exist_ok=True)
        (dir_path / "body.md").write_text(original.selftext or "")

    media_files_meta: list[dict] = []
    if result.media_status == "complete":
        if not verify_media_files([f.path for f in result.files]):
            result.media_status = "partial"
            result.error = "post-download verification failed"
        else:
            media_files_meta = [
                {"path": str(f.path.relative_to(dir_path)), "source_url": f.source_url}
                for f in result.files
            ]

    is_terminal_success = result.media_status in TERMINAL_SUCCESS
    wrapper_id = reached_via_saved_id if resolved.is_crosspost and reached_via_saved_id != original.id else None
    thumbnail_rel = str(result.thumbnail.relative_to(dir_path)) if result.thumbnail else None

    post_json = {
        "id": original.id,
        "title": title,
        "author": author,
        "subreddit": subreddit,
        "permalink": permalink,
        "url": original.url,
        "score": getattr(original, "score", None),
        "created_utc": created_utc,
        "over_18": bool(getattr(original, "over_18", False)),
        "is_self": bool(getattr(original, "is_self", False)),
        "is_crosspost": resolved.is_crosspost,
        "crosspost_wrapper_id": wrapper_id,
        "crosspost_seen_via_subreddit": resolved.crosspost_seen_via_subreddit,
        "crosspost_resolution_failed": resolved.crosspost_resolution_failed,
        "media_status": result.media_status,
        "media_files": media_files_meta,
        "thumbnail": thumbnail_rel,
        "archived_at": int(time.time()) if is_terminal_success else None,
        "unsaved_at": None,
    }
    write_post_json(dir_path, post_json)

    store.set_media_status(
        original.id, result.media_status, len(media_files_meta),
        last_error=result.error, mark_archived=is_terminal_success,
    )

    if is_terminal_success:
        write_sentinel(dir_path)
        store.bump_verify_count(original.id)

    if is_terminal_success:
        log_fn = log.info
    elif result.media_status == "partial":
        log_fn = log.warning
    else:
        log_fn = log.error
    error_suffix = f" error={result.error}" if result.error else ""
    log_fn("[%s] r/%s u/%s \"%.60s\" -> media_status=%s (%d files)%s", original.id, subreddit, author, title, result.media_status, len(media_files_meta), error_suffix)

    stats.record_new(result.media_status)
