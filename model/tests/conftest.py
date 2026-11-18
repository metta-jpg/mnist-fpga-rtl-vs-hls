"""Testlerde ortak kullanılan küçük, elle kurulmuş tamsayı model."""
import numpy as np
import pytest

from mnist_fpga.golden import QuantModel


@pytest.fixture
def tiny_model() -> QuantModel:
    """784->32->10 model; sadece birkaç ağırlık sıfırdan farklı:
    gizli nöron 0 = 2*x[0], gizli nöron 1 = -3*x[0];
    logit 4 = h[0], logit 7 = h[1]."""
    w1 = np.zeros((32, 784), np.int64)
    w1[0, 0] = 2
    w1[1, 0] = -3
    w2 = np.zeros((10, 32), np.int64)
    w2[4, 0] = 1
    w2[7, 1] = 1
    return QuantModel(
        w1=w1,
        b1=np.zeros(32, np.int64),
        w2=w2,
        b2=np.zeros(10, np.int64),
        sh1=1,
        bits=8,
        acc1_bits=26,
        acc2_bits=20,
    )
