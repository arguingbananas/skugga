"""Minimal ASF/AMC reader and forward kinematics for the CMU mocap database.

Standard library only. Conventions follow the Acclaim format as used by CMU:

* Each bone has an `axis` (Euler angles, degrees) that defines its local frame C.
* A frame of AMC motion gives rotations M for each bone's DOFs (missing = 0).
* Local transform  L = C · M · C⁻¹,  global  R = R_parent · L.
* Bone end point   p = p_parent + length · R · direction.
* Euler angles are applied X, then Y, then Z (R = Rz · Ry · Rx).
* Lengths are in "ASF units"; CMU's `:units length 0.45` means
  metres = value * 0.0254 / 0.45.  Y is up.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

Mat = tuple  # 3x3 row-major, 9 floats
Vec = tuple  # 3 floats


def _rx(a: float) -> Mat:
    c, s = math.cos(a), math.sin(a)
    return (1, 0, 0, 0, c, -s, 0, s, c)


def _ry(a: float) -> Mat:
    c, s = math.cos(a), math.sin(a)
    return (c, 0, s, 0, 1, 0, -s, 0, c)


def _rz(a: float) -> Mat:
    c, s = math.cos(a), math.sin(a)
    return (c, -s, 0, s, c, 0, 0, 0, 1)


def mul(a: Mat, b: Mat) -> Mat:
    return tuple(
        a[r * 3] * b[c] + a[r * 3 + 1] * b[3 + c] + a[r * 3 + 2] * b[6 + c]
        for r in range(3)
        for c in range(3)
    )


def apply(m: Mat, v: Vec) -> Vec:
    return (
        m[0] * v[0] + m[1] * v[1] + m[2] * v[2],
        m[3] * v[0] + m[4] * v[1] + m[5] * v[2],
        m[6] * v[0] + m[7] * v[1] + m[8] * v[2],
    )


def transpose(m: Mat) -> Mat:
    return (m[0], m[3], m[6], m[1], m[4], m[7], m[2], m[5], m[8])


def euler_xyz(x_deg: float, y_deg: float, z_deg: float) -> Mat:
    d = math.radians
    return mul(_rz(d(z_deg)), mul(_ry(d(y_deg)), _rx(d(x_deg))))


IDENTITY: Mat = (1, 0, 0, 0, 1, 0, 0, 0, 1)


@dataclass
class Bone:
    name: str
    direction: Vec = (0.0, 0.0, 0.0)
    length: float = 0.0
    C: Mat = IDENTITY
    Cinv: Mat = IDENTITY
    dof: list[str] = field(default_factory=list)
    children: list[str] = field(default_factory=list)


@dataclass
class Skeleton:
    bones: dict[str, Bone]
    root_order: list[str]
    root_C: Mat
    root_Cinv: Mat
    scale: float  # ASF length units -> metres


def _axis_matrix(values: list[float], order: str) -> Mat:
    if order.upper() != "XYZ":
        raise ValueError(f"unsupported axis order {order!r}")
    return euler_xyz(*values)


def read_asf(path: Path) -> Skeleton:
    lines = path.read_text(encoding="latin-1").splitlines()
    bones: dict[str, Bone] = {"root": Bone("root")}
    root_order: list[str] = []
    root_axis = "XYZ"
    root_orient = [0.0, 0.0, 0.0]
    length_unit = 1.0
    section = None
    cur: Bone | None = None

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(":"):
            section = line.split()[0]
            continue
        tok = line.split()
        if section == ":units" and tok[0] == "length":
            length_unit = float(tok[1])
        elif section == ":root":
            if tok[0] == "order":
                root_order = [t.lower() for t in tok[1:]]
            elif tok[0] == "axis":
                root_axis = tok[1]
            elif tok[0] == "orientation":
                root_orient = [float(t) for t in tok[1:4]]
        elif section == ":bonedata":
            if tok[0] == "begin":
                cur = Bone("")
            elif tok[0] == "end" and cur is not None:
                bones[cur.name] = cur
                cur = None
            elif cur is not None:
                if tok[0] == "name":
                    cur.name = tok[1]
                elif tok[0] == "direction":
                    cur.direction = tuple(float(t) for t in tok[1:4])
                elif tok[0] == "length":
                    cur.length = float(tok[1])
                elif tok[0] == "axis":
                    cur.C = _axis_matrix([float(t) for t in tok[1:4]], tok[4])
                    cur.Cinv = transpose(cur.C)
                elif tok[0] == "dof":
                    cur.dof = [t.lower() for t in tok[1:]]
        elif section == ":hierarchy":
            if tok[0] in ("begin", "end"):
                continue
            bones[tok[0]].children.extend(tok[1:])

    root_C = _axis_matrix(root_orient, root_axis)
    return Skeleton(
        bones=bones,
        root_order=root_order,
        root_C=root_C,
        root_Cinv=transpose(root_C),
        scale=0.0254 / length_unit,
    )


def read_amc(path: Path) -> list[dict[str, list[float]]]:
    frames: list[dict[str, list[float]]] = []
    cur: dict[str, list[float]] | None = None
    started = False
    for raw in path.read_text(encoding="latin-1").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(":"):
            if line.upper().startswith(":DEGREES"):
                started = True
            continue
        if not started:
            continue
        tok = line.split()
        if len(tok) == 1 and tok[0].isdigit():
            cur = {}
            frames.append(cur)
        elif cur is not None:
            cur[tok[0]] = [float(t) for t in tok[1:]]
    return frames


def pose(skel: Skeleton, frame: dict[str, list[float]]) -> dict[str, Vec]:
    """Return the end point of every bone (and 'root') in metres."""
    rv = dict(zip(skel.root_order, frame.get("root", [])))
    pos = (rv.get("tx", 0.0), rv.get("ty", 0.0), rv.get("tz", 0.0))
    rot = mul(skel.root_C, mul(euler_xyz(rv.get("rx", 0.0), rv.get("ry", 0.0), rv.get("rz", 0.0)), skel.root_Cinv))

    out: dict[str, Vec] = {"root": tuple(c * skel.scale for c in pos)}
    stack = [(child, pos, rot) for child in skel.bones["root"].children]
    while stack:
        name, ppos, prot = stack.pop()
        b = skel.bones[name]
        dv = dict(zip(b.dof, frame.get(name, [])))
        m = euler_xyz(dv.get("rx", 0.0), dv.get("ry", 0.0), dv.get("rz", 0.0))
        grot = mul(prot, mul(b.C, mul(m, b.Cinv)))
        d = apply(grot, b.direction)
        end = (ppos[0] + b.length * d[0], ppos[1] + b.length * d[1], ppos[2] + b.length * d[2])
        out[name] = tuple(c * skel.scale for c in end)
        stack.extend((c, end, grot) for c in b.children)
    return out
