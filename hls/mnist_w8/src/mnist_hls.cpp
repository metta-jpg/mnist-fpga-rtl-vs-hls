// mnist_hls.cpp: 784 -> 32 -> 10 tamsayı MLP, Vitis HLS ile.
//
// Sayısal davranış Python altın referansıyla (model/mnist_fpga/golden.py) ve RTL tasarımıyla
// (rtl/mnist_wN/src/mnist_mlp.vhd) birebir aynıdır:
//   acc1[j]  = b1[j] + sum_i x[i] * w1[j][i]
//   h[j]     = clamp((max(acc1[j], 0) + 2^(SH1-1)) >> SH1, 0, 255)
//   logit[k] = b2[k] + sum_j h[j] * w2[k][j]
//   pred     = argmax(logit)   (eşitlikte en küçük k)
//
// Optimizasyon pragmaları VARIANT makrosuyla seçilir (her HLS projesinin derleme bayrağı):
//   VARIANT 0 = naive : hiç optimizasyon pragması yok ("pragmasız HLS")
//   VARIANT 1 = pipe  : en içteki döngüler PIPELINE II=1          (RTL P=1 karşılığı)
//   VARIANT 2 = par8  : piksel döngüsü PIPELINE + W1 8'e bölünmüş (RTL P=8 karşılığı)
// Kodun geri kalanı üç varyantta da aynı; fark sadece aşağıdaki #if blokları.
//
// Döngü yapısı: 1. katman 4 grup x 784 piksel x 8 kol. Kol döngüsü en içte olduğu için:
//   - L1_LANE boru hattına alınırsa her çevrimde 1 çarp-topla  (RTL P=1 karşılığı)
//   - L1_PIXEL boru hattına alınırsa kol döngüsü açılır, her çevrimde 8 çarp-topla (~P=8)
#include "mnist_hls.h"

#ifndef VARIANT
#define VARIANT 0
#endif
// Ağırlıklar ve sabitler (SH1, akümülatör genişlikleri): model/train.py üretir
#include "weights_hls.h"

#define N_IN 784
#define N_HID 32
#define N_OUT 10
#define LANES 8                 // 1. katmanda bir gruptaki nöron sayısı
#define GROUPS (N_HID / LANES)  // 4 grup

typedef ap_int<ACC1_BITS> acc1_t;   // 1. katman akümülatörü
typedef ap_int<ACC2_BITS> acc2_t;   // 2. katman akümülatörü
typedef ap_int<9 + W_BITS> prod_t;  // 9 bit (işaretli piksel) x W_BITS ağırlık

// Akümülatörü 8 bit gizli aktivasyona çevirir: ReLU, yarımı yukarı yuvarlama,
// sağa SH1 bit kaydırma, 0..255 doyum.
static ap_uint<8> requant(acc1_t acc) {
    if (acc < 0) return 0;
    ap_int<ACC1_BITS + 1> a = acc;
    a += ap_int<ACC1_BITS + 1>(1) << (SH1 - 1);
    a >>= SH1;
    if (a > 255) return 255;
    return a;
}

void mnist_hls(hls::stream<pix_t>& pixels, ap_uint<4>& pred) {
#pragma HLS INTERFACE mode=axis port=pixels
#pragma HLS INTERFACE mode=ap_vld port=pred
#pragma HLS INTERFACE mode=ap_ctrl_hs port=return

    pix_t x[N_IN];          // giriş görüntüsü tamponu
    ap_uint<8> h[N_HID];    // gizli aktivasyonlar
    acc1_t acc[LANES];      // bir grubun 8 akümülatörü
#if VARIANT >= 1
    // 8 akümülatör ayrı register'larda: aynı çevrimde hepsine erişilebilir
#pragma HLS ARRAY_PARTITION variable=acc type=complete dim=1
#endif
#if VARIANT == 2
    // W1 satırları 8 ayrı ROM'a: satır r -> ROM (r mod 8), 8 kol aynı anda okur
#pragma HLS ARRAY_PARTITION variable=W1 type=cyclic factor=8 dim=1
#endif

LOAD:
    for (int i = 0; i < N_IN; i++) {
#if VARIANT >= 1
#pragma HLS PIPELINE II=1
#endif
        x[i] = pixels.read();
    }

L1_GROUP:
    for (int g = 0; g < GROUPS; g++) {
    L1_INIT:
        for (int p = 0; p < LANES; p++) acc[p] = B1[g * LANES + p];
    L1_PIXEL:
        for (int i = 0; i < N_IN; i++) {
#if VARIANT == 2
#pragma HLS PIPELINE II=1
#endif
        L1_LANE:
            for (int p = 0; p < LANES; p++) {
#if VARIANT == 1
#pragma HLS PIPELINE II=1
#endif
                prod_t prod1 = ap_int<9>(x[i]) * W1[g * LANES + p][i];
                acc[p] += prod1;
            }
        }
    L1_OUT:
        for (int p = 0; p < LANES; p++) h[g * LANES + p] = requant(acc[p]);
    }

    ap_uint<4> best_k = 0;
    acc2_t best = 0;
L2_OUT:
    for (int k = 0; k < N_OUT; k++) {
        acc2_t acc2 = B2[k];
    L2_HID:
        for (int j = 0; j < N_HID; j++) {
#if VARIANT >= 1
#pragma HLS PIPELINE II=1
#endif
            prod_t prod2 = ap_int<9>(h[j]) * W2[k][j];
            acc2 += prod2;
        }
        if (k == 0 || acc2 > best) {  // kesin büyük: eşitlikte en küçük indeks kalır
            best = acc2;
            best_k = k;
        }
    }
    pred = best_k;
}
