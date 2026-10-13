# Audible → Observatory auto-sync (spec, not implemented)

Ticket: `Organization/todos/update-observatory-with-audible-automatically.md`

## Goal
When Waldo finishes an audiobook on Audible, Observatory gets it without manual export.

## Current state
- `scripts/ingest_audible.py` reads `data/raw/audible_finished.csv`, which **does not exist** (only `audible_extra.json` does). Audible data was a one-off manual export.
- Observatory runs on oracle (`observatory.service`); oracle already hosts cron jobs (e.g. the GA4 digest), so a scheduled job there is the natural home.

## What Audible offers
- No public API, no webhooks, no RSS feed for listening activity.
- Unofficial but actively maintained Python client: [`audible`](https://pypi.org/project/audible/) (mkb79; docs at audible.readthedocs.io). It talks to the private API the Audible apps use. Per community docs the library endpoint supports response groups `is_finished`, `listening_status`, `percent_complete`, and finished events with timestamps exist under `/1.0/stats/status/finished`. (From docs and search results; not yet tested against Waldo's account.)
- Auth: one-time interactive login (Amazon login, possibly OTP/CAPTCHA) producing a credentials file that auto-refreshes tokens. Marketplace must match the account (likely `de`).

## Options
| Option | Latency | Effort | Reliability | Notes |
|---|---|---|---|---|
| A. `audible` lib poll on oracle (recommended) | up to poll interval (hourly/daily) | ~half day | Medium-high; unofficial API can change, ToS grey area but read-only on own library | Fetch library with `is_finished`, diff against DB, upsert via existing ingest logic |
| B. Goodreads sync | n/a | low | Poor | Goodreads has no API since 2020; Audible-Goodreads link only syncs to the Goodreads site, nothing to pull |
| C. IFTTT / n8n | n/a | low | Not possible | No Audible trigger exists; n8n VM is parked |
| D. Scraping audible.de web | daily | high | Low | Needs login + bot protection; strictly worse than A |
| E. Manual export (status quo) | manual | none | high | The thing we want to remove |

## Proposal (Option A)
1. One-time: on oracle, create venv `~/Library/Scripts/audible-env`-equivalent, `pip install audible`, run login once (interactive, Waldo types OTP via `! ssh oracle ...`), store credentials file `chmod 600` outside the repo (never committed).
2. New `scripts/sync_audible.py`: list library (`response_groups=is_finished,listening_status,percent_complete,product_attrs,contributors`), keep items with `is_finished` true, map to `media_items` (media_type audiobook/book, author, series where given), reuse `ingest_audible.py` matching (`find_in_db` by title so Goodreads duplicates get "also listened" rather than duplicated). Idempotent.
3. Cron on oracle: hourly (or daily 06:00 Berlin), logs to `~/logs/audible-sync.log`, Telegram alert on auth failure (token revoked is the main failure mode).
4. Smoke check: dry-run mode prints the diff; eval asserts the script exits 0 and is idempotent on second run.

## Risks / tradeoffs
- Unofficial API: can break or require re-login; mitigated by alerting, and failure only means stale data.
- Amazon login may trigger CAPTCHA/OTP on first auth from a new IP; do the login locally and copy the credentials file to oracle.
- Finish detection: use `is_finished` rather than a percentage threshold (the `percent_complete` ≥ 95% heuristic is only a fallback).

## Decision needed from Waldo
Go with Option A? And poll cadence (hourly vs daily)?

## Implementation status (scaffold built, NOT yet installed on oracle)
Decided: Option A, daily poll. Files: `scripts/audible_login.py` (one-time auth), `scripts/sync_audible.py` (fetch + merge + write `data/raw/audible_finished.csv` + run `ingest_audible`; `--dry-run` supported), `scripts/sync_audible_cron.sh` (cron wrapper, logs to `~/logs/audible-sync.log`).
`sync_audible.py` merges existing DB audible rows into the CSV first, because `ingest_audible.main()` deletes all `source='audible'` rows before reinserting.
Not yet tested against a real account (needs the login below).

### Install on oracle (needs Waldo)
```bash
ssh oracle
python3 -m venv ~/audible-env && ~/audible-env/bin/pip install audible
cd ~/observatory && ~/audible-env/bin/python3 scripts/audible_login.py   # the one auth command
~/audible-env/bin/python3 scripts/sync_audible.py --dry-run             # inspect before first real run
# then cron (06:00 Berlin; oracle TZ must be checked): 
# 0 6 * * * /home/ubuntu/observatory/scripts/sync_audible_cron.sh
```
Add `audible` to `requirements.txt` only if the oracle service venv is reused.
