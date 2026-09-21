#!/usr/bin/env python3
"""Build a simple dashboard of recent Cambridge planning applications."""
import html
import json
from pathlib import Path
from urllib.request import Request, urlopen

API = "https://www.planit.org.uk/api/recent/CAMBD/json"

request = Request(API, headers={"User-Agent": "new-planning-dashboard/1.0"})
with urlopen(request, timeout=60) as response:
    payload = json.load(response)

if isinstance(payload, list):
    applications = payload
elif isinstance(payload, dict):
    applications = payload.get("results") or payload.get("applications") or []
else:
    applications = []

rows = []
for app in applications:
    reference = str(app.get("id") or app.get("reference") or app.get("applicref") or "")
    address = str(app.get("address") or app.get("site_address") or "")
    description = str(app.get("description") or app.get("proposal") or "")
    received = str(app.get("date_received") or app.get("received") or "")
    status = str(app.get("decision") or app.get("status") or "")
    rows.append(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(reference), html.escape(address), html.escape(description),
            html.escape(received), html.escape(status)
        )
    )

if not rows:
    rows.append('<tr><td colspan="5">No applications were returned.</td></tr>')

page = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cambridge Planning Applications</title>
<style>
body {{ font: 16px Arial, sans-serif; margin: 2rem; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ddd; padding: .6rem; text-align: left; vertical-align: top; }}
th {{ background: #eee; }}
</style></head><body>
<h1>Cambridge Planning Applications</h1>
<p>Showing {} recent applications from PlanIt.</p>
<table><thead><tr><th>Reference</th><th>Address</th><th>Description</th><th>Received</th><th>Status</th></tr></thead>
<tbody>{}</tbody></table>
</body></html>""".format(len(applications), "\n".join(rows))

Path("docs").mkdir(exist_ok=True)
Path("docs/index.html").write_text(page, encoding="utf-8")
Path("docs/applications.json").write_text(json.dumps(applications, indent=2), encoding="utf-8")
print("Created dashboard with", len(applications), "applications")
