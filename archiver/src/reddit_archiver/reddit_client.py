import logging
import random
import time
from collections.abc import Iterator

import praw
import prawcore

from .config import Settings

log = logging.getLogger(__name__)


def build_reddit(settings: Settings) -> praw.Reddit:
    return praw.Reddit(
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret,
        username=settings.reddit_username,
        password=settings.reddit_password,
        user_agent=settings.reddit_user_agent,
    )


def jitter_sleep(settings: Settings) -> None:
    time.sleep(random.uniform(settings.request_jitter_min_seconds, settings.request_jitter_max_seconds))


def iter_saved_submissions(reddit: praw.Reddit) -> Iterator[praw.models.Submission]:
    """Yields only Submission items from the saved listing, newest first.

    Saved Comments are skipped entirely (v1 scope decision) - they still count
    toward Reddit's ~1000-item saved-listing cap, but archiving them is out of
    scope for now.
    """
    for item in reddit.user.me().saved(limit=None):
        if isinstance(item, praw.models.Submission):
            yield item
        else:
            log.debug("skipping saved Comment %s (comments out of scope for v1)", getattr(item, "id", "?"))


def call_with_ratelimit_retry(fn, *args, **kwargs):
    """Runs a single PRAW call, retrying once on a hard 429.

    PRAW pre-emptively sleeps based on X-Ratelimit-* headers, so this should
    rarely trigger - it's a backstop, not the primary throttling mechanism.
    """
    try:
        return fn(*args, **kwargs)
    except prawcore.exceptions.TooManyRequests as exc:
        retry_after = getattr(exc, "sleep_time", 60)
        log.warning("hit 429, sleeping %.0fs before one retry", retry_after)
        time.sleep(retry_after)
        return fn(*args, **kwargs)
