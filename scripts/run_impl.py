"""RTL (VHDL) projeleri için regresyon ve implementasyon yöneticisi.

Kullanım (repo kökünden):
    python scripts/run_impl.py --sim               # 6 yapılandırma x 10000 görüntü simülasyon
    python scripts/run_impl.py --cfg w8_p1_dsp     # tek implementasyon
    python scripts/run_impl.py --all               # 12 implementasyon

Simülasyon sonuçları: results/rtl/sim_summary.csv
İmplementasyon sonuçları: results/rtl/summary.csv, raporlar results/rtl/<cfg>/
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_sim import REPO, build_generics, default_sources, project_dir, run_sim  # noqa: E402

VIVADO = Path(os.environ.get("VIVADO_BIN", "C:/Xilinx/Vivado/2023.2/bin")) / "vivado.bat"
RESULTS = REPO / "results" / "rtl"
BITS = (8, 4, 2)
PS = (1, 8)


def sim_configs():
    return [(f"w{w}_p{p}", w, p) for w in BITS for p in PS]


def impl_configs():
    return [(f"w{w}_p{p}_{'dsp' if d else 'lut'}", w, p, d) for w in BITS for p in PS for d in (True, False)]


# ---------------------------------------------------------------- simülasyon
def run_one_sim(name: str, w: int, p: int, n: int) -> dict:
    params = project_dir(w) / "mem" / "params.json"
    g = build_generics(w, [f"P={p}", f"N_IMAGES={n}"])
    work = REPO / "build" / "sim" / f"reg_{name}"
    res = run_sim(default_sources("tb_mnist_mlp", w), "tb_mnist_mlp", g, work)
    (work / "run.log").write_text(res.log, encoding="utf-8", errors="replace")
    expected = round(json.loads(params.read_text())["int_acc"] * n) if n == 10000 else None
    row = {"cfg": name, "passed": res.passed, "mismatch": res.mismatch, "correct": res.correct,
           "total": res.total, "cycles": res.cycles, "python_correct": expected}
    print(f"{name}: {row}", flush=True)
    return row


def sim_regression(n: int) -> int:
    with ThreadPoolExecutor(max_workers=6) as ex:
        rows = list(ex.map(lambda c: run_one_sim(c[0], c[1], c[2], n), sim_configs()))
    RESULTS.mkdir(parents=True, exist_ok=True)
    with open(RESULTS / "sim_summary.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    ok = all(r["passed"] and r["mismatch"] == 0 for r in rows)
    ok = ok and all(r["python_correct"] in (None, r["correct"]) for r in rows)
    print("REGRESYON " + ("GECTI" if ok else "BASARISIZ"))
    return 0 if ok else 1


# ----------------------------------------------------------- implementasyon
def _num(pattern: str, text: str) -> float | None:
    m = re.search(pattern, text, re.MULTILINE)
    return float(m.group(1)) if m else None


def parse_reports(out: Path) -> dict:
    util = (out / "utilization.rpt").read_text(errors="replace")
    timing = (out / "timing.rpt").read_text(errors="replace")
    power = (out / "power.rpt").read_text(errors="replace")
    # Design Timing Summary tablosunda başlık satırından sonraki ilk sayı satırı
    wns = None
    m = re.search(r"WNS\(ns\).*\n.*\n\s*(-?[\d.]+)", timing)
    if m:
        wns = float(m.group(1))
    return {
        "LUT": _num(r"^\|\s*Slice LUTs\*?\s*\|\s*(\d+)", util),
        "FF": _num(r"^\|\s*Slice Registers\s*\|\s*(\d+)", util),
        "BRAM": _num(r"^\|\s*Block RAM Tile\s*\|\s*([\d.]+)", util),
        "DSP": _num(r"^\|\s*DSPs\s*\|\s*(\d+)", util),
        "WNS_ns": wns,
        "total_power_W": _num(r"^\|\s*Total On-Chip Power \(W\)\s*\|\s*([\d.]+)", power),
        "dynamic_power_W": _num(r"^\|\s*Dynamic \(W\)\s*\|\s*([\d.]+)", power),
    }


def run_one_impl(name: str, w: int, p: int, dsp: bool) -> dict:
    proj = project_dir(w)
    params = json.loads((proj / "mem" / "params.json").read_text())
    out = RESULTS / name
    out.mkdir(parents=True, exist_ok=True)
    args = [proj.as_posix(), str(w), str(p), str(params["sh1"]), str(params["acc1_bits"]),
            str(params["acc2_bits"]), "true" if dsp else "false", out.as_posix()]
    work = REPO / "build" / "impl" / name
    work.mkdir(parents=True, exist_ok=True)
    cmd = [str(VIVADO), "-mode", "batch", "-nojournal", "-log", "vivado.log",
           "-source", (REPO / "scripts" / "impl.tcl").as_posix(), "-tclargs", *args]
    p_ = subprocess.run(cmd, cwd=work, capture_output=True, text=True, errors="replace")
    if p_.returncode != 0 or not (out / "power.rpt").exists():
        tail = "\n".join((p_.stdout + p_.stderr).splitlines()[-30:])
        raise RuntimeError(f"{name} implementasyonu başarısız:\n{tail}")
    row = {"cfg": name, "W_BITS": w, "P": p, "USE_DSP": dsp, **parse_reports(out)}
    print(f"{name}: {row}", flush=True)
    return row


def write_summary(rows: list[dict]) -> None:
    path = RESULTS / "summary.csv"
    existing = {}
    if path.exists():
        with open(path, newline="") as f:
            existing = {r["cfg"]: r for r in csv.DictReader(f)}
    for r in rows:
        existing[r["cfg"]] = r
    order = [c[0] for c in impl_configs()]
    with open(path, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(existing[c] for c in order if c in existing)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("--n", type=int, default=10000, help="simülasyonda görüntü sayısı")
    ap.add_argument("--cfg", action="append", default=[])
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    if args.sim:
        return sim_regression(args.n)
    cfgs = impl_configs() if args.all else [c for c in impl_configs() if c[0] in args.cfg]
    if not cfgs:
        ap.error("--sim, --all veya geçerli bir --cfg verin")
    rows = []
    for c in cfgs:
        rows.append(run_one_impl(*c))
        write_summary(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
