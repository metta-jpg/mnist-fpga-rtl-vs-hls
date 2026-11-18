# RTL Vivado projelerini oluşturur: rtl/mnist_w8/mnist_w8.xpr, rtl/mnist_w4/..., rtl/mnist_w2/...
# .xpr dosyaları depoda hazırdır; bu script sadece onları sıfırdan üretmek için.
# Mevcut src/, sim/, constrs/, mem/ klasörlerine dokunmaz.
#
# Kullanım (repo kökünden): vivado -mode batch -source scripts/create_rtl_projects.tcl [-tclargs 8 4 2]
#
# Ağırlık klasörü (mem/) generic olarak göreli verilir. Vivado sentezi <proje>.runs/synth_1,
# simülasyonu <proje>.sim/sim_1/behav/xsim içinde çalıştırdığı için iki yol farklıdır.

set repo [file normalize [file join [file dirname [info script]] ..]]
set P 8
set bits_list {8 4 2}
if {[llength $argv] > 0} { set bits_list $argv }

proc read_params {path} {
    set fh [open $path r]
    set json [read $fh]
    close $fh
    foreach key {sh1 acc1_bits acc2_bits} {
        regexp "\"$key\": (\\d+)" $json -> val
        dict set res $key $val
    }
    return $res
}

foreach W_BITS $bits_list {
    set name "mnist_w$W_BITS"
    set proj_dir "$repo/rtl/$name"
    set pr [read_params "$proj_dir/mem/params.json"]
    create_project $name $proj_dir -part xc7a35tcpg236-1 -force
    set_property target_language VHDL [current_project]
    set_property simulator_language VHDL [current_project]

    set src {}
    foreach f {mnist_pkg weight_rom mnist_mlp mnist_mlp_top} { lappend src "$proj_dir/src/$f.vhd" }
    add_files -norecurse -fileset sources_1 $src
    set_property file_type {VHDL 2008} [get_files -of_objects [get_filesets sources_1]]
    set_property top mnist_mlp_top [get_filesets sources_1]
    set nums "W_BITS=$W_BITS P=$P SH1=[dict get $pr sh1] ACC1_BITS=[dict get $pr acc1_bits] ACC2_BITS=[dict get $pr acc2_bits]"
    set_property generic "$nums USE_DSP=true DATA_DIR=\"../../mem\"" [get_filesets sources_1]

    # 100 MHz saat; tasarım pinlere bağlanmadığı için sentez out-of-context
    add_files -norecurse -fileset constrs_1 "$proj_dir/constrs/mnist_ooc.xdc"
    set_property -name {STEPS.SYNTH_DESIGN.ARGS.MORE OPTIONS} -value {-mode out_of_context} -objects [get_runs synth_1]

    set tbs {}
    foreach f {tb_mnist_mlp tb_requant tb_weight_rom} { lappend tbs "$proj_dir/sim/$f.vhd" }
    add_files -norecurse -fileset sim_1 $tbs
    set_property file_type {VHDL 2008} [get_files -of_objects [get_filesets sim_1] *.vhd]
    set_property top tb_mnist_mlp [get_filesets sim_1]
    set_property top_lib xil_defaultlib [get_filesets sim_1]
    set_property generic "$nums USE_DSP=true DATA_DIR=\"../../../../mem\" TEST_DIR=\"../../../../mem\" N_IMAGES=20" [get_filesets sim_1]
    set_property -name {xsim.simulate.runtime} -value {all} -objects [get_filesets sim_1]
    set_property -name {xsim.elaborate.debug_level} -value {typical} -objects [get_filesets sim_1]

    update_compile_order -fileset sources_1
    update_compile_order -fileset sim_1
    puts "PROJE HAZIR: $proj_dir/$name.xpr"
    close_project
}
