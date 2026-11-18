# Vitis HLS projelerini oluşturur: her bit genişliği için üç proje (varyant), her projede
# iki solution (dsp, lut):
#   hls/mnist_w8/naive   hls/mnist_w8/pipe   hls/mnist_w8/par8   (aynısı w4, w2 için)
# Projeler depoda hazırdır; bu script sadece onları sıfırdan üretmek için.
#
# Kullanım (repo kökünden):  vitis_hls -f scripts/create_hls_projects.tcl [-tclargs 8 4 2]
#
# Varyantlar (src/mnist_hls.cpp içindeki VARIANT makrosu):
#   naive : hiç optimizasyon pragması yok
#   pipe  : en içteki döngüler PIPELINE II=1
#   par8  : piksel döngüsü PIPELINE + W1 8'e bölünmüş (8 paralel çarp-topla)
# Solution'lar: dsp / lut -> çarpıcılar DSP48'de mi LUT'ta mı (config_op mul -impl)

set repo [file normalize [file join [file dirname [info script]] ..]]
set bits_list {8 4 2}
# vitis_hls argv'ye komut satırının tamamını koyar (-f dosya dahil): sadece sayıları al
if {[info exists argv]} {
    set given [lsearch -all -inline -regexp $argv {^[0-9]+$}]
    if {[llength $given] > 0} { set bits_list $given }
}

foreach w $bits_list {
    cd "$repo/hls/mnist_w$w"
    foreach {v vnum} {naive 0 pipe 1 par8 2} {
        open_project -reset $v
        set_top mnist_hls
        add_files src/mnist_hls.cpp -cflags "-DVARIANT=$vnum"
        add_files src/mnist_hls.h
        add_files src/weights_hls.h
        add_files -tb tb/tb_mnist_hls.cpp
        foreach {sol impl} {dsp dsp lut fabric} {
            open_solution -reset $sol -flow_target vivado
            set_part xc7a35tcpg236-1
            create_clock -period 10 -name default
            # Otomatik boru hattı kapalı: sadece koddaki pragmalar etkili olsun
            config_compile -pipeline_loops 0
            config_op mul -impl $impl
            config_rtl -reset all
        }
        close_project
        puts "HLS PROJE HAZIR: hls/mnist_w$w/$v"
    }
}
exit
