"""Tamsayı modeli ve test vektörlerini donanım dallarının okuyacağı dosyalara yazar.

.mem biçimi: satır başına bir değer, ikiye tümleyen hex, ceil(bits/4) hane.
VHDL'de textio ile (hread) veya $readmemh ile okunabilir.
Ağırlık sıralaması nöron önceliklidir: w1[j][i] için önce j=0'ın 784 ağırlığı,
sonra j=1'inki ... (VHDL'de adres = j*784 + i).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .golden import QuantModel
from .quant import to_hex

BIAS_BITS = 32
N_IN, N_HID, N_OUT = 784, 32, 10


def write_mem(path: Path, values: np.ndarray, bits: int) -> None:
    Path(path).write_text("\n".join(to_hex(values, bits)) + "\n")


def read_mem(path: Path, bits: int, signed: bool = True) -> np.ndarray:
    """write_mem'in tersi. signed=True ise ikiye tümleyen olarak geri çözer."""
    v = np.array([int(s, 16) for s in Path(path).read_text().split()], dtype=np.int64)
    if signed:
        v = np.where(v >= (1 << (bits - 1)), v - (1 << bits), v)
    return v


def _c_2d(name: str, ctype: str, arr: np.ndarray) -> str:
    rows = ["{" + ",".join(str(int(v)) for v in row) + "}" for row in np.asarray(arr)]
    r, c = np.asarray(arr).shape
    return f"static const {ctype} {name}[{r}][{c}] = {{\n" + ",\n".join(rows) + "\n};\n"


def _c_1d(name: str, ctype: str, arr: np.ndarray) -> str:
    vals = ",".join(str(int(v)) for v in np.asarray(arr).ravel())
    return f"static const {ctype} {name}[{len(np.asarray(arr).ravel())}] = {{{vals}}};\n"


def write_hls_header(out_dir: Path, qm: QuantModel) -> None:
    """Vitis HLS için ağırlık başlığı (weights_hls.h). Ağırlıklar ap_int<W_BITS>
    tipinde tutulur: 2 bitte ROM gerçekten 2 bit genişliğinde olur (int8_t değil)."""
    h = (
        "/* model/train.py tarafından üretildi. Elle değiştirmeyin. */\n"
        "#ifndef MNIST_WEIGHTS_HLS_H\n#define MNIST_WEIGHTS_HLS_H\n#include <ap_int.h>\n\n"
        f"#define W_BITS {qm.bits}\n#define SH1 {qm.sh1}\n"
        f"#define ACC1_BITS {qm.acc1_bits}\n#define ACC2_BITS {qm.acc2_bits}\n\n"
        f"typedef ap_int<{qm.bits}> w_t;\n\n"
        "/* W1[nöron][giriş], W2[çıkış][gizli] */\n"
        + _c_2d("W1", "w_t", qm.w1)
        + _c_1d("B1", "ap_int<32>", qm.b1)
        + _c_2d("W2", "w_t", qm.w2)
        + _c_1d("B2", "ap_int<32>", qm.b2)
        + "\n#endif\n"
    )
    (Path(out_dir) / "weights_hls.h").write_text(h, encoding="utf-8")


def export_model(out_dir: Path, qm: QuantModel, scales: dict, metrics: dict) -> None:
    """w1/w2/b1/b2.mem ve params.json dosyalarını yazar."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    lim = 1 << (BIAS_BITS - 1)
    for b in (qm.b1, qm.b2):
        if np.abs(b).max() >= lim:
            raise OverflowError("Bias 32 bite sığmıyor")
    write_mem(out / "w1.mem", qm.w1, qm.bits)
    write_mem(out / "w2.mem", qm.w2, qm.bits)
    write_mem(out / "b1.mem", qm.b1, BIAS_BITS)
    write_mem(out / "b2.mem", qm.b2, BIAS_BITS)
    params = {
        "bits": qm.bits,
        **{k: int(v) for k, v in scales.items()},
        "sh1": qm.sh1,
        "acc1_bits": qm.acc1_bits,
        "acc2_bits": qm.acc2_bits,
        **metrics,
    }
    (out / "params.json").write_text(json.dumps(params, indent=2))


def load_model(out_dir: Path) -> QuantModel:
    """export_model'in yazdığı dosyalardan QuantModel'i yeniden kurar."""
    out = Path(out_dir)
    p = json.loads((out / "params.json").read_text())
    bits = p["bits"]
    return QuantModel(
        w1=read_mem(out / "w1.mem", bits).reshape(N_HID, N_IN),
        b1=read_mem(out / "b1.mem", BIAS_BITS),
        w2=read_mem(out / "w2.mem", bits).reshape(N_OUT, N_HID),
        b2=read_mem(out / "b2.mem", BIAS_BITS),
        sh1=p["sh1"],
        bits=bits,
        acc1_bits=p["acc1_bits"],
        acc2_bits=p["acc2_bits"],
    )


def export_expected(out_dir: Path, hidden: np.ndarray, logits: np.ndarray, pred: np.ndarray) -> None:
    """Altın referansın ara ve son çıktıları (testbench karşılaştırması için)."""
    out = Path(out_dir)
    write_mem(out / "expected_hidden.mem", hidden, 8)
    write_mem(out / "expected_logits.mem", logits, 32)
    write_mem(out / "expected_pred.mem", pred, 4)


def regenerate_expected(model_dir: Path, x_test: np.ndarray, y_test: np.ndarray) -> float:
    """Eğitim yapmadan: model dosyalarından (w*.mem, b*.mem, params.json) modeli kurar,
    altın referansla çalıştırır ve expected_*.mem dosyalarını yazar.
    Döndürür: etiketlere göre tamsayı doğruluğu."""
    from .golden import infer  # döngüsel import olmasın diye burada

    hidden, logits, pred = infer(load_model(model_dir), x_test)
    export_expected(model_dir, hidden, logits, pred)
    return float((pred == np.asarray(y_test)).mean())


def export_test_set(out_dir: Path, x_test: np.ndarray, y_test: np.ndarray) -> None:
    """Test görüntüleri (görüntü öncelikli, 784 piksel arka arkaya) ve etiketler."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_mem(out / "images.mem", x_test, 8)
    write_mem(out / "labels.mem", y_test, 4)
