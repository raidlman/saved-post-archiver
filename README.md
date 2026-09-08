# Reddit Archiver

> Mirrored out of a private homelab GitOps repo for external review. Paths
> like `git.sknt.xyz/...` are the author's own private container registry -
> not required to run this elsewhere.

Archives saved Reddit posts (media at highest available quality, OP, subreddit,
permalink, score) to a PVC, resolving crossposts to their original source post.
Runs on a schedule, unsaving already-archived posts to work past Reddit's
~1000-item saved-listing cap. Browsable directly on disk, or via a small
web viewer behind Basic Auth.

## How it works

```
reddit-archiver CronJob (every 6h):
  1. Re-verify any pending/downloading rows left over from an interrupted run
  2. List saved posts (newest first), resolve crossposts to their original
  3. For each new/retryable post: dispatch media fetch, verify on disk, write post.json
  4. Unsave rotation: unsave oldest-of-the-newest fully-verified archives
     (only after the archive pass succeeds, never on dead/failed media)
  5. Regenerate the static viewer from the SQLite index
```

Media fetching cascades through `gallery-dl` (images/galleries) and `yt-dlp`
(video, including muxing v.redd.it's separate audio track via ffmpeg), with a
plain HTTP fallback for anything neither tool recognizes. See the full design
rationale (dispatch order, unsave algorithm, state machine) in the plan this
was built from: `~/.claude/plans/ich-will-meine-gesicherten-atomic-goblet.md`
on the machine it was authored on — not part of this repo.

Two independent images, decoupled release cadence:

- **archiver** (`archiver/`) — Python 3.14, the CronJob doing all the work above
- **viewer** (`viewer/`) — Caddy, serves the PVC's `viewer/` + raw `by_subreddit/` tree, and enforces Basic Auth itself

Basic Auth lives in the viewer's own Caddyfile (`basic_auth` directive) rather
than a separate proxy — Gateway API has no native auth filter and Cilium
doesn't support one either (checked directly: no `ExternalAuth`/GEP-1494
support, no first-class Basic Auth route filter), so a dedicated "auth-gate"
component in front of the viewer would only add an extra network hop and
moving parts (its own Deployment/Service/initContainer) without doing
anything Caddy's own `basic_auth` doesn't already do in one line. An
initContainer still renders the final Caddyfile from a template at pod start
(see below) since the credentials are a per-deployment secret, not known at
image build time.

## Directory Structure

```
reddit-archiver/
├── namespace.yaml
├── pvc.yaml                        # 50Gi, openebs-hostpath
├── config.env                      # non-secret config (committed to git)
├── secret.env.example              # Reddit + viewer Basic Auth credentials - copy to secret.env and fill in
├── kustomization.yaml
├── cronjob-archiver.yaml
├── deployment-viewer.yaml          # initContainer renders Caddyfile from secret.env, then basic_auth + file_server
├── service-viewer.yaml             # this is what the HTTPRoute targets
├── httproute-viewer.yaml
├── archiver/
│   ├── Dockerfile                  # python:3.14-slim + ffmpeg
│   ├── pyproject.toml              # praw, yt-dlp, gallery-dl, pydantic-settings, requests
│   ├── build-and-push.sh
│   └── src/reddit_archiver/
│       ├── config.py               # env-driven settings
│       ├── reddit_client.py        # PRAW wrapper, jitter/pacing, 429 backstop
│       ├── crosspost.py            # crosspost_parent_list resolution
│       ├── state.py                # SQLite index (posts table)
│       ├── postdir.py              # on-disk folder naming, post.json read/write
│       ├── media/
│       │   ├── dispatch.py         # gallery-dl / yt-dlp / direct-HTTP cascade
│       │   ├── native.py           # plain HTTP GET for direct image links
│       │   └── verify.py           # post-download completeness check (magic bytes, ffprobe)
│       ├── unsave.py                # rotation algorithm
│       ├── archive.py               # orchestrates one run
│       ├── stats.py                 # run summary + last_run_stats.json
│       └── viewer/
│           ├── generate.py          # writes data.json + copies static_assets/ each run
│           └── static_assets/       # index.html (gallery/filter/sort), post.html (detail view)
└── viewer/
    ├── Dockerfile                   # FROM caddy:2-alpine, bakes Caddyfile in as a template
    ├── Caddyfile                    # basic_auth + serves /data, falls back to /viewer/index.html
    └── build-and-push.sh
```

On the PVC:

```
/data/
├── index.sqlite
├── last_run_stats.json
├── by_subreddit/<sub>/<date>_<id36>_<slug>/
│   ├── post.json
│   ├── body.md            # self posts only
│   ├── media/001.jpg, 002.mp4, thumbnail.jpg
│   └── .archive_complete  # sentinel, only after verify passes
└── viewer/
    ├── index.html, post.html   # copied from static_assets/ each run
    └── data.json               # regenerated each run
```

## Initial Setup

### 1. Create a Reddit script app

1. Log into the Reddit account, go to <https://www.reddit.com/prefs/apps>
2. "are you a developer? create an app..." → name e.g. `saved-post-archiver`
   (Reddit rejects "reddit" in the name), type **script**,
   redirect URI `http://localhost:8080` (unused but required)
3. Note the **client_id** (unlabeled string under the app name) and **secret**
4. **2FA must be off** on this account — password-grant auth doesn't support it

### 2. Fill in secret.env

```bash
cp secret.env.example secret.env
```

```env
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
REDDIT_USERNAME=...
REDDIT_PASSWORD=...
VIEWER_BASIC_AUTH_USERNAME=...
VIEWER_BASIC_AUTH_PASSWORD_HASH=...   # see below, NOT the plaintext password
```

Generate the viewer's Basic Auth password hash (Caddy needs bcrypt, not plaintext):

```bash
docker run --rm caddy:2-alpine caddy hash-password --plaintext 'your-password-here'
```

### 3. Fill in config.env

Set `REDDIT_USER_AGENT` to something real and unique, per Reddit's API rules:

```env
REDDIT_USER_AGENT=linux:reddit-archiver:v1.0 (by /u/your-username)
```

### 4. Dry run locally before touching the real account for real

```bash
cd archiver
python3 -m venv venv
venv/bin/pip install -e .
```

Activate the venv, then run the dry run. Python's own `venv` module doesn't
generate an `activate.nu`, so for nushell there's a minimal hand-written one
at `venv/bin/activate.nu` (recreate it after deleting/recreating `venv/` -
it's gitignored, like the rest of `venv/`):

```nu
overlay use venv/bin/activate.nu
```

`venv/bin/activate.nu` content (same minimal script used across other repos):

```nu
# venv/bin/activate.nu

export-env {
    $env.VIRTUAL_ENV = ($env.PWD | path join "venv")
    $env.PATH = ($env.PATH | prepend $"($env.VIRTUAL_ENV)/bin")
}
```

```bash
# bash/zsh equivalent
source venv/bin/activate
```

No `export`/`$env.` needed for config - `Settings` reads `../config.env` and
`../secret.env` directly (see `config.py`'s `env_file` setting), so it works
the same in any shell. Real environment variables (e.g. the CronJob's
`envFrom`) still take priority when present. For a one-off local override
like `DATA_DIR`, drop it in `archiver/.env.local` (gitignored, read with
highest priority) instead of exporting it in the shell:

```bash
echo 'DATA_DIR=/tmp/reddit-archiver-test' > .env.local
python -m reddit_archiver --dry-run
```

Check the logged decisions and the `[DRY RUN]` summary block — nothing is
written to disk and no `unsave()` calls are made in this mode.

### 5. Build and push both images

```bash
cd archiver && docker login git.sknt.xyz && ./build-and-push.sh
cd ../viewer && ./build-and-push.sh
```

Each script builds locally (Gitea Actions runner is arm on a Pi — wrong arch
for these images), pushes, and rewrites its own image tag in place in the
manifests that reference it. Review the diff and commit.

### 6. Deploy

```bash
kubectl apply -k apps/reddit-archiver
```

Trigger the first run manually rather than waiting for the schedule:

```bash
kubectl create job --from=cronjob/reddit-archiver reddit-archiver-manual-1 -n reddit-archiver
kubectl logs -f job/reddit-archiver-manual-1 -n reddit-archiver
```

Then visit `https://reddit-archive.sknt.xyz` (Basic Auth prompt from Caddy,
then the gallery).

## Notes

- Unsave rotation only ever touches posts with `media_status` `complete` or
  `link_only` **and** `verify_count >= 2` (confirmed archived on a previous
  run, re-confirmed still present now) — dead media (`unavailable`) and
  in-progress failures (`partial`) are never auto-unsaved; that's a manual
  call via Reddit's own UI.
- A single `saved()` call already returns at most Reddit's own ~1000-item
  ceiling, and the run never re-fetches it after unsaving — whatever gets
  revealed by this run's unsaves just shows up on the *next* scheduled run,
  so there's nothing extra to build against saved-listing propagation delay.
- `DRY_RUN=true` in `config.env` makes every run read-only (same effect as
  `--dry-run` on the CLI, useful for leaving the CronJob in observe-only mode).
- `LOG_LEVEL=DEBUG` in `config.env` surfaces why the media-dispatch cascade
  rejected a given tool for a URL before falling through to the next one.
- All base images (`python:3.14-slim`, `caddy:2-alpine`) are Docker Official
  Images; all Python dependencies are long-established, actively-maintained
  packages — no obscure/unverified deps.
- The viewer's liveness/readiness probes use `tcpSocket`, not `httpGet` —
  `basic_auth` in the Caddyfile protects `/` too, so an unauthenticated
  `httpGet` probe would always see a 401.
- `readOnlyRootFilesystem: true` on the archiver container means `$HOME` is
  overridden to `/tmp` (an emptyDir) so yt-dlp/gallery-dl have somewhere
  writable for their cache dirs.
- Renovate needs no extra config for this component — `gitops-fluxcd/renovate.json`'s
  `config:best-practices` already tracks Dockerfile `FROM` tags and
  `pyproject.toml` dependencies repo-wide.

## TODO before deploy

- [ ] Create the Reddit script app, fill in `secret.env`
- [ ] Generate and set `VIEWER_BASIC_AUTH_PASSWORD_HASH`
- [ ] Set a real `REDDIT_USER_AGENT` in `config.env`
- [ ] Dry-run locally against the real saved list, sanity-check the summary
- [ ] Build and push both images
- [ ] Deploy, trigger one manual run, confirm the viewer is reachable and prompts for Basic Auth
