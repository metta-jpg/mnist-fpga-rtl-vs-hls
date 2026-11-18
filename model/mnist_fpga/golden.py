"""Tamsayı altın referans: donanımın yapacağı hesabın birebir aynısı.

VHDL, HLS ve MicroBlaze uygulamalarının çıktıları bununla bit bit karşılaştırılır.
Hesap (planın 'Sabitlenen sayısal arayüz' bölümü):

    acc1[j]  = b1[j] + sum_i x[i] * w1[j][i]
    h[j]     = clamp((max(acc1[j], 0) + 2^(sh1-1)) >> sh1, 0, 255)
    logit[k] = b2[k] + sum_j h[j] * w2[k][j]
    pred     = argmax(logit)   (eşitlikte en küçük k)

Bütün ara değerler int64 ile hesaplanır. Girişler uint8 olduğu için doğrudan
çarpılsaydı NumPy sessizce taşma yapardı.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .quant import requantize


@dataclass
class QuantModel:
    w1: np.ndarray  # (32, 784) int64, değerler W bit aralığında
    b1: np.ndarray  # (32,) int64, ölçek s_x * s_w1
    w2: np.ndarray  # (10, 32) int64
    b2: np.ndarray  # (10,) int64, ölçek s_h * s_w2
    sh1: int  # gizli katman kaydırma miktarı
    bits: int  # ağırlık bit genişliği (8, 4, 2)
    acc1_bits: int  # 1. katman akümülatör genişliği (işaretli)
    acc2_bits: int  # 2. katman akümülatör genişliği (işaretli)


def _check_fits(acc: np.ndarray, bits: int, name: str) -> None:
    """Akümülatör değerlerinin 'bits' bitlik işaretli register'a sığdığını doğrular.
    Sığmazsa donanımda taşma olacağı için hata verir."""
    lo, hi = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
    if acc.min() < lo or acc.max() > hi:
        raise OverflowError(
            f"{name} {bits} bite sığmıyor: aralık [{acc.min()}, {acc.max()}]"
        )


def infer(qm: QuantModel, x: np.ndarray):
    """x: (N, 784) uint8 görüntüler.
    Döndürür: hidden (N, 32), logits (N, 10), pred (N,), hepsi int64."""
    x64 = np.asarray(x).astype(np.int64)
    acc1 = x64 @ qm.w1.T + qm.b1
    _check_fits(acc1, qm.acc1_bits, "acc1")
    hidden = requantize(acc1, qm.sh1)
    logits = hidden @ qm.w2.T + qm.b2
    _check_fits(logits, qm.acc2_bits, "acc2")
    pred = np.argmax(logits, axis=1)  # NumPy eşitlikte ilk (en küçük) indeksi verir
    return hidden, logits, pred.astype(np.int64)
