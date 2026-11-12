"""Compare the monitor displacements of two runs of this case, e.g. on 1 and on
4 processes: `python3 cases/cube_np/compare.py RUN_A RUN_B`, with RUN_* the run
folders (output/cube_np/<run>). Prints the largest difference over all
monitors, components and steps, relative to the largest displacement of RUN_A.

Every rank writes MONITOR<rank>.D: real*8 stream, one record per step of time
and then ux, uy, uz of each monitor of that rank, in the order of its
MONITOR<rank>.INFO (count, then the monitors' indices).
"""

import sys
from array import array
from pathlib import Path


def load(run):
    """{monitor index: [(ux, uy, uz) per step]}, and the times."""
    folder = Path(run) / "MONITOR"
    series, times = {}, None
    for info in sorted(folder.glob("MONITOR[0-9]*.INFO")):
        tokens = info.read_text().split()
        count = int(tokens[0])
        if count == 0:
            continue
        index = [int(t) for t in tokens[1 : 1 + count]]
        data = array("d")
        data.frombytes(info.with_suffix(".D").read_bytes())
        rec = 1 + 3 * count
        if len(data) % rec:
            raise SystemExit(f"{info.with_suffix('.D')}: {len(data)} values, not a multiple of {rec}")
        steps = [data[s : s + rec] for s in range(0, len(data), rec)]
        times = [s[0] for s in steps]
        for m, idx in enumerate(index):
            series[idx] = [tuple(s[1 + 3 * m : 4 + 3 * m]) for s in steps]
        print(f"{info}: {count} monitors, {len(steps)} steps")
    if not series:
        raise SystemExit(f"no monitors in {folder}")
    return series, times


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    a, ta = load(sys.argv[1])
    b, tb = load(sys.argv[2])
    if sorted(a) != sorted(b) or len(ta) != len(tb):
        raise SystemExit(f"monitors {len(a)} vs {len(b)}, steps {len(ta)} vs {len(tb)}")
    scale = max(abs(v) for s in a.values() for step in s for v in step) or 1.0
    diff, where = 0.0, None
    for idx in sorted(a):
        for n, (sa, sb) in enumerate(zip(a[idx], b[idx])):
            for c, (va, vb) in enumerate(zip(sa, sb)):
                if abs(va - vb) > diff:
                    diff, where = abs(va - vb), (idx, ta[n], "xyz"[c])
    print(f"{len(a)} monitors, {len(ta)} steps, max |u| = {scale:.3e}")
    print(f"max |u_a - u_b| / max |u| = {diff / scale:.3e}", end="")
    print(f" (monitor {where[0]}, t = {where[1]:.4g}, u{where[2]})" if where else "")


if __name__ == "__main__":
    main()
