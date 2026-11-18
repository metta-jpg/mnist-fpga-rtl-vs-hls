"""Ölçüm sonuçlarından enerji tablosunu ve grafikleri üretir.

Girdi : results/rtl/summary.csv, results/hls/summary.csv, results/model_accuracy.csv,
        results/fmax.csv (isteğe bağlı)
Çıktı : results/energy.csv  ve  results/figures/*.png

Görüntü başına enerji = Vivado'nun raporladığı güç x (çevrim / 100 MHz).
Güç değerleri Vivado'nun vektörsüz tahminidir; "dinamik enerji" statik güç farkını dışarıda bırakır.

Kullanım (repo kökünden):  python scripts/make_report.py
"""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
RES = REPO / "results"
FIG = RES / "figures"
CLOCK_HZ = 100e6
RTL_CYCLES = {"1": 26362, "8": 4326}  # results/rtl/sim_summary.csv

# Renkler: kategorik palet, sabit sıra (RTL = 1. renk, HLS = 2. renk); metin nötr renkte
BLUE, ORANGE = "#2a78d6", "#eb6834"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#dcdbd6"


def read(path: Path) -> list[dict]:
    return list(csv.DictReader(open(path, newline="")))


def load() -> list[dict]:
    rows = []
    for r in read(RES / "rtl" / "summary.csv"):
        cyc = RTL_CYCLES[r["P"]]
        rows.append({"cfg": r["cfg"], "kind": "RTL", "bits": int(r["W_BITS"]),
                     "variant": f"P={r['P']}", "mul": "DSP" if r["USE_DSP"] == "True" else "LUT",
                     "cycles": cyc, "lut": float(r["LUT"]), "ff": float(r["FF"]),
                     "bram": float(r["BRAM"]), "dsp": float(r["DSP"]), "wns": float(r["WNS_ns"]),
                     "p_total": float(r["total_power_W"]), "p_dyn": float(r["dynamic_power_W"])})
    for r in read(RES / "hls" / "summary.csv"):
        rows.append({"cfg": r["cfg"], "kind": "HLS", "bits": int(r["W_BITS"]),
                     "variant": r["variant"], "mul": "DSP" if r["USE_DSP"] == "True" else "LUT",
                     "cycles": int(r["cosim_latency_avg"]), "lut": float(r["LUT"]),
                     "ff": float(r["FF"]), "bram": float(r["BRAM"]), "dsp": float(r["DSP"]),
                     "wns": float(r["WNS_ns"]), "p_total": float(r["total_power_W"]),
                     "p_dyn": float(r["dynamic_power_W"])})
    fmax_path = RES / "fmax.csv"
    fmax = {r["cfg"]: float(r["fmax_mhz"]) for r in read(fmax_path)} if fmax_path.exists() else {}
    for r in rows:
        r["latency_us"] = r["cycles"] / CLOCK_HZ * 1e6
        r["e_total_uj"] = r["p_total"] * r["latency_us"]  # W x us = uJ
        r["e_dyn_uj"] = r["p_dyn"] * r["latency_us"]
        r["fmax_mhz"] = fmax.get(r["cfg"])
    return rows


def write_energy(rows: list[dict]) -> None:
    fields = ["cfg", "kind", "bits", "variant", "mul", "cycles", "latency_us", "p_total", "p_dyn",
              "e_total_uj", "e_dyn_uj", "fmax_mhz"]
    with open(RES / "energy.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(r[k], 3) if isinstance(r[k], float) else r[k]) for k in fields})


def style(ax, title: str, xlabel: str = "", ylabel: str = "") -> None:
    ax.set_title(title, loc="left", fontsize=11, color=INK)
    ax.set_xlabel(xlabel, color=MUTED, fontsize=9)
    ax.set_ylabel(ylabel, color=MUTED, fontsize=9)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def save(fig, name: str) -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG / name, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def fig_accuracy() -> None:
    acc = read(RES / "model_accuracy.csv")
    bits = [int(r["bits"]) for r in acc]
    fig, ax = plt.subplots(figsize=(5.6, 3.4))
    ax.plot(bits, [float(r["float_acc"]) * 100 for r in acc], color=MUTED, linestyle="--",
            linewidth=1.5, label="Float model")
    ax.plot(bits, [float(r["int_acc"]) * 100 for r in acc], color=BLUE, marker="o", markersize=8,
            linewidth=2, label="Tamsayı model (donanım)")
    for b, r in zip(bits, acc):
        ax.annotate(f"%{float(r['int_acc']) * 100:.2f}".replace(".", ","), (b, float(r["int_acc"]) * 100),
                    textcoords="offset points", xytext=(0, 11), ha="center", fontsize=9, color=INK)
    ax.set_xticks(bits)
    ax.set_xticklabels([f"{b} bit" for b in bits])
    ax.invert_xaxis()
    ax.set_ylim(93, 98)
    style(ax, "Test doğruluğu (10.000 MNIST görüntüsü)", ylabel="Doğruluk (%)")
    ax.legend(frameon=False, fontsize=9, labelcolor=INK, loc="lower left")
    save(fig, "dogruluk.png")


def pick(rows, kind, bits, variant, mul):
    return next(r for r in rows if r["kind"] == kind and r["bits"] == bits
                and r["variant"] == variant and r["mul"] == mul)


def grouped(ax, groups, series, ylabel, title, fmt="{:.0f}"):
    """groups: x etiketleri; series: [(ad, renk, değerler)]"""
    n = len(series)
    width = 0.8 / n
    for i, (name, color, vals) in enumerate(series):
        xs = [g + (i - (n - 1) / 2) * width for g in range(len(groups))]
        bars = ax.bar(xs, vals, width=width - 0.04, color=color, label=name)
        for x, v in zip(xs, vals):
            ax.annotate(fmt.format(v), (x, v), textcoords="offset points", xytext=(0, 3),
                        ha="center", fontsize=8, color=INK)
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels(groups)
    style(ax, title, ylabel=ylabel)


def fig_resources(rows) -> None:
    pairs = [("P=1 / pipe", "P=1", "pipe"), ("P=8 / par8", "P=8", "par8")]
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.4))
    for ax, (key, label) in zip(axes, [("lut", "LUT"), ("ff", "FF"), ("latency_us", "Gecikme (µs)")]):
        groups = [p[0] for p in pairs]
        rtl = [pick(rows, "RTL", 8, p[1], "DSP")[key] for p in pairs]
        hls = [pick(rows, "HLS", 8, p[2], "DSP")[key] for p in pairs]
        grouped(ax, groups, [("RTL (elle VHDL)", BLUE, rtl), ("HLS (Vitis HLS)", ORANGE, hls)],
                label, label, fmt="{:.0f}")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, fontsize=9, labelcolor=INK, loc="upper right",
               ncol=2, bbox_to_anchor=(1.0, 1.04))
    fig.suptitle("8 bit ağırlık, DSP'li çarpıcı. Gruplar: RTL P=1 / HLS pipe ve RTL P=8 / HLS par8",
                 x=0.01, y=1.04, ha="left", fontsize=10, color=MUTED)
    fig.tight_layout()
    save(fig, "rtl_hls_kaynak.png")


def fig_tradeoff(rows) -> None:
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    markers = {8: "o", 4: "s", 2: "^"}
    for kind, color in (("RTL", BLUE), ("HLS", ORANGE)):
        for b, m in markers.items():
            pts = [r for r in rows if r["kind"] == kind and r["bits"] == b]
            ax.scatter([r["latency_us"] for r in pts], [r["lut"] for r in pts], s=46, color=color,
                       marker=m, edgecolors="white", linewidths=0.8, label=f"{kind}, {b} bit")
    ax.set_xscale("log")
    ax.set_yscale("log")
    style(ax, "Gecikme ve LUT kullanımı (30 yapılandırma)", "Görüntü başına gecikme (µs, log)",
          "LUT (log)")
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    from matplotlib.ticker import FuncFormatter
    plain = FuncFormatter(lambda v, _: f"{v:,.0f}".replace(",", "."))
    ax.xaxis.set_major_formatter(plain)
    ax.yaxis.set_major_formatter(plain)
    from matplotlib.ticker import NullFormatter
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.set_xticks([40, 100, 300, 1000, 2000])
    ax.set_yticks([200, 500, 1000, 2000])
    for x, label in ((44, "P=8 / par8"), (264, "P=1 / pipe"), (1850, "naive (yalnız HLS)")):
        ax.annotate(label, (x, 2300), ha="center", fontsize=8, color=MUTED)
    ax.set_ylim(130, 2600)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK, ncol=2, loc="lower left")
    save(fig, "gecikme_lut.png")


def fig_energy(rows) -> None:
    bits = [8, 4, 2]
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.4))
    for ax, (var_rtl, var_hls, title) in zip(
            axes, [("P=1", "pipe", "P=1 / pipe"), ("P=8", "par8", "P=8 / par8")]):
        rtl = [pick(rows, "RTL", b, var_rtl, "DSP")["e_dyn_uj"] for b in bits]
        hls = [pick(rows, "HLS", b, var_hls, "DSP")["e_dyn_uj"] for b in bits]
        grouped(ax, [f"{b} bit" for b in bits],
                [("RTL", BLUE, rtl), ("HLS", ORANGE, hls)], "µJ / görüntü",
                f"Dinamik enerji, {title}", fmt="{:.2f}")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, fontsize=9, labelcolor=INK, loc="upper right",
               ncol=2, bbox_to_anchor=(1.0, 1.06))
    fig.tight_layout()
    save(fig, "enerji.png")


def fig_fmax(rows) -> None:
    if not all(r["fmax_mhz"] for r in rows):
        return
    bits = [8, 4, 2]
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.4))
    for ax, (var_rtl, var_hls, title) in zip(
            axes, [("P=1", "pipe", "P=1 / pipe"), ("P=8", "par8", "P=8 / par8")]):
        rtl = [pick(rows, "RTL", b, var_rtl, "DSP")["fmax_mhz"] for b in bits]
        hls = [pick(rows, "HLS", b, var_hls, "DSP")["fmax_mhz"] for b in bits]
        grouped(ax, [f"{b} bit" for b in bits], [("RTL", BLUE, rtl), ("HLS", ORANGE, hls)],
                "MHz", f"Tahmini Fmax, {title}", fmt="{:.0f}")
        ax.axhline(100, color=MUTED, linewidth=1, linestyle="--")
        ax.annotate("100 MHz hedef", (len(bits) - 0.5, 100), textcoords="offset points",
                    xytext=(-2, 4), ha="right", fontsize=8, color=MUTED)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, fontsize=9, labelcolor=INK, loc="upper right",
               ncol=2, bbox_to_anchor=(1.0, 1.06))
    fig.tight_layout()
    save(fig, "fmax.png")


def main() -> None:
    rows = load()
    write_energy(rows)
    fig_accuracy()
    fig_resources(rows)
    fig_tradeoff(rows)
    fig_energy(rows)
    fig_fmax(rows)
    print("results/energy.csv ve results/figures/ yazıldı")


if __name__ == "__main__":
    main()
