"""MNIST yükleyici testleri: IDX ayrıştırma ve gerçek veri setinin biçimi."""
import struct
from pathlib import Path

import numpy as np
import pytest

from mnist_fpga.data import load_mnist, parse_idx

REPO = Path(__file__).resolve().parents[2]


def test_parse_idx_images():
    # 2 görüntü, 2x2 piksel, magic 0x00000803 (uint8, 3 boyut)
    raw = struct.pack(">IIII", 0x803, 2, 2, 2) + bytes([0, 1, 2, 3, 4, 5, 6, 255])
    arr = parse_idx(raw)
    assert arr.shape == (2, 2, 2)
    assert arr.dtype == np.uint8
    assert arr[1, 1, 1] == 255


def test_parse_idx_bad_magic():
    with pytest.raises(ValueError):
        parse_idx(struct.pack(">II", 0x1234, 0))


@pytest.mark.slow
def test_load_mnist_shapes():
    xtr, ytr, xte, yte = load_mnist(REPO / "data")
    assert xtr.shape == (60000, 784) and xte.shape == (10000, 784)
    assert ytr.shape == (60000,) and yte.shape == (10000,)
    assert xtr.dtype == np.uint8
    assert set(np.unique(yte)) == set(range(10))
