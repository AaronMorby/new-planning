#!/usr/bin/env python3
"""Fetch national planning applications and build a static dashboard."""

import argparse
import datetime as dt
import html
import json
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
import time

DEFAULT_API = "https://www.planit.org.uk/api/applics/json"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--page-size", type=int, default=200)
    parser.add_argument("--max-pages", type=int, default=400)
    parser.add_argument("--council-lookback", type=int, default=14)
    parser.add_argument("--area", action="append", default=[])
    parser.add_argument("--min-size", type=float, default=None)
    parser.add_argument("--max-size", type=float, default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--approved", action="store_true", help="Only include approved or granted decisions.")
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--out-dir", default="docs")
    return parser.parse_args()


def fetch_json(url):
    try:
        request = Request(url, headers={"User-Agent": "new-planning-dashboard/1.0", "Accept": "application/json"})
        with urlopen(request, timeout=60) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError(f"PlanIt API request failed: {exc}") from exc


def fetch_planit(args):
    """Fetch every page for new, changed and decided applications; fail closed."""
    if args.page_size < 1 or args.page_size > 300 or args.max_pages < 1:
        raise RuntimeError("Invalid pagination settings")
    seen = {}
    summaries = []
    parts = urlsplit(args.api)
    base_params = dict(parse_qsl(parts.query))
    for date_filter in ("recent", "changed", "decided"):
        count = 0
        total = None
        for page in range(1, args.max_pages + 1):
            params = dict(base_params)
            params.update({date_filter: str(max(0, args.days)), "pg_sz": str(args.page_size), "page": str(page), "compress": "on"})
            url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), ""))
            for attempt in range(3):
                try:
                    payload = fetch_json(url)
                    break
                except RuntimeError:
                    if attempt == 2:
                        raise
                    time.sleep(2 ** attempt)
            if not isinstance(payload, dict) or not isinstance(payload.get("records"), list) or not isinstance(payload.get("total"), int):
                raise RuntimeError(f"Invalid PlanIt response for {date_filter}, page {page}; cannot claim complete coverage")
            if payload.get("error"):
                raise RuntimeError(f"PlanIt returned error for {date_filter}: {payload['error']}")
            batch = payload["records"]
            total = payload["total"]
            if not batch and count < total:
                raise RuntimeError(f"Missing PlanIt page {page} for {date_filter}: {count}/{total}")
            if total < 0 or count + len(batch) > total:
                raise RuntimeError(f"Inconsistent PlanIt count for {date_filter}, page {page}")
            count += len(batch)
            for app in batch:
                if not isinstance(app, dict):
                    raise RuntimeError("Invalid application record")
                key = str(first(app, "name", "uid", "reference", "id"))
                if not key:
                    raise RuntimeError("Application without identifier")
                seen[key] = app
            if count >= total:
                break
        else:
            raise RuntimeError(f"Pagination limit hit for {date_filter}: {count}/{total}")
        summaries.append(f"{date_filter}: {count}/{total} records, {page} pages")
    if not seen:
        raise RuntimeError("PlanIt returned zero records across all national queries; refusing to publish a misleading empty dashboard")
    print("PlanIt coverage: " + "; ".join(summaries))
    return list(seen.values()), summaries



WATCH_COUNCILS = ("Liverpool", "Kensington and Chelsea", "Portsmouth", "Newcastle upon Tyne", "City of London", "Canterbury")

def council_coverage(args):
    """Independent PlanIt council checks; an unavailable source is never a zero."""
    checks = {}
    parts = urlsplit(args.api)
    for council in WATCH_COUNCILS:
        params = dict(parse_qsl(parts.query))
        params.update({"auth": council, "changed": str(max(args.days, args.council_lookback)),
                       "pg_sz": "1", "page": "1", "compress": "on"})
        for other in ("recent", "decided"):
            params.pop(other, None)
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), ""))
        try:
            payload = fetch_json(url)
            if not isinstance(payload, dict) or not isinstance(payload.get("total"), int) or not isinstance(payload.get("records"), list):
                raise RuntimeError("Invalid council response")
            if payload.get("error"):
                raise RuntimeError(str(payload["error"]))
            checks[council] = {"status": "RESPONDING", "changed_records_in_lookback": payload["total"],
                               "lookback_days": max(args.days, args.council_lookback),
                               "note": "PlanIt aggregate response only; council website not independently verified"}
        except RuntimeError as exc:
            checks[council] = {"status": "NOT VERIFIED", "error": str(exc),
                               "lookback_days": max(args.days, args.council_lookback),
                               "note": "Not a zero-result claim; retry next run and check official council weekly list"}
    return checks

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
    return first(app, "start_date", "start-date", "date_received", "date-received", "application-date")


def decision(app):
    return first(app, "app_state", "decision", "status", "outcome", "application-status", "decision-state")


def is_approved(app):
    value = str(decision(app)).lower()
    return any(word in value for word in ("approved", "granted", "grant", "permission", "permit"))


def as_float(value):
    if value in (None, ""):
        return None
    text = str(value).lower().replace(",", "").replace("m²", "").replace("sqm", "")
    match = re.search(r"[-+]?\d*\.?\d+", text)
    return float(match.group(0)) if match else None


def size(app):
    return as_float(first(app, "site_area", "site-area", "siteArea", "area", "size", "size_sq_m"))


def records(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("records", "entities", "results", "items", "applications"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def searchable_text(app):
    return " ".join(str(first(app, key)) for key in ("reference", "name", "description", "address", "postcode", "organisation-entity")).lower()


def keep(app, args):
    if args.area and not any(term.strip().lower() in searchable_text(app) for term in args.area if term.strip()):
        return False
    value = size(app)
    if value is not None and args.min_size is not None and value < args.min_size:
        return False
    if value is not None and args.max_size is not None and value > args.max_size:
        return False
    date = parse_date(application_date(app))
    # Do not reject older applications newly decided or materially changed in the search window.
    return not args.approved or is_approved(app)


def esc(value):
    return html.escape(str(value or ""), quote=True)


def row(app):
    app_date = application_date(app)
    value = size(app)
    size_text = "" if value is None else f"{value:g}"
    reference = first(app, "reference", "uid", "name", "council-reference", "application-reference", "id")
    address = first(app, "address", "site-address", "location")
    description = first(app, "description", "proposal", "summary", "name")
    status = decision(app)
    date_attr = parse_date(app_date)
    return (f'<tr data-address="{esc(address)}" data-description="{esc(description)}" data-size="{esc(size_text)}" '
            f'data-date="{esc(date_attr.isoformat() if date_attr else "")}" data-decision="{esc(status)}">'
            f"<td>{esc(reference)}</td><td>{esc(address)}</td><td>{esc(description)}</td>"
            f"<td>{esc(app_date or 'Not supplied')}</td><td>{esc(status or 'Not supplied')}</td><td>{esc(size_text)}</td></tr>")


def build_page(apps, args):
    rows = "\n".join(row(app) for app in apps) or '<tr><td colspan="6">No matching applications found.</td></tr>'
    area = esc(" ".join(args.area))
    minimum = "" if args.min_size is None else args.min_size
    maximum = "" if args.max_size is None else args.max_size
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>National Planning Applications</title><style>body{{font:16px Arial,sans-serif;margin:2rem}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:.6rem;text-align:left;vertical-align:top}}th{{background:#eee}}input{{padding:.5rem;font:inherit}}label{{display:block;margin-bottom:.5rem}}button{{padding:.6rem 1rem;font:inherit;cursor:pointer}}</style></head><body><h1>National Planning Applications</h1><p id="count">Showing {len(apps)} records.</p><form id="filters"><label>Area: <input id="area" value="{area}"></label><label>Application search: <input id="application" placeholder="Reference or description"></label><label>Min size (m²): <input id="min" type="number" step="any" value="{minimum}"></label><label>Max size (m²): <input id="max" type="number" step="any" value="{maximum}"></label><label>Application date, last N days (0 = all): <input id="days" type="number" min="0" value="0"></label><label><input id="approved" type="checkbox"> Approved only</label><button type="submit">Update search terms</button></form><table><thead><tr><th>Reference</th><th>Address</th><th>Description</th><th>Application date</th><th>Decision</th><th>Size (m²)</th></tr></thead><tbody id="results">{rows}</tbody></table><script>const rows=[...document.querySelectorAll('#results tr')],form=document.querySelector('#filters'),area=document.querySelector('#area'),application=document.querySelector('#application'),min=document.querySelector('#min'),max=document.querySelector('#max'),days=document.querySelector('#days'),approved=document.querySelector('#approved'),count=document.querySelector('#count');function apply(){{const a=area.value.toLowerCase().trim(),q=application.value.toLowerCase().trim(),lo=min.value===''?-Infinity:Number(min.value),hi=max.value===''?Infinity:Number(max.value),n=Number(days.value||0),cut=n>0?Date.now()-n*86400000:null;let shown=0;rows.forEach(r=>{{const text=((r.dataset.address||'')+' '+(r.dataset.description||'')+' '+(r.textContent||'')).toLowerCase(),s=r.dataset.size===''?null:Number(r.dataset.size),d=r.dataset.date||'',status=(r.dataset.decision||'').toLowerCase(),ok=(!a||text.includes(a))&&(!q||text.includes(q))&&(s===null||(s>=lo&&s<=hi))&&(!cut||(d&&Date.parse(d)>=cut))&&(!approved.checked||['approved','granted','grant','permission','permit'].some(x=>status.includes(x)));r.style.display=ok?'':'none';if(ok)shown++}});count.textContent='Showing '+shown+' records.'}}form.addEventListener('submit',e=>{{e.preventDefault();apply()}});[area,application,min,max,days,approved].forEach(e=>{{e.addEventListener('input',apply);e.addEventListener('change',apply)}});apply();</script></body></html>'''


def main():
    args = parse_args()
    fetched, summaries = fetch_planit(args)
    apps = [app for app in fetched if keep(app, args)]
    checks = council_coverage(args)
    if args.limit:
        apps = apps[:args.limit]
    output = Path(args.out_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "applications.json").write_text(json.dumps(apps, indent=2), encoding="utf-8")
    coverage = {"run_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "national_planit": "COMPLETE",
                "national_queries": summaries, "source_caveat": "PlanIt is not independent council portal verification",
                "councils": checks, "records_published": len(apps)}
    (output / "coverage.json").write_text(json.dumps(coverage, indent=2), encoding="utf-8")
    (output / "index.html").write_text(build_page(apps, args), encoding="utf-8")
    print(f"Created dashboard with {len(apps)} national applications in {output}")
    for council, state in checks.items():
        print(f"COUNCIL COVERAGE {council}: {state[\x27status\x27]}")


if __name__ == "__main__":
    main()
