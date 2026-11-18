-- mnist_mlp_top: sentez sarmalayıcısı.
-- Çekirdeği hata ayıklama portları olmadan dışarı açar. Bağlanmayan hata ayıklama
-- çıkışlarını süren mantık sentezde otomatik olarak silinir, böylece kaynak raporları
-- sadece gerçek hızlandırıcıyı ölçer.
library ieee;
use ieee.std_logic_1164.all;

entity mnist_mlp_top is
  generic (
    W_BITS    : positive := 8;
    P         : positive := 1;
    SH1       : positive := 12;
    ACC1_BITS : positive := 26;
    ACC2_BITS : positive := 21;
    DATA_DIR  : string   := "mem";
    USE_DSP   : boolean  := true
  );
  port (
    clk, rst      : in  std_logic;
    s_axis_tdata  : in  std_logic_vector(7 downto 0);
    s_axis_tvalid : in  std_logic;
    s_axis_tready : out std_logic;
    s_axis_tlast  : in  std_logic;
    pred_o        : out std_logic_vector(3 downto 0);
    pred_valid_o  : out std_logic
  );
end entity;

architecture rtl of mnist_mlp_top is
begin
  core : entity work.mnist_mlp
    generic map (W_BITS => W_BITS, P => P, SH1 => SH1, ACC1_BITS => ACC1_BITS,
                 ACC2_BITS => ACC2_BITS, DATA_DIR => DATA_DIR, USE_DSP => USE_DSP)
    port map (clk => clk, rst => rst,
              s_axis_tdata => s_axis_tdata, s_axis_tvalid => s_axis_tvalid,
              s_axis_tready => s_axis_tready, s_axis_tlast => s_axis_tlast,
              pred_o => pred_o, pred_valid_o => pred_valid_o,
              hid_valid_o => open, hid_idx_o => open, hid_o => open,
              logit_valid_o => open, logit_idx_o => open, logit_o => open);
end architecture;
