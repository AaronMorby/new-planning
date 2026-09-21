#!/usr/bin/env python3
"""Build a dashboard of recent planning applications with filters by area, size, and age."""

import argparse
import datetime as dt
import html
import json
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

DEFAULT_AUTHORITY = "CAMBD"
DEFAULT_API = "https://www.planit.org.uk/api/recent/CAMBD/json"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download recent planning applications from PlanIt and build a searchable dashboard."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Only include applications received in the last N days.",
    )
    parser.add_argument(
        "--area",
        action="append",
        default=[],
        help="Address/description keyword to match. Repeat for multiple keywords.",
    )
    parser.add_argument(
        "--min-size",
        type=float,
        default=None,
        help="Minimum site area in square metres.",
    )
    parser.add_argument(
        "--max-size",
        type=float,
        default=None,
        help="Maximum site area in square metres.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Maximum number of applications to keep after filtering.",
    )
    parser.add_argument(
        "--authority",
        default=DEFAULT_AUTHORITY,
        help="PlanIt authority code. Example: CAMBD for Cambridge.",
    )
    parser.add_argument(
        "--api",
        default=DEFAULT_API,
        help="PlanIt API URL. Defaults to the recent Cambridge dataset.",
    )
    parser.add_argument(
        "--out-dir",
        default="docs",
        help="Directory to write the generated dashboard files to.",
    )
    return parser.parse_args()


def fetch_applications(api_url):
    request = Request(api_url, headers={"User-Agent": "new-planning-dashboard/1.0"})
    try:
        with urlopen(request, timeout=60) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise SystemExit(
            f"PlanIt API request failed with HTTP {exc.code}: {api_url}\n"
            "Check that the authority code and endpoint are still valid. Example: "
            "https://www.planit.org.uk/api/recent/CAMBD/json"
        ) from exc

    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("results", "applications", "items", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def coalesce(app, keys):
    for key in keys:
        value = app.get(key)
        if value not in (None, ""):
            return value
    return ""


def parse_date(value):
    if value in (None, ""):
        return None
    raw = str(value).strip()
    if not raw:
        return None

    candidates = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d %b %Y",
        "%d %B %Y",
        "%d %b %y",
        "%d %B %y",
    ]
    for fmt in candidates:
        try:
            normalized = raw[:10] if len(raw) > 10 and raw[4] == "-" else raw
            return dt.datetime.strptime(normalized, fmt).date()
        except ValueError:
            pass

    try:
        return dt.date.fromisoformat(raw[:10])
    except ValueError:
        pass

    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
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
    for key in (
        "site_area",
        "site_area_m2",
        "area",
        "area_sq_m",
        "size_sq_m",
        "size_m2",
        "gross_floor_area",
        "floor_area",
        "site_area_sq_m",
    ):
        value = as_float(app.get(key))
        if value is not None:
            return value
    return None


def app_matches_area(app, area_terms):
    if not area_terms:
        return True

    haystack = " ".join(
        str(value)
        for value in (
            coalesce(app, ("address", "site_address", "location", "site")),
            coalesce(app, ("description", "proposal", "summary", "details")),
            coalesce(app, ("authority", "council", "local_authority")),
        )
    ).lower()

    for term in area_terms:
        if term.lower() in haystack:
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

    received = coalesce(app, ("date_received", "received", "application_date", "date"))
    date_obj = parse_date(received)
    if date_obj is None:
        return True

    cutoff = dt.date.today() - dt.timedelta(days=days)
    return date_obj >= cutoff


def clean_cell(value):
    return html.escape(str(value), quote=False)


def build_rows(applications):
    rows = []
    for app in applications:
        reference = clean_cell(coalesce(app, ("id", "reference", "applicref", "application_number")))
        address = clean_cell(coalesce(app, ("address", "site_address", "location", "site")))
        description = clean_cell(coalesce(app, ("description", "proposal", "summary", "details")))
        received = clean_cell(coalesce(app, ("date_received", "received", "application_date", "date")))
        status = clean_cell(coalesce(app, ("decision", "status", "outcome")))
        size = get_size_m2(app)
        size_text = "" if size is None else f"{size:g}"
        date_key = parse_date(coalesce(app, ("date_received", "received", "application_date", "date")))
        iso_date = "" if date_key is None else date_key.isoformat()

        rows.append(
            f"<tr data-address=\"{html.escape(address, quote=True)}\" "
            f"data-description=\"{html.escape(description, quote=True)}\" "
            f"data-size=\"{html.escape(size_text, quote=True)}\" "
            f"data-date=\"{html.escape(iso_date, quote=True)}\">"
            f"<td>{reference}</td><td>{address}</td><td>{description}</td><td>{received}</td><td>{status}</td><td>{size_text}</td></tr>"
        )

    if not rows:
        rows.append('<tr><td colspan="6">No matching applications were returned.</td></tr>')
    return "\n".join(rows)


def build_html(applications, area_search, min_size, max_size, days):
    rows_html = build_rows(applications)
    page = f"""<!doctype html>
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
      form {{ display: grid; gap: .75rem; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); margin-bottom: 1rem; }}
      label {{ display: grid; gap: .25rem; font-weight: 600; }}
      input {{ padding: .5rem; font: inherit; }}
      button {{ padding: .6rem 1rem; font: inherit; }}
      .summary {{ margin-bottom: 1rem; }}
    </style>
  </head>
  <body>
    <h1>Planning Applications Dashboard</h1>
    <div class="summary">Showing {len(applications)} applications matching the active filters.</div>

    <form id="filters" onsubmit="return false;">
      <label>Area contains <input id="areaFilter" type="text" value="{html.escape(area_search or '', quote=True)}"></label>
      <label>Min size (m²) <input id="minSizeFilter" type="number" step="any" value="{'' if min_size is None else html.escape(str(min_size), quote=True)}"></label>
      <label>Max size (m²) <input id="maxSizeFilter" type="number" step="any" value="{'' if max_size is None else html.escape(str(max_size), quote=True)}"></label>
      <label>Days <input id="daysFilter" type="number" min="0" step="1" value="{days}"></label>
      <button type="button" id="applyFilters">Apply filters</button>
    </form>

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
      <tbody id="resultsBody">
        {rows_html}
      </tbody>
    </table>

    <script>
      const rows = Array.from(document.querySelectorAll('#resultsBody tr'));
      const areaInput = document.getElementById('areaFilter');
      const minInput = document.getElementById('minSizeFilter');
      const maxInput = document.getElementById('maxSizeFilter');
      const daysInput = document.getElementById('daysFilter');
      const applyButton = document.getElementById('applyFilters');

      function applyFilters() {{
        const area = areaInput.value.trim().toLowerCase();
        const minSize = minInput.value === '' ? Number.NEGATIVE_INFINITY : Number(minInput.value);
        const maxSize = maxInput.value === '' ? Number.POSITIVE_INFINITY : Number(maxInput.value);
        const days = Number(daysInput.value || 0);
        const cutoff = days > 0 ? Date.now() - (days * 24 * 60 * 60 * 1000) : null;

        rows.forEach((row) => {{
          const address = (row.dataset.address || '').toLowerCase();
          const description = (row.dataset.description || '').toLowerCase();
          const size = Number(row.dataset.size || '') || 0;
          const date = row.dataset.date ? new Date(row.dataset.date).getTime() : null;
          const matchesArea = !area || address.includes(area) || description.includes(area);
          const matchesSize = size >= minSize && size <= maxSize;
          const matchesDate = !cutoff || (date && date >= cutoff);
          row.style.display = (matchesArea && matchesSize && matchesDate) ? '' : 'none';
        }});
      }}

      applyButton.addEventListener('click', applyFilters);
      areaInput.addEventListener('input', applyFilters);
      minInput.addEventListener('input', applyFilters);
      maxInput.addEventListener('input', applyFilters);
      daysInput.addEventListener('input', applyFilters);
    </script>
  </body>
</html>
"""
    return page


def main():
    args = parse_args()

    if args.api == DEFAULT_API and args.authority != DEFAULT_AUTHORITY:
        args.api = f"https://www.planit.org.uk/api/applications.json?authority=627"

    applications = fetch_applications(args.api)
    filtered = []

    for app in applications:
        if not app_matches_area(app, args.area):
            continue
        if not app_matches_size(app, args.min_size, args.max_size):
            continue
        if not app_is_recent(app, args.days):
            continue
        filtered.append(app)

    filtered = filtered[: args.limit] if args.limit else filtered

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "applications.json").write_text(json.dumps(filtered, indent=2), encoding="utf-8")
    page = build_html(filtered, " ".join(args.area), args.min_size, args.max_size, args.days)
    (out_dir / "index.html").write_text(page, encoding="utf-8")

    print(f"Created dashboard with {len(filtered)} applications in {out_dir}")


if __name__ == "__main__":
    main()
