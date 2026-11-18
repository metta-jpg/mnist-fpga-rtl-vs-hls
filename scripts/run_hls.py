"""Vitis HLS projeleri için yönetici: C simülasyonu, sentez, co-simülasyon, RTL dışa aktarma
ve üretilen RTL'in RTL projeleriyle aynı Vivado akışından geçirilmesi.

Kullanım (repo kökünden):
    python scripts/run_hls.py --csim            # 3 bit, 10.000 görüntü C simülasyonu
    python scripts/run_hls.py --all             # 18 solution: csynth + cosim + Vivado impl
    python scripts/run_hls.py --sol 8 par8_dsp  # tek solution (hls/mnist_w8/par8, dsp)

Sonuçlar: results/hls/summary.csv, raporlar results/hls/<cfg>/
Dışa aktarılan RTL (Vivado projeleri için): hls/mnist_wN/vivado/rtl/  (par8 / dsp)
HLS projeleri: hls/mnist_wN/<naive|pipe|par8>, solution'lar: dsp, lut
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_impl import parse_reports  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
HLS_BIN = Path(os.environ.get("VITIS_HLS_BIN", "C:/Xilinx/Vitis_HLS/2023.2/bin")) / "vitis_hls.bat"
VIVADO = Path(os.environ.get("VIVADO_BIN", "C:/Xilinx/Vivado/2023.2/bin")) / "vivado.bat"
RESULTS = REPO / "results" / "hls"
BITS = (8, 4, 2)
VARIANTS = ("naive", "pipe", "par8")
SOLUTIONS = [f"{v}_{d}" for v in VARIANTS for d in ("dsp", "lut")]  # sonuç adları: <varyant>_<dsp|lut>
EXPORT_SOL = "par8_dsp"  # Vivado projelerine konan RTL


def XDC(bits: int) -> Path:  # noqa: N802
    return REPO / "hls" / f"mnist_w{bits}" / "vivado" / "constrs" / "mnist_hls_ooc.xdc"


def proj_sol(bits: int, cfg_sol: str) -> tuple[Path, str, str]:
    """'par8_dsp' -> (hls/mnist_w8/par8, 'par8', 'dsp')"""
    v, d = cfg_sol.split("_")
    return REPO / "hls" / f"mnist_w{bits}" / v, v, d

# Windows'ta bazı ortamlarda cmd, bulunduğu klasördeki .bat'ları adıyla çalıştırmaz;
# Vitis HLS / Vivado kendi ürettiği scriptleri böyle çağırdığı için bu ayarı kaldır.
ENV = {k: v for k, v in os.environ.items() if k != "NoDefaultCurrentDirectoryInExePath"}


def _run(cmd: list[str], cwd: Path, log: Path) -> int:
    cwd.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace",
                       env=ENV, stdin=subprocess.DEVNULL)
    log.write_text(p.stdout + p.stderr, encoding="utf-8", errors="replace")
    return p.returncode


def hls(bits: int, sol: str, *steps: str) -> str:
    _, v, d = proj_sol(bits, sol)
    work = REPO / "build" / "hls" / f"w{bits}_{sol}"
    log = work / f"{'_'.join(steps)}.log"
    _run([str(HLS_BIN), "-f", (REPO / "scripts" / "run_hls.tcl").as_posix(), "-tclargs",
          str(bits), v, d, *steps], work, log)
    return log.read_text(encoding="utf-8", errors="replace")


def csynth_latency(bits: int, sol: str) -> dict:
    proj, _, d = proj_sol(bits, sol)
    xml = proj / d / "syn" / "report" / "csynth.xml"
    root = ET.parse(xml).getroot()
    lat = root.find(".//PerformanceEstimates/SummaryOfOverallLatency")
    est = root.find(".//PerformanceEstimates/SummaryOfTimingAnalysis/EstimatedClockPeriod")
    return {"csynth_latency": int(lat.find("Best-caseLatency").text),
            "hls_est_clock_ns": float(est.text)}


def cosim_result(bits: int, sol: str) -> dict:
    proj, _, d = proj_sol(bits, sol)
    rpt = proj / d / "sim" / "report" / "mnist_hls_cosim.rpt"
    if not rpt.exists():
        return {"cosim": "YOK", "cosim_latency_avg": None}
    text = rpt.read_text(errors="replace")
    # | VHDL | Pass | min | avg | max | ...
    m = re.search(r"\|\s*VHDL\s*\|\s*(\w+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)", text)
    if not m:
        return {"cosim": "?", "cosim_latency_avg": None}
    return {"cosim": m.group(1), "cosim_latency_avg": int(m.group(3))}


def vivado_impl(bits: int, sol: str) -> dict:
    proj, _, d = proj_sol(bits, sol)
    vhdl = proj / d / "syn" / "vhdl"
    out = RESULTS / f"w{bits}_{sol}"
    out.mkdir(parents=True, exist_ok=True)
    work = REPO / "build" / "impl_hls" / f"w{bits}_{sol}"
    rc = _run([str(VIVADO), "-mode", "batch", "-nojournal", "-log", "vivado.log", "-source",
               (REPO / "scripts" / "impl_hls.tcl").as_posix(), "-tclargs", vhdl.as_posix(),
               XDC(bits).as_posix(), out.as_posix()], work, work / "run.log")
    if rc != 0 or not (out / "power.rpt").exists():
        raise RuntimeError(f"w{bits}_{sol}: Vivado implementasyonu başarısız ({work})")
    return parse_reports(out)


def run_solution(bits: int, sol: str) -> dict:
    log = hls(bits, sol, "csynth", "cosim")
    row = {"cfg": f"w{bits}_{sol}", "W_BITS": bits, "variant": sol.split("_")[0],
           "USE_DSP": sol.endswith("dsp")}
    row.update(csynth_latency(bits, sol))
    row.update(cosim_result(bits, sol))
    if "TEST GECTI" not in log:
        row["cosim"] = "FAIL"
    if sol == EXPORT_SOL:
        dst = REPO / "hls" / f"mnist_w{bits}" / "vivado" / "rtl"
        shutil.rmtree(dst, ignore_errors=True)
        proj, _, d = proj_sol(bits, sol)
        shutil.copytree(proj / d / "syn" / "vhdl", dst)
    row.update(vivado_impl(bits, sol))
    print(row, flush=True)
    return row


def run_project(bits: int, sols: list[str]) -> list[dict]:
    # Aynı bit genişliğinin projeleri sırayla
    return [run_solution(bits, s) for s in sols]


def write_summary(rows: list[dict]) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / "summary.csv"
    existing = {}
    if path.exists():
        with open(path, newline="") as f:
            existing = {r["cfg"]: r for r in csv.DictReader(f)}
    for r in rows:
        existing[r["cfg"]] = r
    order = [f"w{b}_{s}" for b in BITS for s in SOLUTIONS]
    fields = list(rows[0])
    with open(path, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=fields)
        wr.writeheader()
        wr.writerows(existing[c] for c in order if c in existing)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--csim", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--sol", nargs=2, metavar=("BITS", "SOLUTION"))
    args = ap.parse_args()
    if args.csim:
        ok = True
        for b in BITS:
            log = hls(b, "naive_dsp", "csim")
            line = next((l for l in log.splitlines() if "SONUC:" in l), "SONUC yok")
            print(f"w{b}: {line.strip()}")
            ok &= "TEST GECTI" in log
        print("CSIM " + ("GECTI" if ok else "BASARISIZ"))
        return 0 if ok else 1
    if args.sol:
        rows = [run_solution(int(args.sol[0]), args.sol[1])]
    elif args.all:
        with ThreadPoolExecutor(max_workers=3) as ex:
            rows = [r for rs in ex.map(lambda b: run_project(b, SOLUTIONS), BITS) for r in rs]
    else:
        ap.error("--csim, --all veya --sol verin")
    write_summary(rows)
    bad = [r["cfg"] for r in rows if r["cosim"] != "Pass"]
    print("COSIM " + ("hepsi Pass" if not bad else f"BASARISIZ: {bad}"))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
