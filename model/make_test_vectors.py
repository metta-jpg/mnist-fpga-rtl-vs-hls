"""Proje dosyalarını depodaki ağırlıklardan yeniden üretir (eğitim yok, PyTorch gerekmez).

rtl/mnist_wN/mem/*.mem dosyalarındaki tamsayı modeli okur, tamsayı referansla çalıştırır ve
beklenen çıktıları, test görüntülerini ve HLS ağırlık başlığını yeniden yazar. Ayrıca tam
regresyon için 10.000 görüntülük data/test klasörünü üretir (MNIST gerekirse indirilir, ~11 MB).

Kullanım (repo kökünden):  python model/make_test_vectors.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mnist_fpga.data import load_mnist  # noqa: E402
from mnist_fpga.export import load_model  # noqa: E402
from mnist_fpga.project_files import rtl_mem_dir, write_project_files  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    _, _, xte, yte = load_mnist(REPO / "data")
    ok = True
    for bits in (8, 4, 2):
        mem = rtl_mem_dir(REPO, bits)
        params = json.loads((mem / "params.json").read_text())
        scales = {k: params[k] for k in ("e1", "eh", "e2")}
        metrics = {k: params[k] for k in ("float_acc", "qat_acc", "int_acc")}
        acc = write_project_files(REPO, load_model(mem), scales, metrics, xte, yte)
        same = abs(acc - params["int_acc"]) < 1e-9
        ok &= same
        print(f"w{bits}: tamsayı doğruluk {acc:.4f} (params.json: {params['int_acc']:.4f}) "
              + ("tamam" if same else "UYUSMUYOR"))
    print("Proje dosyaları ve data/test hazır." if ok else "HATA")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
