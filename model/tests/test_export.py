"""Dışa aktarma testleri: .mem biçimi, model dosyaları ve dosyadan geri yükleme."""
import json

import numpy as np

from mnist_fpga.export import (
    export_model,
    load_model,
    read_mem,
    regenerate_expected,
    write_hls_header,
    write_mem,
)
from mnist_fpga.golden import infer
from mnist_fpga.project_files import write_project_files
from mnist_fpga.quant import qmax

SCALES = {"e1": 7, "eh": 5, "e2": 6}


def test_mem_roundtrip(tmp_path):
    for bits in (8, 4, 2, 32):
        v = np.array([-qmax(bits), -1, 0, 1, qmax(bits)])
        write_mem(tmp_path / "x.mem", v, bits)
        assert (read_mem(tmp_path / "x.mem", bits) == v).all()


def test_mem_unsigned(tmp_path):
    # Tahminler (0..9) ve pikseller (0..255) işaretsiz okunmalı: 4 bitte 9 -> 9, -7 değil
    write_mem(tmp_path / "p.mem", np.array([9, 0, 15]), 4)
    assert list(read_mem(tmp_path / "p.mem", 4, signed=False)) == [9, 0, 15]


def test_export_model_files(tmp_path, tiny_model):
    export_model(tmp_path, tiny_model, SCALES, {"int_acc": 0.0})
    assert len((tmp_path / "w1.mem").read_text().split()) == 32 * 784
    p = json.loads((tmp_path / "params.json").read_text())
    assert p["sh1"] == tiny_model.sh1 and p["bits"] == 8 and p["int_acc"] == 0.0
    assert not (tmp_path / "weights.h").exists()  # C başlığı artık üretilmiyor


def test_regenerate_expected_from_files(tmp_path, tiny_model):
    # Eğitim olmadan: depodaki model dosyalarından beklenen çıktıları yeniden üret
    export_model(tmp_path, tiny_model, SCALES, {})
    rng = np.random.default_rng(1)
    x = rng.integers(0, 256, (7, 784), dtype=np.uint8)
    y = np.array([4, 0, 4, 1, 4, 0, 0])
    acc = regenerate_expected(tmp_path, x, y)
    hidden, logits, pred = infer(tiny_model, x)
    assert (read_mem(tmp_path / "expected_pred.mem", 4, signed=False) == pred).all()
    assert (read_mem(tmp_path / "expected_logits.mem", 32) == logits.ravel()).all()
    assert (read_mem(tmp_path / "expected_hidden.mem", 8, signed=False) == hidden.ravel()).all()
    assert acc == float((pred == y).mean())


def test_hls_header(tmp_path, tiny_model):
    tiny_model.bits = 2
    tiny_model.w1[0, 0] = -1
    tiny_model.b2[3] = -7
    write_hls_header(tmp_path, tiny_model)
    h = (tmp_path / "weights_hls.h").read_text()
    assert "typedef ap_int<2> w_t;" in h
    assert "#define SH1 1" in h and "#define ACC1_BITS 26" in h
    assert "static const w_t W1[32][784]" in h and "static const w_t W2[10][32]" in h
    # W1'in ilk satırının ilk değeri -1, B2[3] = -7
    w1_body = h.split("W1[32][784] = {")[1]
    assert w1_body.lstrip().startswith("{-1,")
    b2_body = h.split("B2[10] = {")[1].split("}")[0]
    assert [int(v) for v in b2_body.split(",")][3] == -7


def test_load_model_roundtrip(tmp_path, tiny_model):
    tiny_model.b1[3] = -5
    tiny_model.w2[2, 9] = -127
    export_model(tmp_path, tiny_model, SCALES, {})
    qm2 = load_model(tmp_path)
    for f in ("w1", "b1", "w2", "b2"):
        assert (getattr(qm2, f) == getattr(tiny_model, f)).all()
    assert (qm2.sh1, qm2.bits, qm2.acc1_bits) == (tiny_model.sh1, 8, 26)


def test_write_project_files(tmp_path, tiny_model):
    # Model dosyaları doğrudan proje klasörlerine yazılır (rtl/mnist_wN, hls/mnist_wN)
    rng = np.random.default_rng(2)
    x = rng.integers(0, 256, (120, 784), dtype=np.uint8)
    y = rng.integers(0, 10, 120)
    acc = write_project_files(tmp_path, tiny_model, SCALES, {"int_acc": 0.5}, x, y)
    mem = tmp_path / "rtl" / "mnist_w8" / "mem"
    hls = tmp_path / "hls" / "mnist_w8"
    for f in ("w1.mem", "w2.mem", "b1.mem", "b2.mem", "params.json",
              "expected_hidden.mem", "expected_logits.mem", "expected_pred.mem"):
        assert (mem / f).exists(), f
    # Projelerde ilk 100 test görüntüsü, tam set data/test altında
    assert len((mem / "images.mem").read_text().split()) == 100 * 784
    assert len((hls / "data" / "labels.mem").read_text().split()) == 100
    assert len((tmp_path / "data" / "test" / "labels.mem").read_text().split()) == 120
    assert (hls / "src" / "weights_hls.h").exists()
    pred = infer(tiny_model, x)[2]
    assert (read_mem(hls / "data" / "expected_pred.mem", 4, signed=False) == pred).all()
    assert acc == float((pred == y).mean())
