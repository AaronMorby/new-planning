#!/usr/bin/env python3
import datetime as dt
import html
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://www.planit.org.uk/api/application.json"
days = 7
since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
url = API + "?" + urlencode({"date_received__gte": since, "limit": 1000})
request = Request(url, headers={"User-Agent": "new-planning-dashboard/1.0"})
with urlopen(request, timeout=60) as response:
    payload = json.load(response)
applications = payload.get("results", []) if isinstance(payload, dict) else []

rows = []
for app in applications:
    reference = str(app.get("id", app.get("reference", "")))
    address = str(app.get("address", ""))
    description = str(app.get("description", ""))
    received = str(app.get("date_received", ""))
    status = str(app.get("decision", app.get("status", "")))
    rows.append("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
        html.escape(reference), html.escape(address), html.escape(description),
        html.escape(received), html.escape(status)))

if not rows:
    rows.append('<tr><td colspan="5">No applications were returned.</td></tr>')

page = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>UK Planning Applications</title>
<style>body{font:16px Arial,sans-serif;margin:2rem}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:.6rem;text-align:left;vertical-align:top}th{background:#eee}</style>
</head><body><h1>UK Planning Applications</h1>
<p>Showing {} applications received since {}.</p>
<table><thead><tr><th>Reference</th><th>Address</th><th>Description</th><th>Received</th><th>Status</th></tr></thead><tbody>{}</tbody></table>
</body></html>""".format(len(applications), since, "\n".join(rows))

Path("docs").mkdir(exist_ok=True)
Path("docs/index.html").write_text(page, encoding="utf-8")
Path("docs/applications.json").write_text(json.dumps(applications, indent=2), encoding="utf-8")
print("Created dashboard with", len(applications), "applications")

.github/workflows/update.yml

yml
name: Update planning applications dashboard

on:
  workflow_dispatch:
  schedule:
    - cron: "0 */6 * * *"

permissions:
  contents: write

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@v4
      - name: Build dashboard
        run: python3 planit_scraper.py
      - name: Save updated dashboard
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add docs/
          git diff --cached --quiet || git commit -m "Update planning applications dashboard"
          git push
