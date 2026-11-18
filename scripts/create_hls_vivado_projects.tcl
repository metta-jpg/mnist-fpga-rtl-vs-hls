# HLS'in ürettiği RTL'i (par8 / dsp) içeren Vivado projelerini oluşturur:
#   hls/mnist_w8/vivado/mnist_hls_w8.xpr  (aynısı w4, w2 için)
# RTL dosyaları: hls/mnist_wN/vivado/rtl/ (scripts/run_hls.py HLS projesinden kopyalar).
#
# Kullanım (repo kökünden): vivado -mode batch -source scripts/create_hls_vivado_projects.tcl [-tclargs 8 4 2]

set repo [file normalize [file join [file dirname [info script]] ..]]
set bits_list {8 4 2}
if {[llength $argv] > 0} { set bits_list $argv }

foreach w $bits_list {
    set name "mnist_hls_w$w"
    set proj_dir "$repo/hls/mnist_w$w/vivado"
    create_project $name $proj_dir -part xc7a35tcpg236-1 -force
    set_property target_language VHDL [current_project]
    add_files -norecurse -fileset sources_1 [glob -directory "$proj_dir/rtl" *.vhd]
    set_property top mnist_hls [get_filesets sources_1]
    add_files -norecurse -fileset constrs_1 "$proj_dir/constrs/mnist_hls_ooc.xdc"
    set_property -name {STEPS.SYNTH_DESIGN.ARGS.MORE OPTIONS} -value {-mode out_of_context} -objects [get_runs synth_1]
    update_compile_order -fileset sources_1
    puts "PROJE HAZIR: $proj_dir/$name.xpr"
    close_project
}
