#!/usr/bin/env python3
"""
Fetch recent UK planning applications from the government Planning Data API,
then build a simple dashboard with area, size, and age filters.
"""

import argparse
import datetime as dt
import html
import json
import re
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

DEFAULT_API = "https://www.planning.data.gov.uk/entity.json?dataset=planning-application&limit=100&sort=start-date_desc"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Fetch UK planning applications from Planning Data and build a dashboard."
    )
    parser.add_argument("--days", type=int, default=30, help="Only include applications in the last N days.")
    parser.add_argument("--area", action="append", default=[], help="Area or place-name keyword. Repeat for multiple matches.")
    parser.add_argument("--min-size", type=float, default=None, help="Minimum site size in square metres.")
    parser.add_argument("--max-size", type=float, default=None, help="Maximum site size in square metres.")
    parser.add_argument("--limit", type=int, default=500, help="Maximum number of results to keep after filtering.")
    parser.add_argument("--api", default=DEFAULT_API, help="Planning Data API URL.")
    parser.add_argument("--out-dir", default="docs", help="Output directory for dashboard files.")
    return parser.parse_args()


def fetch_json(url):
    req = Request(url, headers={"User-Agent": "new-planning-dashboard/1.0"})
    try:
        with urlopen(req, timeout=60) as response:
            return json.load(response)
    except HTTPError as exc:
        raise SystemExit(f"Planning Data API request failed with HTTP {exc.code}: {url}") from exc


def flatten_values(obj):
    values = []

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, (str, int, float, bool)):
            values.append(str(x))

    walk(obj)
    return values


def first_present(data, keys):
    if isinstance(data, dict):
        for key in keys:
            if key in data and data[key] not in (None, ""):
                return data[key]
    return ""


def get_text(obj, *keys):
    if isinstance(obj, dict):
        for key in keys:
            if key in obj and obj[key] not in (None, ""):
                return str(obj[key])
    return ""


def parse_date(value):
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime(text[:10], fmt).date()
        except ValueError:
            pass
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def as_float(value):
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    text = (text.replace("sqm", "").replace("sqm.", "").replace("m²", "")
            .replace("m2", "").replace("square metres", "").replace("sq m", "")
            .replace(",", ""))
    match = re.search(r"[-+]?\d*\.?\d+", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def get_size_m2(app):
    # Do not scan every value recursively: that incorrectly treats years and IDs as sizes.
    candidates = [
        app.get("site-area"), app.get("site_area"), app.get("siteArea"),
        app.get("area"), app.get("site-area-sq-m"), app.get("size"),
        app.get("size_sq_m"), app.get("square_metres"), app.get("gross-floor-area"),
    ]
    for value in candidates:
        size = as_float(value)
        if size is not None:
            return size
    return None


def get_app_date(app):
    return first_present(app, [
        "start-date", "start_date", "date", "application-date", "received-date",
        "date_received", "received", "decision-date", "decision_date",
    ]) or ""


def app_matches_area(app, terms):
    if not terms:
        return True
    text = " ".join(flatten_values(app)).lower()
    return any(term.lower().strip() in text for term in terms if term.strip())


def app_matches_size(app, min_size, max_size):
    size = get_size_m2(app)
    if size is None:
        return True
    if min_size is not None and size < min_size:
        return False
    if max_size is not None and size > max_size:
        return False
    return True


def app_is_recent(app, days):
    if days is None or days < 0:
        return True
    date_obj = parse_date(get_app_date(app))
    if date_obj is None:
        return True
    return date_obj >= dt.date.today() - dt.timedelta(days=days)


def clean_html(value):
    return html.escape(str(value), quote=True)


def get_row_text(app):
    ref = first_present(app, ["reference", "id", "application-reference", "applicationNumber", "application_no"]) or ""
    address = first_present(app, ["address", "site_address", "site-address", "address_text", "location"]) or ""
    desc = first_present(app, ["description", "proposal", "summary", "title"]) or ""
    received = get_app_date(app)
    status = first_present(app, ["decision", "status", "outcome"]) or ""
    size = get_size_m2(app)
    size_text = "" if size is None else f"{size:g}"
    date_text = parse_date(received).isoformat() if parse_date(received) else ""
    return (
        f'<tr data-address="{clean_html(address)}" data-description="{clean_html(desc)}" '
        f'data-size="{clean_html(size_text)}" data-date="{clean_html(date_text)}">'
        f"<td>{clean_html(ref)}</td><td>{clean_html(address)}</td><td>{clean_html(desc)}</td>"
        f"<td>{clean_html(received)}</td><td>{clean_html(status)}</td><td>{clean_html(size_text)}</td></tr>"
    )


def build_page(applications, area_text, min_size, max_size, days):
    rows_html = "\n".join(get_row_text(app) for app in applications) if applications else '<tr><td colspan="6">No matching applications found.</td></tr>'
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Planning Applications Dashboard</title>
<style>body {{ font: 16px Arial,sans-serif; margin:2rem }} table {{ border-collapse:collapse;width:100% }} th,td {{ border:1px solid #ddd;padding:.6rem;text-align:left;vertical-align:top }} th {{ background:#eee }} input {{ padding:.5rem;font:inherit }} label {{ display:block;margin-bottom:.5rem }} button {{ padding:.6rem 1rem;font:inherit;cursor:pointer }}</style></head>
<body><h1>Planning Applications Dashboard</h1><p id="resultCount">Showing {len(applications)} matching applications.</p>
<form id="filters" style="margin-bottom:1rem"><label>Search area or description: <input id="areaFilter" type="text" value="{html.escape(area_text or '', quote=True)}"></label>
<label>Min size (m²): <input id="minSize" type="number" step="any" value="{' ' if min_size is None else min_size}"></label>
<label>Max size (m²): <input id="maxSize" type="number" step="any" value="{' ' if max_size is None else max_size}"></label>
<label>Days: <input id="days" type="number" min="0" value="{days}"></label><button type="submit">Update search terms</button></form>
<table><thead><tr><th>Reference</th><th>Address</th><th>Description</th><th>Received</th><th>Status</th><th>Size (m²)</th></tr></thead><tbody id="results">{rows_html}</tbody></table>
<script>
const rows=[...document.querySelectorAll('#results tr')], form=document.getElementById('filters'), areaFilter=document.getElementById('areaFilter'), minSize=document.getElementById('minSize'), maxSize=document.getElementById('maxSize'), days=document.getElementById('days'), resultCount=document.getElementById('resultCount');
function applyFilters() {{ const area=(areaFilter.value||'').toLowerCase().trim(), min=minSize.value===''?-Infinity:Number(minSize.value), max=maxSize.value===''?Infinity:Number(maxSize.value), dayCount=Number(days.value||0), cutoff=dayCount>0?Date.now()-dayCount*86400000:null; let count=0;
rows.forEach(row=>{{ const address=(row.dataset.address||'').toLowerCase(), description=(row.dataset.description||'').toLowerCase(), size=row.dataset.size===''?null:Number(row.dataset.size), date=row.dataset.date||'', matchesArea=!area||address.includes(area)||description.includes(area), matchesSize=size===null||(size>=min&&size<=max), matchesDate=!cutoff||(date&&new Date(date).getTime()>=cutoff); const visible=matchesArea&&matchesSize&&matchesDate; row.style.display=visible?'':'none'; if(visible) count++; }}); resultCount.textContent=`Showing ${{count}} matching applications.`; localStorage.setItem('planningFilters',JSON.stringify({{area:areaFilter.value,min:minSize.value,max:maxSize.value,days:days.value}})); }}
form.addEventListener('submit',event=>{{event.preventDefault();applyFilters();}}); [areaFilter,minSize,maxSize,days].forEach(el=>el.addEventListener('input',applyFilters)); applyFilters();
</script></body></html>'''


def main():
    args = parse_args()
    payload = fetch_json(args.api)
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("entities") or payload.get("items") or payload.get("results") or payload.get("applications") or []
    else:
        items = []
    filtered = [app for app in items if app_matches_area(app, args.area) and app_matches_size(app, args.min_size, args.max_size) and app_is_recent(app, args.days)]
    filtered = filtered[:args.limit] if args.limit else filtered
    out_dir = Path(args.out_dir)
    out_dir.mkdir(exist_ok=True, parents=True)
    (out_dir / "applications.json").write_text(json.dumps(filtered, indent=2), encoding="utf-8")
    (out_dir / "index.html").write_text(build_page(filtered, " ".join(args.area), args.min_size, args.max_size, args.days), encoding="utf-8")
    print(f"Created dashboard with {len(filtered)} applications in {out_dir}")


if __name__ == "__main__":
    main()
