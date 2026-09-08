from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Read straight from the env files when run locally (any shell - no
    # `export`/`$env.` gymnastics needed), while still letting real env vars
    # (e.g. the CronJob's envFrom) take priority. Missing files are ignored.
    # .env.local is gitignored and meant for local-only overrides (e.g.
    # DATA_DIR, DRY_RUN) without touching the real config.env/secret.env.
    model_config = SettingsConfigDict(
        env_file=("../config.env", "../secret.env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    reddit_client_id: str
    reddit_client_secret: str
    reddit_username: str
    reddit_password: str
    reddit_user_agent: str

    data_dir: Path = Path("/data")

    unsave_batch_size: int = 10
    unsave_min_verify_count: int = 2
    max_video_size_mb: int = 2048
    crosspost_max_hops: int = 5

    request_jitter_min_seconds: float = 1.5
    request_jitter_max_seconds: float = 4.0

    log_level: str = "INFO"
    dry_run: bool = False

    @property
    def by_subreddit_dir(self) -> Path:
        return self.data_dir / "by_subreddit"

    @property
    def viewer_dir(self) -> Path:
        return self.data_dir / "viewer"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "index.sqlite"

    @property
    def last_run_stats_path(self) -> Path:
        return self.data_dir / "last_run_stats.json"


def load_settings() -> Settings:
    return Settings()
