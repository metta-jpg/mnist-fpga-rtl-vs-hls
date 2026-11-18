"""Tamsayı altın referans testleri (elle hesaplanmış değerler)."""
import numpy as np
import pytest

from mnist_fpga.golden import infer


def test_infer_hand_computed(tiny_model):
    x = np.zeros((1, 784), np.uint8)
    x[0, 0] = 200
    h, lg, p = infer(tiny_model, x)
    assert h[0, 0] == 200  # (400 + 1) >> 1 = 200
    assert h[0, 1] == 0  # -600 -> ReLU -> 0
    assert lg[0, 4] == 200
    assert p[0] == 4


def test_no_uint8_overflow(tiny_model):  # Review Focus 1
    tiny_model.w1[0, :] = 127
    x = np.full((1, 784), 255, np.uint8)
    h, _, _ = infer(tiny_model, x)
    # Doğru sonuç doyum (255). uint8 ile çarpılsaydı taşma küçük bir değer verirdi.
    assert h[0, 0] == 255


def test_argmax_tie_lowest(tiny_model):
    x = np.zeros((1, 784), np.uint8)
    assert infer(tiny_model, x)[2][0] == 0  # bütün logitler 0 -> indeks 0


def test_overflow_detected(tiny_model):  # Review Focus 3
    tiny_model.acc1_bits = 8  # 400 değeri 8 bit işaretliye (max 127) sığmaz
    x = np.zeros((1, 784), np.uint8)
    x[0, 0] = 200
    with pytest.raises(OverflowError):
        infer(tiny_model, x)
