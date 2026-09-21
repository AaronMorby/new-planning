# UK Planning Applications Tracker

Tracks new planning applications and decisions across UK local authorities,
using the free [PlanIt](https://www.planit.org.uk) aggregator (~420 councils,
no API key needed), and renders them as a browsable dashboard.

**Why this isn't a single link I can hand you right now:** a live, always-current
dashboard needs something to fetch fresh data from PlanIt on a schedule and
re-publish it. A page I publish directly for you in this chat is a snapshot
that can't reach out to external sites on its own — so instead this is a small,
free, self-running setup: a script plus a GitHub Actions workflow that runs it
automatically and republishes the dashboard as a real hosted webpage.

## Files

- `planit_scraper.py` — fetches from PlanIt, stores everything in a local
  SQLite database (`planning.db`), and writes `docs/index.html`, a dashboard
  with search, filters (authority, status, new-this-run, newly-decided-this-run).
  Uses only Python's standard library — nothing to `pip install`.
- `update.yml` — a GitHub Actions workflow that runs the script every 6 hours
  and commits the updated data + dashboard back to your repo.

## Fastest path: hosted, self-updating dashboard (10 minutes, free)

1. Create a new **public** GitHub repository.
2. Add `planit_scraper.py` to the repo root.
3. Create the folder `.github/workflows/` and add `update.yml` there.
4. Commit and push.
5. In the repo's **Settings → Pages**, set the source to "Deploy from a
   branch", branch `main`, folder `/docs`.
6. In the **Actions** tab, run the "Update planning applications dashboard"
   workflow once manually (`Run workflow`) so `docs/index.html` and
   `planning.db` get created and pushed.
7. Your dashboard is now live at `https://<your-username>.github.io/<repo-name>/`,
   and updates automatically every 6 hours (edit the `cron` line in `update.yml`
   to change that — e.g. `"0 * * * *"` for hourly).

Because the schedule only fetches the last N days each run, missing a run or
two doesn't lose data — just keep `--recent` at least as large as the gap
between runs.

## Running it yourself instead (cron / Task Scheduler)

```bash
python3 planit_scraper.py --recent 2 --db planning.db --out dashboard.html
```

Then open `dashboard.html` in a browser. To automate:

- **Mac/Linux (cron):** `crontab -e`, add a line like
  `0 */6 * * * cd /path/to/folder && python3 planit_scraper.py`
- **Windows:** use Task Scheduler to run the same command every few hours.

## Narrowing the scope

By default it queries nationally. To restrict to specific authorities or
filters:

```bash
python3 planit_scraper.py --auth "Cornwall" --auth "Bristol, City of" --recent 3
python3 planit_scraper.py --keyword "solar" --recent 7
python3 planit_scraper.py --app-state Permitted --recent 30
```

Run `python3 planit_scraper.py --help` for all options.

## Notes and caveats

- PlanIt is a long-running, well-regarded community aggregator, not an
  official government service — treat it as a discovery tool and always
  follow the linked reference through to the council's own portal (the
  dashboard links to it) before relying on a decision or date.
- Coverage and freshness vary a little by council; PlanIt's own docs are at
  https://www.planit.org.uk/api/ if you want to extend the queries (e.g.
  postcode-radius or bounding-box search).
- The dashboard shows the last 60 days plus anything flagged new/decided this
  run, to keep the file a manageable size at national scale; change
  `--window-days` if you want more or less history visible.
