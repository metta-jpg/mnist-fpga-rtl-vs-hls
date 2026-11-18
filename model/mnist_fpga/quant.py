"""Quantization yardımcıları.

Projedeki bütün ölçekler 2'nin kuvvetidir (gerçek değer = tamsayı * 2^-e). Böylece
donanımda çarpma/bölme yerine sadece bit kaydırma gerekir. Ağırlıklar işaretli ve
simetriktir: [-qmax, +qmax] (en küçük negatif değer -2^(W-1) kullanılmaz, 2 bitte
değerler {-1, 0, 1} olur).
"""
from __future__ import annotations

import math

import numpy as np


def qmax(bits: int) -> int:
    """W bitlik simetrik işaretli tamsayının en büyük değeri: 2^(W-1) - 1."""
    return (1 << (bits - 1)) - 1


def pow2_exponent(max_abs: float, qmax: int) -> int:
    """max_abs * 2^e <= qmax koşulunu sağlayan en büyük tamsayı e.
    En büyük gerçek değer, tamsayı aralığına taşmadan sığar."""
    if max_abs <= 0:
        raise ValueError("max_abs pozitif olmalı")
    e = math.floor(math.log2(qmax / max_abs))
    # log2'deki kayan nokta hatalarına karşı sınırı kesinleştir
    while max_abs * 2.0**e > qmax:
        e -= 1
    while max_abs * 2.0 ** (e + 1) <= qmax:
        e += 1
    return e


def best_pow2_exponent(w: np.ndarray, bits: int, extra: int = 4) -> int:
    """Quantization hatasını (MSE) en aza indiren 2'nin kuvveti ölçek üssü.

    pow2_exponent en büyük ağırlığı kırpmadan sığdırır. Düşük bitlerde bu kötüdür:
    2 bitte (değerler -1, 0, 1) en büyüğün yarısından küçük her ağırlık 0 olur.
    Burada en büyüğe göre bulunan üs ve ondan 'extra' fazlası denenir; birkaç
    büyük ağırlığın kırpılması pahasına geri kalanları koruyan üs seçilir.
    """
    w = np.asarray(w, dtype=np.float64)
    e0 = pow2_exponent(float(np.abs(w).max()), qmax(bits))
    best_e, best_err = e0, np.inf
    for e in range(e0, e0 + extra + 1):
        err = np.mean((w - quantize_weights(w, bits, e) / 2.0**e) ** 2)
        if err < best_err:
            best_e, best_err = e, err
    return best_e


def quantize_weights(w: np.ndarray, bits: int, e: int) -> np.ndarray:
    """Gerçek ağırlıkları W bit tamsayıya çevirir: clip(round(w * 2^e), -qmax, qmax).
    Yuvarlama yarımı yukarı (floor(x + 0.5)), donanımdaki kuralla aynı."""
    q = qmax(bits)
    return np.clip(np.floor(np.asarray(w) * 2.0**e + 0.5), -q, q).astype(np.int64)


def requantize(acc: np.ndarray, sh: int) -> np.ndarray:
    """Akümülatörü 8 bit gizli aktivasyona çevirir:
    ReLU -> (+ 2^(sh-1), yuvarlama) -> sağa sh bit kaydır -> 0..255'e kırp."""
    if sh < 1:
        raise ValueError(f"Kaydırma miktarı en az 1 olmalı (sh={sh})")
    a = np.maximum(np.asarray(acc, dtype=np.int64), 0)
    return np.clip((a + (1 << (sh - 1))) >> sh, 0, 255)


def to_hex(values: np.ndarray, bits: int) -> list[str]:
    """Tamsayıları ikiye tümleyen hex metne çevirir (ceil(bits/4) hane, küçük harf).
    Örnek: 8 bitte -1 -> 'ff', 2 bitte -1 -> '3'."""
    mask = (1 << bits) - 1
    width = (bits + 3) // 4
    return [format(int(v) & mask, f"0{width}x") for v in np.asarray(values).ravel()]


def acc_bits(n_inputs: int, in_max: int, w_bits: int, bias_max_abs: int) -> int:
    """En kötü durumda akümülatörün taşmaması için gereken işaretli bit sayısı.
    |acc| <= n_inputs * in_max * qmax + |bias|; büyüklük bitleri + 1 işaret biti."""
    worst = n_inputs * in_max * qmax(w_bits) + abs(int(bias_max_abs))
    return worst.bit_length() + 1
