import logging


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # yt-dlp/urllib3 are noisy at INFO/DEBUG - keep them quiet unless we're
    # explicitly troubleshooting the archiver itself.
    for noisy in ("urllib3", "prawcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
