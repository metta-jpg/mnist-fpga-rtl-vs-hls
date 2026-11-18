"""Her yapılandırma için en yüksek saat frekansını (Fmax) tahmin eder.

Yöntem: aynı RTL, saat kısıtı 4 ns (250 MHz) gibi sıkı bir değere çekilerek yeniden implemente
edilir. Araç zamanlamayı sağlamak için elinden geleni yapar; sonuçtaki en kötü setup payı (WNS)
ile Fmax = 1 / (T - WNS) bulunur. Sonuç bir tahmindir (saat darbesi genişliği gibi sınırlar
hesaba katılmaz).

Kullanım (repo kökünden):  python scripts/run_fmax.py [--period 4.0] [--workers 4]
Çıktı: results/fmax.csv  (cfg, period_ns, wns_ns, fmax_mhz)
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

from run_hls import REPO, XDC, hls, proj_sol  # noqa: E402
from run_impl import impl_configs  # noqa: E402
from run_sim import project_dir  # noqa: E402

VIVADO = Path(os.environ.get("VIVADO_BIN", "C:/Xilinx/Vivado/2023.2/bin")) / "vivado.bat"
ENV = {k: v for k, v in os.environ.items() if k != "NoDefaultCurrentDirectoryInExePath"}


def wns_of(report: Path) -> float:
    m = re.search(r"WNS\(ns\).*\n.*\n\s*(-?[\d.]+)", report.read_text(errors="replace"))
    if not m:
        raise RuntimeError(f"WNS okunamadı: {report}")
    return float(m.group(1))


def run_vivado(args: list[str], work: Path) -> None:
    work.mkdir(parents=True, exist_ok=True)
    p = subprocess.run([str(VIVADO), "-mode", "batch", "-nojournal", "-log", "vivado.log", *args],
                       cwd=work, capture_output=True, text=True, errors="replace",
                       env=ENV, stdin=subprocess.DEVNULL)
    (work / "stdout.log").write_text(p.stdout + p.stderr, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"Vivado hatası ({work})")


def rtl_job(cfg: str, w: int, p: int, dsp: bool, period: float) -> dict:
    proj = project_dir(w)
    params = json.loads((proj / "mem" / "params.json").read_text())
    out = REPO / "results" / "rtl" / cfg
    if (out / "timing_fmax.rpt").exists():  # önceki çalıştırmadan kalan sonuç
        return result(cfg, period, wns_of(out / "timing_fmax.rpt"))
    run_vivado(["-source", (REPO / "scripts" / "impl.tcl").as_posix(), "-tclargs", proj.as_posix(),
                str(w), str(p), str(params["sh1"]), str(params["acc1_bits"]),
                str(params["acc2_bits"]), "true" if dsp else "false", out.as_posix(), str(period)],
               REPO / "build" / "fmax" / cfg)
    return result(cfg, period, wns_of(out / "timing_fmax.rpt"))


def hls_job(cfg: str, w: int, sol: str, period: float) -> dict:
    proj, _, d = proj_sol(w, sol)
    vhdl = proj / d / "syn" / "vhdl"
    out = REPO / "results" / "hls" / cfg
    if (out / "timing_fmax.rpt").exists():
        return result(cfg, period, wns_of(out / "timing_fmax.rpt"))
    run_vivado(["-source", (REPO / "scripts" / "impl_hls.tcl").as_posix(), "-tclargs",
                vhdl.as_posix(), XDC(w).as_posix(), out.as_posix(), str(period)],
               REPO / "build" / "fmax" / cfg)
    return result(cfg, period, wns_of(out / "timing_fmax.rpt"))


def result(cfg: str, period: float, wns: float) -> dict:
    row = {"cfg": cfg, "period_ns": period, "wns_ns": wns, "fmax_mhz": round(1000.0 / (period - wns), 1)}
    print(row, flush=True)
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--period", type=float, default=4.0)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    jobs = [lambda c=c, w=w, p=p, d=d: rtl_job(c, w, p, d, args.period) for c, w, p, d in impl_configs()]
    hls_cfgs = [r["cfg"] for r in csv.DictReader(open(REPO / "results" / "hls" / "summary.csv"))]
    for c in hls_cfgs:
        w = int(c[1])
        sol = c.split("_", 1)[1]
        jobs.append(lambda c=c, w=w, sol=sol: hls_job(c, w, sol, args.period))
    # HLS RTL'i (syn/vhdl) yoksa önce sentezle (aynı projedeki solution'lar paylaşımlı: sırayla)
    for c in hls_cfgs:
        w, sol = int(c[1]), c.split("_", 1)[1]
        proj, _, d = proj_sol(w, sol)
        if not (proj / d / "syn" / "vhdl").exists() and not (REPO / "results" / "hls" / c / "timing_fmax.rpt").exists():
            hls(w, sol, "csynth")
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        rows = list(ex.map(lambda j: j(), jobs))
    with open(REPO / "results" / "fmax.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=["cfg", "period_ns", "wns_ns", "fmax_mhz"])
        wr.writeheader()
        wr.writerows(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
