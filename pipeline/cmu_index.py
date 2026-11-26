#!/usr/bin/env python3
"""Build an index of every trial in the CMU Graphics Lab Motion Capture Database.

Crawls the public subject pages on mocap.cs.cmu.edu (one request per second,
cached under data/raw/index_html/) and writes pipeline/cmu_index.json:

    [{"id": "02_03", "subject": 2, "subject_desc": "...",
      "trial": 3, "desc": "run/jog", "fps": 120}, ...]

The index is only used to choose clips for clips.toml. Standard library only.
"""
import html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "raw" / "index_html"
OUT = ROOT / "pipeline" / "cmu_index.json"
BASE = "http://mocap.cs.cmu.edu/search.php?subjectnumber={}"
USER_AGENT = "skugga-pipeline/0.1 (+https://github.com/arguingbananas/skugga)"
MAX_SUBJECT = 150  # the database ends at 144 (some numbers in between are unused)

ROW = re.compile(
    r"<TR[^>]*><TD></TD><TD>(\d+)</TD><TD>(.*?)</TD>.*?<TD>(\d+)</TD><TD><A HREF=\"badtrial",
    re.I | re.S,
)
SUBJ = re.compile(r"Subject #\d+ \((.*?)\)", re.I)


def fetch(subject: int) -> str:
    path = CACHE / f"{subject:02d}.html"
    if path.exists():
        return path.read_text(encoding="latin-1")
    req = urllib.request.Request(BASE.format(subject), headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        text = r.read().decode("latin-1")
    path.write_text(text, encoding="latin-1")
    time.sleep(1.0)
    return text


def main() -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    trials = []
    for s in range(1, MAX_SUBJECT + 1):
        page = fetch(s)
        rows = ROW.findall(page)
        if not rows:
            continue
        m = SUBJ.search(page)
        sdesc = html.unescape(m.group(1)).strip() if m else ""
        for trial, desc, fps in rows:
            trials.append({
                "id": f"{s:02d}_{int(trial):02d}",
                "subject": s,
                "subject_desc": sdesc,
                "trial": int(trial),
                "desc": html.unescape(re.sub(r"\s+", " ", desc)).strip(),
                "fps": int(fps),
            })
        print(f"subject {s:3d}: {len(rows):3d} trials  {sdesc}", file=sys.stderr)
    OUT.write_text(json.dumps(trials, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {len(trials)} trials to {OUT.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
