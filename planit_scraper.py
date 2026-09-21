#!/usr/bin/env python3
"""Fetch national planning-application data and build a static dashboard."""

import argparse
import datetime as dt
import html
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_API = "https://www.planning.data.gov.uk/entity.json?dataset=planning-application&limit=100&sort=entry-date_desc"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=-1, help="Application-date filter; -1 means no date filter.")
    parser.add_argument("--area", action="append", default=[])
    parser.add_argument("--min-size", type=float, default=None)
    parser.add_argument("--max-size", type=float, default=None)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--out-dir", default="docs")
    return parser.parse_args()


def fetch_json(url):
    try:
        request = Request(url, headers={"User-Agent": "new-planning-dashboard/1.0", "Accept": "application/json"})
        with urlopen(request, timeout=60) as response:
            return json.load(response)
    except (HTTPError, URLError) as exc:
        raise SystemExit(f"National Planning Data API request failed: {exc}") from exc


def first(app, *keys):
    for key in keys:
        value = app.get(key) if isinstance(app, dict) else None
        if value not in (None, ""):
            return value
    return ""


def parse_date(value):
    if not value:
        return None
    text = str(value).strip()[:10]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def application_date(app):
    return first(app, "start-date", "start_date", "date_received", "date-received", "application-date")


def number(value):
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").replace("m²", "").replace("sqm", "").strip())
    except ValueError:
        return None


def size(app):
    return number(first(app, "site-area", "site_area", "siteArea", "area", "size", "size_sq_m"))


def searchable_text(app):
    keys = ("reference", "name", "description", "address", "postcode", "organisation-entity")
    return " ".join(str(first(app, key)) for key in keys).lower()


def records(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("entities", "results", "items", "applications"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def keep(app, args):
    if args.area and not any(term.strip().lower() in searchable_text(app) for term in args.area if term.strip()):
        return False
    value = size(app)
    if value is not None and args.min_size is not None and value < args.min_size:
        return False
    if value is not None and args.max_size is not None and value > args.max_size:
        return False
    date = parse_date(application_date(app))
    if args.days >= 0 and date and date < dt.date.today() - dt.timedelta(days=args.days):
        return False
    return True


def esc(value):
    return html.escape(str(value or ""), quote=True)


def row(app):
    app_date = application_date(app)
    parsed_date = parse_date(app_date)
    value = size(app)
    size_text = "" if value is None else f"{value:g}"
    reference = first(app, "reference", "council-reference", "application-reference", "id")
    address = first(app, "address", "site-address", "location")
    description = first(app, "description", "proposal", "summary", "name")
    status = first(app, "decision", "status", "outcome")
    date_attr = parsed_date.isoformat() if parsed_date else ""
    displayed_date = app_date or "Not supplied"
    return (
        f'<tr data-address="{esc(address)}" data-description="{esc(description)}" '
        f'data-size="{esc(size_text)}" data-date="{esc(date_attr)}">'
        f"<td>{esc(reference)}</td><td>{esc(address)}</td><td>{esc(description)}</td>"
        f"<td>{esc(displayed_date)}</td><td>{esc(status)}</td><td>{esc(size_text)}</td></tr>"
    )


def page(apps, args):
    rows = "\n".join(row(app) for app in apps) or '<tr><td colspan="6">No matching applications found.</td></tr>'
    area = esc(" ".join(args.area))
    minimum = "" if args.min_size is None else args.min_size
    maximum = "" if args.max_size is None else args.max_size
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>National Planning Applications</title>
<style>body{{font:16px Arial,sans-serif;margin:2rem}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:.6rem;text-align:left;vertical-align:top}}th{{background:#eee}}input{{padding:.5rem;font:inherit}}label{{display:block;margin-bottom:.5rem}}button{{padding:.6rem 1rem;font:inherit;cursor:pointer}}</style></head>
<body><h1>National Planning Applications</h1><p id="count">Showing {len(apps)} records.</p>
<form id="filters"><label>Search: <input id="area" value="{area}"></label>
<label>Min size (m²): <input id="min" type="number" step="any" value="{minimum}"></label>
<label>Max size (m²): <input id="max" type="number" step="any" value="{maximum}"></label>
<label>Application date, last N days (0 = all): <input id="days" type="number" min="0" value="0"></label>
<button type="submit">Update search terms</button></form>
<table><thead><tr><th>Reference</th><th>Address</th><th>Description</th><th>Application date</th><th>Status</th><th>Size (m²)</th></tr></thead><tbody id="results">{rows}</tbody></table>
<script>
const rows=[...document.querySelectorAll('#results tr')],form=document.querySelector('#filters'),area=document.querySelector('#area'),min=document.querySelector('#min'),max=document.querySelector('#max'),days=document.querySelector('#days'),count=document.querySelector('#count');
function apply(){{const query=area.value.toLowerCase().trim(),low=min.value===''?-Infinity:Number(min.value),high=max.value===''?Infinity:Number(max.value),dayCount=Number(days.value||0),cutoff=dayCount>0?Date.now()-dayCount*86400000:null;let shown=0;rows.forEach(row=>{{const text=((row.dataset.address||'')+' '+(row.dataset.description||'')).toLowerCase(),value=row.dataset.size===''?null:Number(row.dataset.size),date=row.dataset.date||'',visible=(!query||text.includes(query))&&(value===null||(value>=low&&value<=high))&&(!cutoff||(date&&Date.parse(date)>=cutoff));row.style.display=visible?'':'none';if(visible)shown++}});count.textContent='Showing '+shown+' records.'}}
form.addEventListener('submit',event=>{{event.preventDefault();apply()}});[area,min,max,days].forEach(element=>element.addEventListener('input',apply));apply();
</script></body></html>'''


def main():
    args = parse_args()
    apps = [app for app in records(fetch_json(args.api)) if keep(app, args)]
    if args.limit:
        apps = apps[:args.limit]
    output = Path(args.out_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "applications.json").write_text(json.dumps(apps, indent=2), encoding="utf-8")
    (output / "index.html").write_text(page(apps, args), encoding="utf-8")
    print(f"Created dashboard with {len(apps)} national applications in {output}")


if __name__ == "__main__":
    main()
