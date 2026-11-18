"""MNIST MLP (784-32-10) eğitimi, quantization ve donanım projelerine dışa aktarma.

Akış: float eğitim -> her bit genişliği için QAT -> tamsayı model -> proje dosyaları
(rtl/mnist_wN/mem, hls/mnist_wN/src, hls/mnist_wN/data) -> dosyalardan geri yükleyerek kontrol.

Kullanım (repo kökünden):
    python model/train.py --bits 8 4 2 --epochs 10 --qat-epochs 5
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mnist_fpga.data import load_mnist  # noqa: E402
from mnist_fpga.export import load_model  # noqa: E402
from mnist_fpga.golden import infer  # noqa: E402
from mnist_fpga.model import MLP, evaluate, to_quant_model, train_model  # noqa: E402
from mnist_fpga.project_files import rtl_mem_dir, write_project_files  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--bits", type=int, nargs="+", default=[8, 4, 2])
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--qat-epochs", type=int, default=5)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--qat-lr", type=float, default=5e-4)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    data = REPO / "data"
    xtr, ytr, xte, yte = load_mnist(data)

    print(f"Float eğitim ({args.epochs} epoch)...")
    fmodel = train_model(MLP(None), xtr, ytr, args.epochs, args.lr)
    float_acc = evaluate(fmodel, xte, yte)
    print(f"  float doğruluk: {float_acc:.4f}")
    torch.save(fmodel.state_dict(), data / "float.pt")

    rows = []
    for bits in args.bits:
        print(f"\n{bits} bit QAT ({args.qat_epochs} epoch)...")
        q = MLP(bits)
        q.load_state_dict(fmodel.state_dict())  # float modelden başla
        q = train_model(q, xtr, ytr, args.qat_epochs, args.qat_lr)
        qm, scales = to_quant_model(q, bits, xtr[:10000])
        qat_acc = evaluate(q, xte, yte)
        pred = infer(qm, xte)[2]
        int_acc = float((pred == yte).mean())
        metrics = {"float_acc": float_acc, "qat_acc": qat_acc, "int_acc": int_acc}
        write_project_files(REPO, qm, scales, metrics, xte, yte)

        # Dosya kontrolü: modeli yazılan dosyalardan yeniden kur, tahminler aynı olmalı
        same = int((infer(load_model(rtl_mem_dir(REPO, bits)), xte)[2] == pred).sum())
        if same != len(pred):
            sys.exit(f"HATA: {bits} bit dosya kontrolü başarısız ({same}/{len(pred)})")
        print(f"  qat {qat_acc:.4f} | tamsayı {int_acc:.4f} | sh1={qm.sh1} "
              f"acc1={qm.acc1_bits} acc2={qm.acc2_bits} bit | dosya kontrolü {same}/{len(pred)}")
        rows.append({"bits": bits, **metrics})

    (REPO / "results").mkdir(exist_ok=True)
    with open(REPO / "results" / "model_accuracy.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["bits", "float_acc", "qat_acc", "int_acc"])
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
