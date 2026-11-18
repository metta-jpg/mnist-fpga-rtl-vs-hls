"""Eğitilmiş tamsayı modelin dosyalarını donanım projelerinin klasörlerine yazar.

    rtl/mnist_wN/mem/   w1/w2/b1/b2.mem, params.json, expected_*.mem (10.000 görüntü),
                        images.mem + labels.mem (ilk 100 görüntü, proje simülasyonu için)
    hls/mnist_wN/src/   weights_hls.h
    hls/mnist_wN/data/  images.mem + labels.mem (ilk 100), expected_pred.mem (10.000)
    data/test/          10.000 test görüntüsü (tam regresyon için; depoda tutulmaz)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .export import (
    export_expected,
    export_model,
    export_test_set,
    write_hls_header,
    write_mem,
)
from .golden import QuantModel, infer

N_SMALL = 100  # projelerde tutulan test görüntüsü sayısı


def rtl_mem_dir(repo: Path, bits: int) -> Path:
    return Path(repo) / "rtl" / f"mnist_w{bits}" / "mem"


def hls_dir(repo: Path, bits: int) -> Path:
    return Path(repo) / "hls" / f"mnist_w{bits}"


def write_project_files(repo: Path, qm: QuantModel, scales: dict, metrics: dict,
                        x_test: np.ndarray, y_test: np.ndarray) -> float:
    """Bütün proje dosyalarını yazar. Döndürür: tamsayı modelin test doğruluğu."""
    hidden, logits, pred = infer(qm, x_test)
    acc = float((pred == np.asarray(y_test)).mean())

    mem = rtl_mem_dir(repo, qm.bits)
    export_model(mem, qm, scales, metrics)
    export_expected(mem, hidden, logits, pred)
    export_test_set(mem, x_test[:N_SMALL], y_test[:N_SMALL])

    h = hls_dir(repo, qm.bits)
    (h / "src").mkdir(parents=True, exist_ok=True)
    write_hls_header(h / "src", qm)
    export_test_set(h / "data", x_test[:N_SMALL], y_test[:N_SMALL])
    write_mem(h / "data" / "expected_pred.mem", pred, 4)

    export_test_set(Path(repo) / "data" / "test", x_test, y_test)
    return acc
