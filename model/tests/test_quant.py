"""Quantization yardımcılarının testleri. Değerler planın 'Sabitlenen sayısal arayüz'
bölümündeki kurallardan elle hesaplandı."""
import numpy as np
import pytest

from mnist_fpga.quant import (
    acc_bits,
    best_pow2_exponent,
    pow2_exponent,
    qmax,
    quantize_weights,
    requantize,
    to_hex,
)


def test_qmax():
    assert [qmax(b) for b in (8, 4, 2)] == [127, 7, 1]


def test_pow2_exponent():
    # 0.9 * 2^7 = 115.2 <= 127 ama 0.9 * 2^8 = 230.4 > 127
    assert pow2_exponent(0.9, 127) == 7


def test_pow2_exponent_zero_rejected():
    with pytest.raises(ValueError):
        pow2_exponent(0.0, 127)


def test_best_exponent_clips_outlier_at_2bit():
    # Bir büyük (1.0) ve 99 küçük (0.3) ağırlık. En büyüğe göre ölçek (e=0) bütün
    # küçükleri 0'a yuvarlar (MSE 0.089). e=2'de büyük olan kırpılır ama küçükler
    # 0.25 olur (MSE 0.0081, adaylar içinde en düşük).
    w = np.array([1.0] + [0.3] * 99)
    assert pow2_exponent(1.0, qmax(2)) == 0
    assert best_pow2_exponent(w, 2) == 2


def test_best_exponent_never_below_max_based():
    w = np.random.default_rng(0).normal(0, 0.1, 1000)
    e_max = pow2_exponent(float(np.abs(w).max()), qmax(8))
    assert best_pow2_exponent(w, 8) >= e_max


def test_quantize_symmetric_clip():
    # e=2: -40 -> -1 (kırpma), 1.04 -> 1, 40 -> 1 (kırpma)
    assert list(quantize_weights(np.array([-10.0, 0.26, 10.0]), 2, 2)) == [-1, 1, 1]


def test_requantize_round_relu_sat():
    # sh=3, yuvarlama sabiti 4: -5 -> ReLU 0 ; 3+4=7>>3=0 ; 4+4=8>>3=1 ; büyük -> 255
    assert list(requantize(np.array([-5, 0, 3, 4, 10**6]), 3)) == [0, 0, 0, 1, 255]


def test_requantize_bad_shift():
    with pytest.raises(ValueError):
        requantize(np.array([1]), 0)


def test_to_hex_negative():
    assert to_hex(np.array([-1, 5]), 8) == ["ff", "05"]
    assert to_hex(np.array([-1]), 4) == ["f"]
    assert to_hex(np.array([-1, 1, 0]), 2) == ["3", "1", "0"]


def test_acc_bits():
    # 784 * 255 * 127 = 25_391_640 -> 25 bit büyüklük + 1 işaret biti
    assert acc_bits(784, 255, 8, 0) == 26
