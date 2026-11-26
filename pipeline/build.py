#!/usr/bin/env python3
"""Build point-light clips from the CMU mocap database.

    python3 pipeline/build.py            # build every clip in clips.toml
    python3 pipeline/build.py 02_01 ...  # build only these ids

Reads pipeline/clips.toml, downloads the needed ASF/AMC files from
mocap.cs.cmu.edu into data/raw/cmu/ (cached, gitignored), runs forward
kinematics and writes:

    data/clips/<id>.json   one clip: 31 markers per frame, in millimetres
    data/clips/index.json  list of all built clips

Each clip is normalised so that, at its first frame, the pelvis is at x=z=0
and the figure faces +x; the lowest marker over the whole clip sits at y=0.
Axes: x forward, y up, z to the figure's left (right-handed).

Standard library only.
"""
from __future__ import annotations

import json
import math
import sys
import time
import tomllib
import urllib.request
from pathlib import Path

from asfamc import pose, read_amc, read_asf

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "cmu"
OUT = ROOT / "data" / "clips"
MANIFEST = ROOT / "pipeline" / "clips.toml"
INDEX = ROOT / "pipeline" / "cmu_index.json"
CATEGORIES = ROOT / "data" / "categories.json"
BASE = "http://mocap.cs.cmu.edu/subjects/{s:02d}/{name}"
USER_AGENT = "skugga-pipeline/0.1 (+https://github.com/arguingbananas/skugga)"

# Point-light markers: name -> bone end points to average. All 31 joints of
# the CMU skeleton: the root (pelvis) and the far end of each of its 30 bones.
MARKERS: dict[str, tuple[str, ...]] = {
    "pelvis": ("root",),
    "lhip": ("lhipjoint",), "rhip": ("rhipjoint",),
    "lknee": ("lfemur",), "rknee": ("rfemur",),
    "lankle": ("ltibia",), "rankle": ("rtibia",),
    "lfoot": ("lfoot",), "rfoot": ("rfoot",),        # ball of the foot
    "ltoes": ("ltoes",), "rtoes": ("rtoes",),
    "lowerback": ("lowerback",), "upperback": ("upperback",),
    "neck": ("thorax",),                              # base of the neck
    "lowerneck": ("lowerneck",), "upperneck": ("upperneck",),
    "head": ("head",),                                # top of the head
    "lshoulder": ("lclavicle",), "rshoulder": ("rclavicle",),
    "lelbow": ("lhumerus",), "relbow": ("rhumerus",),
    "lwrist": ("lradius",), "rwrist": ("rradius",),
    "lhand": ("lwrist",), "rhand": ("rwrist",),      # middle of the hand
    "lknuckles": ("lhand",), "rknuckles": ("rhand",),
    "lfingers": ("lfingers",), "rfingers": ("rfingers",),
    "lthumb": ("lthumb",), "rthumb": ("rthumb",),
}
NAMES = list(MARKERS)
# Pairs of markers on one rigid bone, used to check for broken data.
RIGID = [("lelbow", "lwrist"), ("relbow", "rwrist"), ("lknee", "lankle"), ("rknee", "rankle"),
         ("lhip", "lknee"), ("rhip", "rknee"), ("lshoulder", "lelbow"), ("rshoulder", "relbow")]


def download(subject: int, name: str) -> Path:
    path = RAW / f"{subject:02d}" / name
    if path.exists() and path.stat().st_size > 0:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    url = BASE.format(s=subject, name=name)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    tmp.rename(path)
    time.sleep(1.0)  # be polite to the CMU server
    return path


def markers(p: dict[str, tuple]) -> list[tuple[float, float, float]]:
    out = []
    for bones in MARKERS.values():
        pts = [p[b] for b in bones]
        out.append(tuple(sum(c[i] for c in pts) / len(pts) for i in range(3)))
    return out


def build_clip(entry: dict, info: dict, cfg: dict) -> dict:
    subject = info["subject"]
    asf = read_asf(download(subject, f"{subject:02d}.asf"))
    amc = read_amc(download(subject, f"{info['id']}.amc"))

    src_fps = info["fps"]
    step = max(1, round(src_fps / cfg["fps"]))
    fps = src_fps / step
    start = int(entry.get("start", 0.0) * src_fps)
    stop_s = entry.get("end")
    stop = int(stop_s * src_fps) if stop_s is not None else len(amc)
    stop = min(stop, len(amc), start + int(cfg["max_seconds"] * src_fps))
    frames = [markers(pose(asf, amc[i])) for i in range(start, stop, step)]
    if len(frames) < fps:  # under one second
        raise ValueError(f"only {len(frames)} frames")

    # Normalise: pelvis at x=z=0, facing +x (CMU: y up), floor at y=0.
    pel, lh, rh = (NAMES.index(n) for n in ("pelvis", "lhip", "rhip"))
    f0 = frames[0]
    hx, hz = f0[rh][0] - f0[lh][0], f0[rh][2] - f0[lh][2]
    # forward = up x (right hip - left hip)  ->  (hz, 0, -hx)
    fx, fz = hz, -hx
    ang = math.atan2(fz, fx)
    ca, sa = math.cos(-ang), math.sin(-ang)
    ox, oz = f0[pel][0], f0[pel][2]
    floor = min(pt[1] for fr in frames for pt in fr)

    def tf(pt):
        x, z = pt[0] - ox, pt[2] - oz
        # rotate about y by -ang so forward maps to +x; flip z for right-handed x-fwd/z-left
        rx = ca * x - sa * z
        rz = sa * x + ca * z
        return (round(rx * 1000), round((pt[1] - floor) * 1000), round(-rz * 1000))

    out_frames = [[c for pt in fr for c in tf(pt)] for fr in frames]

    # Validate: rigid bone lengths should not change between frames.
    worst = 0.0
    for a, b in RIGID:
        ia, ib = NAMES.index(a), NAMES.index(b)
        ls = [math.dist(fr[ia], fr[ib]) for fr in frames]
        worst = max(worst, (max(ls) - min(ls)) / max(ls))
    if worst > 0.01:
        raise ValueError(f"bone length varies by {worst:.1%}")

    return {
        "id": info["id"],
        "category": entry["category"],
        "source": f"CMU Graphics Lab Motion Capture Database, trial {info['id']}",
        "description": info["desc"],
        "fps": fps,
        "units": "mm",
        "axes": "x forward, y up, z left",
        "markers": NAMES,
        "frames": out_frames,
    }


def main(argv: list[str]) -> int:
    cfg = tomllib.loads(MANIFEST.read_text())
    entries = cfg["clip"]
    index = {x["id"]: x for x in json.loads(INDEX.read_text())}
    categories = set(json.loads(CATEGORIES.read_text())["categories"])

    ids = [e["id"] for e in entries]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        print(f"duplicate ids in clips.toml: {sorted(dupes)}", file=sys.stderr)
        return 1
    for e in entries:
        if e["category"] not in categories:
            print(f"{e['id']}: unknown category {e['category']!r}", file=sys.stderr)
            return 1
        if e["id"] not in index:
            print(f"{e['id']}: not in cmu_index.json", file=sys.stderr)
            return 1

    wanted = set(argv) or set(ids)
    OUT.mkdir(parents=True, exist_ok=True)
    failed = []
    for e in entries:
        if e["id"] not in wanted:
            continue
        info = index[e["id"]]
        try:
            clip = build_clip(e, info, cfg)
        except Exception as exc:  # report and continue with the rest
            failed.append(e["id"])
            print(f"FAIL {e['id']:>7} {e['category']:<14} {exc}", file=sys.stderr)
            continue
        path = OUT / f"{e['id']}.json"
        path.write_text(json.dumps(clip, separators=(",", ":")) + "\n")
        secs = len(clip["frames"]) / clip["fps"]
        print(f"ok   {e['id']:>7} {e['category']:<14} {secs:5.1f}s {path.stat().st_size // 1024:4d} KB  {info['desc'][:40]}")

    # Rebuild the index from every clip file listed in the manifest.
    listing = []
    for e in entries:
        path = OUT / f"{e['id']}.json"
        if not path.exists():
            continue
        clip = json.loads(path.read_text())
        listing.append({
            "id": clip["id"],
            "category": clip["category"],
            "file": path.name,
            "frames": len(clip["frames"]),
            "fps": clip["fps"],
        })
    (OUT / "index.json").write_text(json.dumps({"markers": NAMES, "clips": listing}, indent=1) + "\n")
    print(f"\n{len(listing)} clips in data/clips/index.json; {len(failed)} failed {failed or ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
