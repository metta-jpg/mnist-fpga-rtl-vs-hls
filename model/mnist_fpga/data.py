"""MNIST veri setini indirir ve NumPy dizisi olarak yükler.

torchvision kullanılmaz: ham IDX dosyaları doğrudan indirilip ayrıştırılır.
IDX biçimi: büyük-endian başlık (magic + boyutlar), ardından ham baytlar.
Magic sayının son baytı boyut sayısını, üçüncü baytı veri tipini verir
(0x08 = uint8, MNIST'te sadece bu kullanılır).
"""
from __future__ import annotations

import gzip
import struct
import urllib.request
from pathlib import Path

import numpy as np

# torchvision'un da kullandığı ayna
BASE_URL = "https://ossci-datasets.s3.amazonaws.com/mnist/"
FILES = {
    "x_train": "train-images-idx3-ubyte.gz",
    "y_train": "train-labels-idx1-ubyte.gz",
    "x_test": "t10k-images-idx3-ubyte.gz",
    "y_test": "t10k-labels-idx1-ubyte.gz",
}


def parse_idx(data: bytes) -> np.ndarray:
    """IDX baytlarını uint8 NumPy dizisine çevirir."""
    if len(data) < 4:
        raise ValueError("IDX verisi çok kısa")
    magic = struct.unpack(">I", data[:4])[0]
    dtype_code = (magic >> 8) & 0xFF
    ndim = magic & 0xFF
    if magic >> 16 != 0 or dtype_code != 0x08 or ndim == 0:
        raise ValueError(f"Geçersiz IDX magic sayısı: {magic:#010x}")
    header_len = 4 + 4 * ndim
    shape = struct.unpack(">" + "I" * ndim, data[4:header_len])
    arr = np.frombuffer(data, dtype=np.uint8, offset=header_len)
    if arr.size != int(np.prod(shape)):
        raise ValueError("IDX boyutları veri uzunluğuyla uyuşmuyor")
    return arr.reshape(shape)


def _download(url: str, dest: Path) -> None:
    """Önce .part dosyasına indirir, başarılı olunca yeniden adlandırır.
    Böylece yarıda kalan indirme bozuk dosya bırakmaz."""
    part = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as resp, open(part, "wb") as f:
            f.write(resp.read())
        part.replace(dest)
    except Exception as exc:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"MNIST indirilemedi: {url} ({exc})") from exc


def load_mnist(root: Path):
    """(x_train [60000,784], y_train [60000], x_test [10000,784], y_test [10000])
    döndürür, hepsi uint8. Dosyalar yoksa root/raw/ altına indirilir."""
    raw = Path(root) / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    out = {}
    for key, name in FILES.items():
        path = raw / name
        if not path.exists():
            _download(BASE_URL + name, path)
        out[key] = parse_idx(gzip.decompress(path.read_bytes()))
    return (
        out["x_train"].reshape(-1, 784),
        out["y_train"],
        out["x_test"].reshape(-1, 784),
        out["y_test"],
    )
