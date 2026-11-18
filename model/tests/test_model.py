"""PyTorch QAT modelinin tamsayı altın referansla aynı sonucu verdiğini doğrular."""
import numpy as np
import torch

from mnist_fpga.golden import infer
from mnist_fpga.model import MLP, to_quant_model, train_model


def test_qat_matches_golden():
    torch.manual_seed(0)
    rng = np.random.default_rng(0)
    xtr = rng.integers(0, 256, (512, 784), dtype=np.uint8)
    ytr = rng.integers(0, 10, 512)
    m = train_model(MLP(bits=8), xtr, ytr, epochs=1, lr=1e-3)
    qm, scales = to_quant_model(m, 8, xtr)
    assert qm.sh1 >= 1 and set(scales) == {"e1", "eh", "e2"}
    _, _, pred = infer(qm, xtr)
    with torch.no_grad():
        torch_pred = m(torch.tensor(xtr, dtype=torch.float32)).argmax(1).numpy()
    assert (pred == torch_pred).mean() >= 0.995
