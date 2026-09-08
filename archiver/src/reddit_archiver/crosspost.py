import logging
from dataclasses import dataclass

import praw
import prawcore

log = logging.getLogger(__name__)


@dataclass
class ResolvedSubmission:
    submission: praw.models.Submission
    is_crosspost: bool
    crosspost_seen_via_subreddit: str | None
    crosspost_resolution_failed: bool


def resolve_original(reddit: praw.Reddit, submission: praw.models.Submission, max_hops: int) -> ResolvedSubmission:
    """Follows crosspost_parent_list to the original submission.

    Reddit's saved listing can return the crosspost wrapper rather than the
    source post; we archive the original, not the wrapper, but remember which
    subreddit the wrapper (the thing actually saved) lived in.
    """
    seen_via_subreddit: str | None = None
    current = submission
    hops = 0

    while hops < max_hops:
        parent_list = getattr(current, "crosspost_parent_list", None)
        if not parent_list:
            break

        if seen_via_subreddit is None:
            seen_via_subreddit = str(current.subreddit)

        parent_id = parent_list[0]["id"]
        try:
            parent = reddit.submission(id=parent_id)
            parent.title  # force a lazy-load fetch now, so failures surface here
        except (prawcore.exceptions.Forbidden, prawcore.exceptions.NotFound) as exc:
            log.warning("crosspost parent %s unreachable (%s), archiving wrapper instead", parent_id, exc)
            return ResolvedSubmission(
                submission=current,
                is_crosspost=True,
                crosspost_seen_via_subreddit=seen_via_subreddit,
                crosspost_resolution_failed=True,
            )

        current = parent
        hops += 1

    return ResolvedSubmission(
        submission=current,
        is_crosspost=seen_via_subreddit is not None,
        crosspost_seen_via_subreddit=seen_via_subreddit,
        crosspost_resolution_failed=False,
    )
