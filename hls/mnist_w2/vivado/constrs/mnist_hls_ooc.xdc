# HLS çekirdeği için out-of-context saat kısıtı: 100 MHz (HLS'in saat portu ap_clk)
create_clock -period 10.000 -name ap_clk [get_ports ap_clk]
