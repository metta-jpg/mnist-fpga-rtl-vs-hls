"""784 -> 32 -> 10 MLP: float eğitim, QAT (quantization'a duyarlı eğitim) ve
tamsayı modele dönüştürme.

QAT modunda ileri geçiş, tamsayı altın referansın (golden.py) yaptığı hesabı
float sayılarla taklit eder ("sahte quantization"):
  - ağırlıklar W bit tamsayıya yuvarlanıp kırpılır, sonra ölçekle geri çarpılır
  - bias'lar akümülatör ölçeğine yuvarlanır
  - gizli aktivasyon 0..255 tamsayıya yuvarlanıp kırpılır
Yuvarlama türevlenemediği için geri yayılımda STE (straight-through estimator)
kullanılır: ileri geçişte yuvarlanmış değer, geri geçişte yuvarlanmamış değerin
türevi kullanılır.

Bütün ölçekler 2'nin kuvveti: s_x = 2^-8, s_w1 = 2^-e1, s_h = 2^-eh, s_w2 = 2^-e2.
Böylece floor(acc1 * 2^eh + 0.5) ile (acc1_int + 2^(sh1-1)) >> sh1 tam olarak aynı
sonucu verir (sh1 = 8 + e1 - eh).
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from .golden import QuantModel
from .quant import acc_bits, best_pow2_exponent, pow2_exponent, qmax, quantize_weights

IN_BITS = 8  # giriş ölçeği 2^-8 (piksel / 256)


def _ste(x: torch.Tensor, q: torch.Tensor) -> torch.Tensor:
    """İleri geçişte q, geri geçişte x'in türevi."""
    return x + (q - x).detach()


def _round_half_up(x: torch.Tensor) -> torch.Tensor:
    return torch.floor(x + 0.5)


def _weight_exp(w: torch.Tensor, bits: int) -> int:
    """Ağırlık ölçeği: quantization hatasını en aza indiren 2'nin kuvveti."""
    return best_pow2_exponent(w.detach().numpy(), bits)


def _fake_quant_weight(w: torch.Tensor, bits: int, e: int) -> torch.Tensor:
    q = qmax(bits)
    return _ste(w, torch.clamp(_round_half_up(w * 2.0**e), -q, q) / 2.0**e)


def _fake_quant_bias(b: torch.Tensor, e: int) -> torch.Tensor:
    return _ste(b, _round_half_up(b * 2.0**e) / 2.0**e)


class MLP(nn.Module):
    def __init__(self, bits: int | None = None):
        """bits=None: float model. bits=8/4/2: QAT modeli."""
        super().__init__()
        self.bits = bits
        self.fc1 = nn.Linear(784, 32)
        self.fc2 = nn.Linear(32, 10)
        # Gizli aktivasyon ölçeğinin üssü; calibrate() ile belirlenir (eval modunda kullanılır)
        self.register_buffer("eh", torch.tensor(0, dtype=torch.int64))

    def _hidden_exp(self, act_max: float, e1: int) -> int:
        """eh: en büyük aktivasyon 255'e sığacak şekilde; sh1 >= 1 olacak şekilde sınırlı."""
        eh = pow2_exponent(max(act_max, 1e-12), 255)
        return min(eh, IN_BITS + e1 - 1)

    def _layer1(self, x: torch.Tensor):
        """Döndürür: (ReLU'dan önceki akümülatör (gerçek değer), e1)."""
        x = x / 2.0**IN_BITS
        if self.bits is None:
            return self.fc1(x), None
        e1 = _weight_exp(self.fc1.weight, self.bits)
        w1 = _fake_quant_weight(self.fc1.weight, self.bits, e1)
        b1 = _fake_quant_bias(self.fc1.bias, IN_BITS + e1)
        return F.linear(x, w1, b1), e1

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """x: (N, 784) float tensör, değerler 0..255 (ham piksel)."""
        acc1, e1 = self._layer1(x)
        h = F.relu(acc1)
        if self.bits is None:
            return self.fc2(h)
        if self.training:
            eh = self._hidden_exp(float(h.detach().max()), e1)
        else:
            eh = int(self.eh)
        h = _ste(h, torch.clamp(_round_half_up(h * 2.0**eh), 0, 255) / 2.0**eh)
        e2 = _weight_exp(self.fc2.weight, self.bits)
        w2 = _fake_quant_weight(self.fc2.weight, self.bits, e2)
        b2 = _fake_quant_bias(self.fc2.bias, eh + e2)
        return F.linear(h, w2, b2)

    @torch.no_grad()
    def calibrate(self, x: np.ndarray) -> None:
        """Kalibrasyon verisindeki en büyük gizli aktivasyona göre eh'yi sabitler."""
        acc1, e1 = self._layer1(torch.tensor(x, dtype=torch.float32))
        self.eh.fill_(self._hidden_exp(float(F.relu(acc1).max()), e1))


def train_model(model: MLP, xtr: np.ndarray, ytr: np.ndarray, epochs: int, lr: float) -> MLP:
    """Adam, batch 128, çapraz entropi. Sonunda model eval modunda ve kalibre edilmiş döner."""
    x = torch.tensor(xtr, dtype=torch.float32)
    y = torch.tensor(np.asarray(ytr), dtype=torch.int64)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    model.train()
    for _ in range(epochs):
        perm = torch.randperm(len(x))
        for i in range(0, len(x), 128):
            idx = perm[i : i + 128]
            opt.zero_grad()
            F.cross_entropy(model(x[idx]), y[idx]).backward()
            opt.step()
    model.eval()
    if model.bits is not None:
        model.calibrate(xtr[:10000])
    return model


@torch.no_grad()
def evaluate(model: MLP, x: np.ndarray, y: np.ndarray) -> float:
    model.eval()
    pred = model(torch.tensor(x, dtype=torch.float32)).argmax(1).numpy()
    return float((pred == np.asarray(y)).mean())


@torch.no_grad()
def to_quant_model(model: MLP, bits: int, x_calib: np.ndarray) -> tuple[QuantModel, dict]:
    """QAT modelini tamsayı QuantModel'e çevirir. Ölçekler modelin ileri geçişiyle
    aynı şekilde hesaplanır, böylece iki model aynı sonucu verir."""
    if model.bits != bits:
        raise ValueError(f"Model {model.bits} bit için eğitilmiş, {bits} istendi")
    model.eval()
    model.calibrate(x_calib)
    w1f, b1f = model.fc1.weight.numpy(), model.fc1.bias.numpy()
    w2f, b2f = model.fc2.weight.numpy(), model.fc2.bias.numpy()
    e1 = _weight_exp(model.fc1.weight, bits)
    e2 = _weight_exp(model.fc2.weight, bits)
    eh = int(model.eh)
    w1 = quantize_weights(w1f, bits, e1)
    w2 = quantize_weights(w2f, bits, e2)
    # float32 ile aynı yuvarlamayı yapmak için torch üzerinden hesaplanır
    b1 = _round_half_up(model.fc1.bias * 2.0 ** (IN_BITS + e1)).numpy().astype(np.int64)
    b2 = _round_half_up(model.fc2.bias * 2.0 ** (eh + e2)).numpy().astype(np.int64)
    qm = QuantModel(
        w1=w1,
        b1=b1,
        w2=w2,
        b2=b2,
        sh1=IN_BITS + e1 - eh,
        bits=bits,
        acc1_bits=acc_bits(784, 255, bits, int(np.abs(b1).max())),
        acc2_bits=acc_bits(32, 255, bits, int(np.abs(b2).max())),
    )
    return qm, {"e1": e1, "eh": eh, "e2": e2}
