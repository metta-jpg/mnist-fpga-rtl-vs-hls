# RTL projesi: out-of-context sentez + implementasyon + raporlar (non-project batch akış).
# Kullanım: vivado -mode batch -source scripts/impl.tcl -tclargs \
#           PROJ_DIR W_BITS P SH1 ACC1_BITS ACC2_BITS USE_DSP OUT_DIR
# PROJ_DIR: rtl/mnist_wN (src/, constrs/, mem/ içerir). Genelde scripts/run_impl.py çağırır.

lassign $argv PROJ_DIR W_BITS P SH1 ACC1_BITS ACC2_BITS USE_DSP OUT_DIR
file mkdir $OUT_DIR

foreach f {mnist_pkg weight_rom mnist_mlp mnist_mlp_top} {
    read_vhdl -vhdl2008 [file join $PROJ_DIR src $f.vhd]
}
read_xdc -mode out_of_context [file join $PROJ_DIR constrs mnist_ooc.xdc]

set DATA_DIR [file join $PROJ_DIR mem]
synth_design -top mnist_mlp_top -part xc7a35tcpg236-1 -mode out_of_context \
    -generic W_BITS=$W_BITS -generic P=$P -generic SH1=$SH1 \
    -generic ACC1_BITS=$ACC1_BITS -generic ACC2_BITS=$ACC2_BITS \
    -generic USE_DSP=$USE_DSP -generic DATA_DIR=\"$DATA_DIR\"

opt_design
place_design
route_design

report_utilization    -file [file join $OUT_DIR utilization.rpt]
report_timing_summary -file [file join $OUT_DIR timing.rpt]
report_power          -file [file join $OUT_DIR power.rpt]
write_checkpoint -force [file join $OUT_DIR routed.dcp]
