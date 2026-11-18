# HLS'in ürettiği VHDL'i RTL projeleriyle aynı OOC akışından geçirir.
# Kullanım: vivado -mode batch -source scripts/impl_hls.tcl -tclargs VHDL_DIR XDC OUT_DIR
lassign $argv VHDL_DIR XDC OUT_DIR
file mkdir $OUT_DIR

read_vhdl [glob -directory $VHDL_DIR *.vhd]
read_xdc -mode out_of_context $XDC
synth_design -top mnist_hls -part xc7a35tcpg236-1 -mode out_of_context
opt_design
place_design
route_design
report_utilization    -file [file join $OUT_DIR utilization.rpt]
report_timing_summary -file [file join $OUT_DIR timing.rpt]
report_power          -file [file join $OUT_DIR power.rpt]
write_checkpoint -force [file join $OUT_DIR routed.dcp]
