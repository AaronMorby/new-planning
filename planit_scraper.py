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
        raise SystemExit(
            f"Planning Data API request failed with HTTP {exc.code}: {url}"
        ) from exc


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
        pass

    return None


def as_float(value):
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None

    text = (
        text.replace("sqm", "")
        .replace("sqm.", "")
        .replace("m²", "")
        .replace("m2", "")
        .replace("square metres", "")
        .replace("sq m", "")
        .replace(",", "")
    )
    match = re.search(r"[-+]?\d*\.?\d+", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def get_size_m2(app):
    # Try common keys in nested objects
    candidates = [
        app.get("site-area"),
        app.get("site_area"),
        app.get("siteArea"),
        app.get("area"),
        app.get("site-area-sq-m"),
        app.get("size"),
        app.get("size_sq_m"),
        app.get("square_metres"),
        app.get("gross-floor-area"),
    ]
    for value in candidates:
        size = as_float(value)
        if size is not None:
            return size

    # Try recursively across nested data structures
    for value in flatten_values(app):
        size = as_float(value)
        if size is not None and size > 0:
            return size
    return None


def app_matches_area(app, terms):
    if not terms:
        return True

    text = " ".join(flatten_values(app)).lower()
    for term in terms:
        if term.lower() in text:
            return True
    return False


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

    # Try several possible date fields
    date_value = (
        first_present(app, ["start-date", "start_date", "date", "application-date", "received-date"]) or
        get_text(app, "decision-date", "decision_date") or
        first_present(app, ["date_received", "received"])
    )
    date_obj = parse_date(date_value)
    if date_obj is None:
        return True

    cutoff = dt.date.today() - dt.timedelta(days=days)
    return date_obj >= cutoff


def clean_html(value):
    return html.escape(str(value), quote=False)


def get_row_text(app):
    ref = first_present(app, ["reference", "id", "application-reference", "applicationNumber", "application_no"]) or ""
    address = first_present(app, ["address", "site_address", "site-address", "address_text", "location"]) or ""
    desc = first_present(app, ["description", "proposal", "summary", "title"]) or ""
    received = first_present(app, ["start-date", "start_date", "date", "application-date", "received-date"]) or ""
    status = first_present(app, ["decision", "status", "outcome"]) or ""
    size = get_size_m2(app)
    size_text = "" if size is None else f"{size:g}"

    return (
        f"<tr data-address=\"{clean_html(address)}\" "
        f"data-description=\"{clean_html(desc)}\" "
        f"data-size=\"{clean_html(size_text)}\">"
        f"<td>{clean_html(ref)}</td>"
        f"<td>{clean_html(address)}</td>"
        f"<td>{clean_html(desc)}</td>"
        f"<td>{clean_html(received)}</td>"
        f"<td>{clean_html(status)}</td>"
        f"<td>{clean_html(size_text)}</td>"
        f"</tr>"
    )


def build_page(applications, area_text, min_size, max_size, days):
    rows_html = "\n".join(get_row_text(app) for app in applications) if applications else '<tr><td colspan="6">No matching applications found.</td></tr>'
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Planning Applications Dashboard</title>
  <style>
    body {{ font: 16px Arial, sans-serif; margin: 2rem; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: .6rem; text-align: left; vertical-align: top; }}
    th {{ background: #eee; }}
    input {{ padding: .5rem; font: inherit; }}
    label {{ display: block; margin-bottom: .5rem; }}
  </style>
</head>
<body>
  <h1>Planning Applications Dashboard</h1>
  <p>Showing {len(applications)} matching applications.</p>

  <div style="margin-bottom: 1rem;">
    <label>Area: <input id="areaFilter" type="text" value="{html.escape(area_text or '', quote=True)}"></label>
    <label>Min size (m²): <input id="minSize" type="number" step="any" value="{'' if min_size is None else min_size}"></label>
    <label>Max size (m²): <input id="maxSize" type="number" step="any" value="{'' if max_size is None else max_size}"></label>
    <label>Days: <input id="days" type="number" min="0" value="{days}"></label>
  </div>

  <table>
    <thead>
      <tr>
        <th>Reference</th>
        <th>Address</th>
        <th>Description</th>
        <th>Received</th>
        <th>Status</th>
        <th>Size (m²)</th>
      </tr>
    </thead>
    <tbody id="results">
      {rows_html}
    </tbody>
  </table>

  <script>
    const rows = [...document.querySelectorAll('#results tr')];
    const areaFilter = document.getElementById('areaFilter');
    const minSize = document.getElementById('minSize');
    const maxSize = document.getElementById('maxSize');
    const days = document.getElementById('days');

    function applyFilters() {{
      const area = (areaFilter.value || '').toLowerCase().trim();
      const min = minSize.value === '' ? Number.NEGATIVE_INFINITY : Number(minSize.value);
      const max = maxSize.value === '' ? Number.POSITIVE_INFINITY : Number(maxSize.value);
      const cutoff = Number(days.value || 0) > 0 ? Date.now() - (Number(days.value || 0) * 86400000) : null;

      rows.forEach((row) => {{
        const address = (row.dataset.address || '').toLowerCase();
        const description = (row.dataset.description || '').toLowerCase();
        const size = Number(row.dataset.size || '') || 0;
        const date = row.dataset.date || '';
        const matchesArea = !area || address.includes(area) || description.includes(area);
        const matchesSize = size >= min && size <= max;
        const matchesDate = !cutoff || (date && new Date(date).getTime() >= cutoff);

        row.style.display = matchesArea && matchesSize && matchesDate ? '' : 'none';
      }});
    }}

    [areaFilter, minSize, maxSize, days].forEach((el) => el.addEventListener('input', applyFilters));
  </script>
</body>
</html>
"""

def main():
    args = parse_args()
    payload = fetch_json(args.api)

    items = []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("items") or payload.get("results") or payload.get("applications") or []

    filtered = []
    for app in items:
        if not app_matches_area(app, args.area):
            continue
        if not app_matches_size(app, args.min_size, args.max_size):
            continue
        if not app_is_recent(app, args.days):
            continue
        filtered.append(app)

    filtered = filtered[:args.limit] if args.limit else filtered

    out_dir = Path(args.out_dir)
    out_dir.mkdir(exist_ok=True, parents=True)

    (out_dir / "applications.json").write_text(json.dumps(filtered, indent=2), encoding="utf-8")
    (out_dir / "index.html").write_text(build_page(filtered, " ".join(args.area), args.min_size, args.max_size, args.days), encoding="utf-8")

    print(f"Created dashboard with {len(filtered)} applications in {out_dir}")


if __name__ == "__main__":
    main()
