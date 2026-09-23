"""Download the public Lianjia/Beike listing snapshots used by this project.

Source: github.com/linpingta/lianjia-eroom-analysis (public crawl snapshots of
lianjia.com / ke.com listing pages). We take Beijing snapshots at 5 points in
time (2022-09 .. 2024-09) so the ETL can build both a modelling table (latest
listing per house id) and a price-history table, plus one snapshot per city
(Shanghai / Guangzhou / Shenzhen) for the multi-city error analysis.

Zero third-party dependencies (stdlib only) so it can run anywhere.

Usage:
    python scripts/fetch_data.py [--out data/raw]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.request
from pathlib import Path

REPO = "linpingta/lianjia-eroom-analysis"
BRANCH = "main"
API_DIR = "https://api.github.com/repos/{repo}/contents/{dir}?ref={branch}"
RAW_URL = "https://raw.githubusercontent.com/{repo}/{branch}/{path}"

# Beijing snapshots, roughly every 6 months, oldest first.
BJ_DATES = ["20220923", "20230401", "20231027", "20240501", "20240926"]

# Other cities: all usable snapshots (dates embedded in the name; 0-byte crawls skipped).
CITY_FILES = {
    "sh": [
        "sh_data/sh_eroom_time__20231112_detail__1699761883__area_3.csv",
        "sh_data/sh_eroom_time__20240601_detail__1717244236__area_3.csv",
        "sh_data/sh_eroom_time__20240605_detail__1717594528__area_3.csv",
        "sh_data/sh_eroom_time__20240615_detail__1718432544__area_3.csv",
    ],
    "sz": ["sz_data/sz_eroom_time__20231114_detail__1699973280__area_2.csv"],
    "gz": ["gz_data/gz_eroom_time__20231117_detail__1700230560__area_2.csv"],
    "hz": ["hz_data/hangzhou_eroom_time__20220115_detail__1642236238__area_17.csv"],
}

DATE_RE = re.compile(r"[0-9]{8}")


def list_dir(dir_name: str) -> list[dict]:
    url = API_DIR.format(repo=REPO, branch=BRANCH, dir=dir_name)
    req = urllib.request.Request(url, headers={"User-Agent": "homevalue-fetch"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def bj_targets(all_snapshots: bool = False) -> dict[str, str]:
    """Return {local filename: url} for the chosen Beijing snapshot dates.

    all_snapshots=False: the 5 canonical snapshots (快速复现).
    all_snapshots=True : every usable snapshot in the source repo (~35 期,2022-09..2024-07),
    跳过 0 字节/过小的残缺抓取。
    """
    entries = [e for e in list_dir("bj_data") if e["name"].endswith(".csv")]
    found: dict[str, dict] = {}
    for e in entries:
        m = DATE_RE.search(e["name"])
        keep = m and (all_snapshots or m.group(0) in BJ_DATES)
        if keep and (not all_snapshots or e["size"] > 1_000_000):
            # --all: <1MB 的快照是残缺抓取,跳过;默认模式保留 2024-09 残缺期(口径可复现)
            # keep the largest file per date (2024-09 has a truncated variant)
            prev = found.get(m.group(0))
            if prev is None or e["size"] > prev["size"]:
                found[m.group(0)] = e
    if not all_snapshots:
        missing = set(BJ_DATES) - set(found)
        if missing:
            raise RuntimeError(f"missing Beijing snapshots: {sorted(missing)}")
    return {
        "bj__" + e["name"]: e["download_url"]
        for _, e in sorted(found.items())
    }


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "homevalue-fetch"})
    with urllib.request.urlopen(req, timeout=180) as resp, dest.open("wb") as f:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)


def peek(path: Path) -> tuple[int, list[str]]:
    with path.open("r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        header = next(reader)
        n = sum(1 for _ in reader)
    return n, header


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/raw", help="download directory")
    parser.add_argument("--all", action="store_true",
                        help="下载源仓库全部可用快照(~35 期),默认仅 5 期快速复现")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    targets = bj_targets(all_snapshots=args.all)
    for city, rels in CITY_FILES.items():
        for rel in rels:
            targets[city + "__" + Path(rel).name] = RAW_URL.format(
                repo=REPO, branch=BRANCH, path=rel
            )

    for fname, url in targets.items():
        dest = out / fname
        if dest.exists() and dest.stat().st_size > 1000:
            print(f"[skip] {fname} already present ({dest.stat().st_size} bytes)")
        else:
            print(f"[get ] {fname} ...", flush=True)
            download(url, dest)
            print(f"[done] {fname} ({dest.stat().st_size:,} bytes)")
        rows, header = peek(dest)
        print(f"       rows={rows:,}  cols={len(header)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
