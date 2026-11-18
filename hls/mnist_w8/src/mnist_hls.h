// mnist_hls.h: Vitis HLS MNIST MLP hızlandırıcısının arayüzü.
#ifndef MNIST_HLS_H
#define MNIST_HLS_H

#include <ap_int.h>
#include <hls_stream.h>

typedef ap_uint<8> pix_t;  // piksel 0..255

// 784 pikseli AXI-Stream'den alır, tahmin edilen rakamı (0..9) pred'e yazar.
void mnist_hls(hls::stream<pix_t>& pixels, ap_uint<4>& pred);

#endif
