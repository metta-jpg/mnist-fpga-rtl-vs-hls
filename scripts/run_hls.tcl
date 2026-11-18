# Bir HLS solution'ında adımları çalıştırır.
# Kullanım (repo kökünden):
#   vitis_hls -f scripts/run_hls.tcl -tclargs <bit> <varyant> <solution> <adım...>
#   örnek: -tclargs 8 par8 dsp csim csynth cosim
# Adımlar: csim (bütün görüntüler)  csynth  cosim (5 görüntü)
set repo [file normalize [file join [file dirname [info script]] ..]]
# vitis_hls argv'ye komut satırının tamamını koyar: ilk sayıdan (bit genişliği) itibaren al
set i [lsearch -regexp $argv {^[0-9]+$}]
lassign [lrange $argv $i end] w v sol
set steps [lrange $argv [expr {$i + 3}] end]
cd "$repo/hls/mnist_w$w"
open_project $v
open_solution $sol
foreach s $steps {
    switch $s {
        csim   { csim_design -argv "0" }
        csynth { csynth_design }
        cosim  { cosim_design -rtl vhdl -argv "5" }
    }
}
close_project
exit
