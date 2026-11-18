"""VHDL testbench'lerini xsim ile komut satırından çalıştırır.

Kullanım (repo kökünden):
    python scripts/run_sim.py tb_requant
    python scripts/run_sim.py tb_mnist_mlp --bits 8 -g P=8 -g N_IMAGES=20
    python scripts/run_sim.py tb_mnist_mlp --bits 2 -g P=1 -g N_IMAGES=10000

--bits N projeyi seçer (rtl/mnist_wN). Ağırlık parametreleri projenin mem/params.json
dosyasından okunur. 100 görüntüye kadar projedeki küçük test seti, daha fazlası için
data/test kullanılır (model/make_test_vectors.py üretir).

Başarı ölçütü: log'da 'TEST GECTI' var, 'Failure' / 'ERROR:' yok.
Testbench'in yazdığı 'SONUC: mismatch=.. correct=../.. cycles=..' satırı ayrıştırılır.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VIVADO_BIN = Path(os.environ.get("VIVADO_BIN", "C:/Xilinx/Vivado/2023.2/bin"))
# Derleme sırası önemli: paket önce, sonra onu kullanan modüller
SRC_ORDER = ["mnist_pkg.vhd", "weight_rom.vhd", "mnist_mlp.vhd", "mnist_mlp_top.vhd"]


@dataclass
class SimResult:
    passed: bool
    mismatch: int | None
    correct: int | None
    total: int | None
    cycles: float | None
    log: str


def project_dir(bits: int) -> Path:
    return REPO / "rtl" / f"mnist_w{bits}"


def default_sources(top: str, bits: int = 8) -> list[Path]:
    proj = project_dir(bits)
    return [proj / "src" / f for f in SRC_ORDER] + [proj / "sim" / f"{top}.vhd"]


def _run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace")
    return p.returncode, p.stdout + p.stderr


def _generic_arg(name: str, value) -> str:
    """xelab argüman dosyası satırı (Windows'ta string generic'lerin tırnakları komut
    satırında bozulduğu için generic'ler argüman dosyasıyla -f verilir)."""
    if isinstance(value, bool):
        value = "true" if value else "false"
    return f'-generic_top "{name}={value}"'


def run_sim(sources: list[Path], top: str, generics: dict, work_dir: Path) -> SimResult:
    work_dir.mkdir(parents=True, exist_ok=True)
    log = ""
    rc, out = _run([str(VIVADO_BIN / "xvhdl.bat"), "--2008", *map(str, sources)], work_dir)
    log += out
    if rc == 0:
        lines = [_generic_arg(k, v) for k, v in generics.items()]
        lines.append(f"--debug off --timescale 1ns/1ps {top} -s {top}_snap")
        (work_dir / "xelab_args.txt").write_text("\n".join(lines) + "\n", encoding="ascii")
        rc, out = _run([str(VIVADO_BIN / "xelab.bat"), "-f", "xelab_args.txt"], work_dir)
        log += out
    if rc == 0:
        rc, out = _run([str(VIVADO_BIN / "xsim.bat"), f"{top}_snap", "-R"], work_dir)
        log += out
    m = re.search(r"SONUC: mismatch=(\d+) correct=(\d+)/(\d+) cycles=([\d.]+)", log)
    passed = rc == 0 and "TEST GECTI" in log and "Failure" not in log and "ERROR:" not in log
    if m:
        return SimResult(passed, int(m[1]), int(m[2]), int(m[3]), float(m[4]), log)
    return SimResult(passed, None, None, None, None, log)


def params_generics(params_path: Path) -> dict:
    """params.json -> W_BITS, SH1, ACC1_BITS, ACC2_BITS, DATA_DIR (json'un klasörü)."""
    p = json.loads(params_path.read_text())
    return {
        "W_BITS": p["bits"],
        "SH1": p["sh1"],
        "ACC1_BITS": p["acc1_bits"],
        "ACC2_BITS": p["acc2_bits"],
        "DATA_DIR": params_path.resolve().parent.as_posix(),
    }


def build_generics(bits: int, overrides: list[str], params: Path | None = None) -> dict:
    """Projenin parametreleri + komut satırı generic'leri. N_IMAGES > 100 ise tam test seti."""
    mem = project_dir(bits) / "mem"
    g: dict = params_generics(params or mem / "params.json")
    g["TEST_DIR"] = Path(g["DATA_DIR"]).as_posix()
    for item in overrides:
        k, v = item.split("=", 1)
        if k.endswith("_DIR") and not Path(v).is_absolute():
            v = (REPO / v).resolve().as_posix()
        g[k] = v
    if int(g.get("N_IMAGES", 100)) > 100 and not any(o.startswith("TEST_DIR=") for o in overrides):
        g["TEST_DIR"] = (REPO / "data" / "test").as_posix()
    return g


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("top")
    ap.add_argument("--bits", type=int, default=8, choices=(8, 4, 2))
    ap.add_argument("--params", type=Path, help="başka bir params.json (ör. test fixture'ı)")
    ap.add_argument("-g", action="append", default=[], metavar="NAME=VAL")
    ap.add_argument("--work", type=Path, help="çalışma klasörü (varsayılan build/sim/<top>)")
    args = ap.parse_args()
    if args.top == "tb_mnist_mlp":
        generics = build_generics(args.bits, args.g, args.params)
    else:
        generics = {}
        for item in args.g:
            k, v = item.split("=", 1)
            generics[k] = (REPO / v).resolve().as_posix() if k.endswith("_DIR") else v
    work = args.work or REPO / "build" / "sim" / args.top
    res = run_sim(default_sources(args.top, args.bits), args.top, generics, work)
    (work / "run.log").write_text(res.log, encoding="utf-8", errors="replace")
    for line in res.log.splitlines():
        if "SONUC:" in line or "UYUSMAZLIK" in line or "Error" in line or "Failure" in line:
            print(line.strip())
    print("GECTI" if res.passed else f"BASARISIZ (log: {work / 'run.log'})")
    return 0 if res.passed else 1


if __name__ == "__main__":
    sys.exit(main())
