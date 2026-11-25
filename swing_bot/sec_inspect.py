"""Print the real structure of an SEC Insider Transactions (Forms 3/4/5) quarterly file. No trading logic here.

Respects SEC fair access: declared User-Agent (env SEC_USER_AGENT, a project name), at most a few requests.
"""
import io
import os
import sys
import zipfile

import pandas as pd
import requests

URLS = ["https://www.sec.gov/files/structureddata/data/form-345/{q}_form345.zip",
        "https://www.sec.gov/files/dera/data/form-345/{q}_form345.zip",
        "https://www.sec.gov/dera/data/form-345/{q}_form345.zip"]


def fetch(quarter: str, session=None) -> bytes:
    ua = os.environ.get("SEC_USER_AGENT") or "swing-bot-research no-reply@users.noreply.github.com"  # unset repo variable arrives as ""
    s = session or requests.Session()
    s.headers.update({"User-Agent": ua, "Accept-Encoding": "gzip, deflate"})
    errors = []
    for template in URLS:
        url = template.format(q=quarter)
        r = s.get(url, timeout=120)
        if r.status_code == 200 and r.content[:2] == b"PK":
            print(f"downloaded {url} ({len(r.content):,} bytes)")
            return r.content
        errors.append(f"{url} -> HTTP {r.status_code}")
    raise RuntimeError("could not download; tried: " + "; ".join(errors))


def describe(blob: bytes, sample_rows=3) -> dict:
    """Return {table_name: {'rows': n, 'columns': [...], 'sample': [...]}} for every tab-separated file in the zip."""
    out = {}
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for name in z.namelist():
            if not name.lower().endswith((".tsv", ".txt", ".csv")):
                out[name] = {"rows": None, "columns": [], "sample": []}
                continue
            with z.open(name) as f:
                df = pd.read_csv(f, sep="\t", dtype=str, low_memory=False, on_bad_lines="skip")
            out[name] = {"rows": len(df), "columns": list(df.columns), "sample": df.head(sample_rows).to_dict("records")}
    return out


def main(argv=None):
    quarter = (argv or sys.argv[1:] or ["2015q1"])[0]
    info = describe(fetch(quarter))
    for name, d in info.items():
        print(f"\n=== {name}: {d['rows']} rows")
        print("columns:", d["columns"])
        for row in d["sample"]:
            print("  ", {k: v for k, v in list(row.items())[:12]})
    return info


if __name__ == "__main__":
    main()
