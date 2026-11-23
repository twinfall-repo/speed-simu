"""SPEED's monitored points of a run, one text file per point:

    python monitors.py RUN_DIR

SPEED writes the points of LS.input (MLST in SPEED.input) every TMONITOR
steps into RUN_DIR/MONITOR, one set of files per MPI process: MONITORxxxxx.INFO
lists the points the process holds (their count, then their numbers in
LS.input), and MONITORxxxxx.D, .V, .A, .S, .E, .O hold, as raw float64 in
time order, the time and then each of its points' values, in the order of
their numbers: 3 components of displacement, velocity, acceleration and
rotation, 6 of stress and strain (OPTIOUT says which are there). The values
are interpolated at the point inside its element.

Writes RUN_DIR/monitors/point_NN.txt, NN its number in LS.input: a header
with its coordinates, then the time and every quantity written, in columns.
"""

import sys
from pathlib import Path

import numpy as np

QUANTITIES = (  # suffix, name, components
    (".D", "displacement", ("ux", "uy", "uz")),
    (".V", "velocity", ("vx", "vy", "vz")),
    (".A", "acceleration", ("ax", "ay", "az")),
    (".S", "stress", ("sxx", "syy", "szz", "sxy", "syz", "szx")),
    (".E", "strain", ("exx", "eyy", "ezz", "exy", "eyz", "ezx")),
    (".O", "rotation", ("ox", "oy", "oz")),
)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        raise SystemExit(__doc__)
    run = Path(argv[0])
    monitor = run / "MONITOR"
    points = [line.split() for line in (run / "LS.input").read_text().splitlines()[1:] if line.strip()]
    infos = sorted(monitor.glob("MONITOR*.INFO"))
    if not infos:
        raise SystemExit(f"no MONITOR*.INFO in {monitor}: did SPEED run with MLST in SPEED.input?")

    series = {}  # point number -> {name: (columns, values (nt, ncomp))}
    times = None
    for info in infos:
        numbers = [int(v) for v in info.read_text().split()]
        count, held = numbers[0], numbers[1:1 + numbers[0]]
        if count == 0:
            continue
        for suffix, name, components in QUANTITIES:
            path = info.with_suffix(suffix)
            if not path.exists():
                continue
            raw = np.fromfile(path, dtype="<f8")
            width = 1 + len(components) * count
            if raw.size % width:
                raise SystemExit(f"{path}: {raw.size} values, not a multiple of {width} "
                                 f"(time and {len(components)} x {count} points)")
            rows = raw.reshape(-1, width)
            if times is None or len(rows[:, 0]) > len(times):
                times = rows[:, 0]
            for k, number in enumerate(held):
                values = rows[:, 1 + len(components) * k: 1 + len(components) * (k + 1)]
                series.setdefault(number, {})[name] = (components, values)
        print(f"{info.name}: points {held}", flush=True)

    out = run / "monitors"
    out.mkdir(exist_ok=True)
    for number in sorted(series):
        columns, blocks = ["t"], []
        for _, name, _ in QUANTITIES:
            if name in series[number]:
                components, values = series[number][name]
                columns += list(components)
                blocks.append(values)
        n = min(len(b) for b in blocks)
        table = np.column_stack([times[:n]] + [b[:n] for b in blocks])
        x, y, z = points[number - 1][1:4]
        path = out / f"point_{number:02d}.txt"
        np.savetxt(path, table, fmt="%.9e",
                   header=f"point {number} of LS.input at x {x} y {y} z {z} (DTM frame)\n" + " ".join(columns))
        print(f"wrote {path}: {n} times, {table.shape[1] - 1} values each", flush=True)
    missing = sorted(set(range(1, len(points) + 1)) - set(series))
    if missing:
        print(f"MISSING: points {missing} of LS.input are in no MONITOR*.INFO", flush=True)


if __name__ == "__main__":
    main()
