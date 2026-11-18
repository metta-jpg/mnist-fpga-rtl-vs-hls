// tb_mnist_hls.cpp: Vitis HLS C / C-RTL testbench'i.
//
// Test görüntülerini çekirdeğe verir ve tahminleri Python tamsayı altın referansının
// tahminleriyle (data/expected_pred.mem) karşılaştırır; doğruluğu etiketlerle ölçer.
// Görüntü sayısı ilk argümanla verilir (GUI'de: C Simulation / Co-Simulation ->
// "Input Arguments"):
//   argüman yok : 20 görüntü (GUI'de hızlı deneme; co-simülasyon da makul sürede biter)
//   0           : mevcut bütün görüntüler (repo kökünde data/test varsa 10.000, yoksa 100)
//   N           : ilk N görüntü
// Scriptler C simülasyonunu 0 ile, co-simülasyonu 5 ile çalıştırır.
// Uyuşmazlık varsa 1 döndürür (Vitis HLS testi başarısız sayar).
#include <cstdio>
#include <cstdlib>
#include <string>

#include "../src/mnist_hls.h"

static bool exists(const std::string& p) {
    FILE* f = std::fopen(p.c_str(), "r");
    if (f) std::fclose(f);
    return f != nullptr;
}

// Vitis HLS csim/cosim'i farklı alt klasörlerde çalıştırır: dosya görünene kadar yukarı çık.
// Bulunamazsa boş string döner.
static std::string find_up(const std::string& rel) {
    std::string pre;
    for (int up = 0; up < 10; ++up) {
        if (exists(pre + rel)) return pre;
        pre += "../";
    }
    return "";
}

static FILE* open_or_die(const std::string& p) {
    FILE* f = std::fopen(p.c_str(), "r");
    if (!f) {
        std::fprintf(stderr, "HATA: acilamadi: %s\n", p.c_str());
        std::exit(2);
    }
    return f;
}

static unsigned read_hex(FILE* f) {
    unsigned v = 0;
    if (std::fscanf(f, "%x", &v) != 1) {
        std::fprintf(stderr, "HATA: dosya beklenenden kisa\n");
        std::exit(2);
    }
    return v;
}

int main(int argc, char** argv) {
    // Proje klasörü (hls/mnist_wN): data/expected_pred.mem içerir
    const std::string proj = find_up("data/expected_pred.mem");
    if (proj.empty() && !exists("data/expected_pred.mem")) {
        std::fprintf(stderr, "HATA: data/expected_pred.mem bulunamadi\n");
        return 2;
    }
    // Tam test seti (10.000 görüntü) repo kökündeki data/test altında, isteğe bağlı
    const std::string root = find_up("data/test/images.mem");
    const bool full = !root.empty() || exists("data/test/images.mem");
    const int available = full ? 10000 : 100;
    int n_images = argc > 1 ? std::atoi(argv[1]) : 20;
    if (n_images <= 0 || n_images > available) n_images = available;
    // 100 görüntüye kadar projedeki küçük set yeterli (tam setin ilk 100 görüntüsü)
    const std::string tdir = n_images > 100 ? root + "data/test/" : proj + "data/";
    const std::string wdir = proj + "data/";
    FILE* f_img = open_or_die(tdir + "images.mem");
    FILE* f_lab = open_or_die(tdir + "labels.mem");
    FILE* f_exp = open_or_die(wdir + "expected_pred.mem");

    int mismatch = 0, correct = 0;
    for (int n = 0; n < n_images; ++n) {
        hls::stream<pix_t> pixels;
        for (int i = 0; i < 784; ++i) pixels.write(read_hex(f_img));
        ap_uint<4> pred;
        mnist_hls(pixels, pred);
        const unsigned exp = read_hex(f_exp);
        const unsigned lab = read_hex(f_lab);
        if (pred != exp) {
            if (++mismatch <= 10)
                std::printf("UYUSMAZLIK goruntu=%d beklenen=%u gelen=%u\n", n, exp, (unsigned)pred);
        }
        if (pred == lab) ++correct;
    }
    std::fclose(f_img);
    std::fclose(f_lab);
    std::fclose(f_exp);
    std::printf("SONUC: mismatch=%d correct=%d/%d\n", mismatch, correct, n_images);
    if (mismatch == 0) std::printf("TEST GECTI\n");
    return mismatch == 0 ? 0 : 1;
}
