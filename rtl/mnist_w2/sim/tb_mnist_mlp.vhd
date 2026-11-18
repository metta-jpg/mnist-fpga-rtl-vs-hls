-- tb_mnist_mlp: MLP çekirdeğinin uçtan uca testbench'i.
--
-- Test görüntülerini (TEST_DIR/images.mem) AXI-Stream ile çekirdeğe akıtır ve her
-- görüntü için çekirdeğin ürettiği
--   * 32 gizli aktivasyonu  (DATA_DIR/expected_hidden.mem)
--   * 10 logiti             (DATA_DIR/expected_logits.mem)
--   * tahmini               (DATA_DIR/expected_pred.mem)
-- Python altın referansının değerleriyle bit bit karşılaştırır. Doğruluk etiketlerle
-- (TEST_DIR/labels.mem) ölçülür.
--
-- Senaryolar: GAPS (tvalid'de rastgele boşluklar), RESET_TEST (2. görüntünün ortasında
-- reset; o görüntü atlanır, sonrakiler doğru olmalı).
-- Sonunda: "SONUC: mismatch=<n> correct=<c>/<N> cycles=<ortalama>" ve "TEST GECTI".
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use ieee.math_real.all;
use std.textio.all;
use work.mnist_pkg.all;

entity tb_mnist_mlp is
  generic (
    W_BITS     : positive := 8;
    P          : positive := 1;
    SH1        : positive := 12;
    ACC1_BITS  : positive := 26;
    ACC2_BITS  : positive := 21;
    DATA_DIR   : string   := "mem";
    TEST_DIR   : string   := "mem";
    N_IMAGES   : positive := 100;
    GAPS       : boolean  := false;
    RESET_TEST : boolean  := false;
    USE_DSP    : boolean  := true
  );
end entity;

architecture sim of tb_mnist_mlp is
  constant CLK_PERIOD : time := 10 ns;
  -- Görüntü başına izin verilen en fazla çevrim (planın "Gecikme sınırı")
  constant MAX_CYCLES : natural := 784 + (784 + 4) * (N_HID / P) + N_OUT * (N_HID + 4) + 64;
  constant SKIP_IMG   : integer := 1;  -- RESET_TEST'te yarıda kesilen görüntü

  signal clk, rst      : std_logic := '0';
  signal tdata         : std_logic_vector(7 downto 0) := (others => '0');
  signal tvalid, tlast : std_logic := '0';
  signal tready        : std_logic;
  signal pred          : std_logic_vector(3 downto 0);
  signal pred_valid    : std_logic;
  signal hid_valid     : std_logic;
  signal hid_idx       : std_logic_vector(4 downto 0);
  signal hid           : std_logic_vector(7 downto 0);
  signal logit_valid   : std_logic;
  signal logit_idx     : std_logic_vector(3 downto 0);
  signal logit         : std_logic_vector(ACC2_BITS - 1 downto 0);
  signal cycle         : natural := 0;
  signal finished      : boolean := false;

  -- 8 veya 32 bitlik hex satırı okur
  procedure read_hex(file f : text; v : out std_logic_vector) is
    variable l : line;
  begin
    readline(f, l);
    hread(l, v);
  end procedure;
begin
  clk <= not clk after CLK_PERIOD / 2 when not finished;

  process (clk)
  begin
    if rising_edge(clk) then
      cycle <= cycle + 1;
    end if;
  end process;

  dut : entity work.mnist_mlp
    generic map (W_BITS => W_BITS, P => P, SH1 => SH1, ACC1_BITS => ACC1_BITS,
                 ACC2_BITS => ACC2_BITS, DATA_DIR => DATA_DIR, USE_DSP => USE_DSP)
    port map (clk => clk, rst => rst,
              s_axis_tdata => tdata, s_axis_tvalid => tvalid, s_axis_tready => tready,
              s_axis_tlast => tlast,
              pred_o => pred, pred_valid_o => pred_valid,
              hid_valid_o => hid_valid, hid_idx_o => hid_idx, hid_o => hid,
              logit_valid_o => logit_valid, logit_idx_o => logit_idx, logit_o => logit);

  -- Uyarıcı: görüntüleri piksel piksel AXI-Stream ile gönderir
  stim : process
    file f_img        : text open read_mode is TEST_DIR & "/images.mem";
    variable px       : std_logic_vector(7 downto 0);
    variable s1, s2   : positive := 42;
    variable rnd      : real;
  begin
    rst <= '1';
    wait for 3 * CLK_PERIOD;
    wait until rising_edge(clk);
    rst <= '0';
    for img in 0 to N_IMAGES - 1 loop
      for i in 0 to N_IN - 1 loop
        read_hex(f_img, px);
        if GAPS then
          uniform(s1, s2, rnd);
          if rnd < 0.3 then
            tvalid <= '0';
            wait until rising_edge(clk);
          end if;
        end if;
        if RESET_TEST and img = SKIP_IMG and i = 400 then
          -- Görüntünün ortasında reset: kalan pikseller okunup atılır
          tvalid <= '0';
          rst <= '1';
          wait until rising_edge(clk);
          wait until rising_edge(clk);
          rst <= '0';
          for k in i + 1 to N_IN - 1 loop
            read_hex(f_img, px);
          end loop;
          exit;
        end if;
        tdata  <= px;
        tvalid <= '1';
        tlast  <= '1' when i = N_IN - 1 else '0';
        loop
          wait until rising_edge(clk);
          exit when tready = '1';
        end loop;
      end loop;
      tvalid <= '0';
      tlast  <= '0';
    end loop;
    wait;
  end process;

  -- Denetleyici: çekirdeğin çıktılarını beklenen değerlerle karşılaştırır
  check : process
    file f_hid, f_log, f_pred : text;
    file f_lab                : text;
    type hid_arr_t is array (0 to N_HID - 1) of integer;
    type log_arr_t is array (0 to N_OUT - 1) of integer;
    variable exp_hid          : hid_arr_t;
    variable exp_log          : log_arr_t;
    variable exp_pred, exp_label  : integer;
    variable v8               : std_logic_vector(7 downto 0);
    variable v32              : std_logic_vector(31 downto 0);
    variable v4               : std_logic_vector(3 downto 0);
    variable img, done_cnt    : integer := 0;
    variable mismatch, correct, cnt_hid, cnt_log : integer := 0;
    variable start_cyc        : natural := 0;
    variable beats            : natural := 0;
    variable cyc_sum          : real := 0.0;
    variable n_expected       : integer;
    variable l                : line;

    -- Sıradaki görüntünün beklenen değerlerini dosyalardan okur
    procedure load_expected is
    begin
      for j in 0 to N_HID - 1 loop
        read_hex(f_hid, v8);
        exp_hid(j) := to_integer(unsigned(v8));
      end loop;
      for k in 0 to N_OUT - 1 loop
        read_hex(f_log, v32);
        exp_log(k) := to_integer(signed(v32));
      end loop;
      read_hex(f_pred, v4);
      exp_pred := to_integer(unsigned(v4));
      read_hex(f_lab, v4);
      exp_label := to_integer(unsigned(v4));
    end procedure;

    procedure report_mismatch(what : string; idx, exp, got : integer) is
    begin
      mismatch := mismatch + 1;
      if mismatch <= 10 then
        report "UYUSMAZLIK goruntu=" & integer'image(img) & " " & what & "["
               & integer'image(idx) & "] beklenen=" & integer'image(exp)
               & " gelen=" & integer'image(got) severity error;
      end if;
    end procedure;
  begin
    file_open(f_hid, DATA_DIR & "/expected_hidden.mem", read_mode);
    file_open(f_log, DATA_DIR & "/expected_logits.mem", read_mode);
    file_open(f_pred, DATA_DIR & "/expected_pred.mem", read_mode);
    file_open(f_lab, TEST_DIR & "/labels.mem", read_mode);
    n_expected := N_IMAGES - 1 when RESET_TEST else N_IMAGES;
    load_expected;

    while done_cnt < n_expected loop
      wait until rising_edge(clk);
      if cycle > (N_IMAGES + 2) * MAX_CYCLES * 2 then
        report "ZAMAN ASIMI" severity failure;
      end if;
      if rst = '1' then
        beats := 0;
        cnt_hid := 0;
        cnt_log := 0;
        if RESET_TEST and img = SKIP_IMG then
          -- Yarıda kesilen görüntünün beklenen değerlerini atla
          img := img + 1;
          load_expected;
        end if;
      else
        if hid_valid = '1' then
          cnt_hid := cnt_hid + 1;
          if to_integer(unsigned(hid)) /= exp_hid(to_integer(unsigned(hid_idx))) then
            report_mismatch("hidden", to_integer(unsigned(hid_idx)),
                            exp_hid(to_integer(unsigned(hid_idx))), to_integer(unsigned(hid)));
          end if;
        end if;
        if logit_valid = '1' then
          cnt_log := cnt_log + 1;
          if to_integer(signed(logit)) /= exp_log(to_integer(unsigned(logit_idx))) then
            report_mismatch("logit", to_integer(unsigned(logit_idx)),
                            exp_log(to_integer(unsigned(logit_idx))), to_integer(signed(logit)));
          end if;
        end if;
        if pred_valid = '1' then
          if to_integer(unsigned(pred)) /= exp_pred then
            report_mismatch("pred", 0, exp_pred, to_integer(unsigned(pred)));
          end if;
          if cnt_hid /= N_HID or cnt_log /= N_OUT then
            report_mismatch("cikis_sayisi", 0, N_HID * 100 + N_OUT, cnt_hid * 100 + cnt_log);
          end if;
          if to_integer(unsigned(pred)) = exp_label then
            correct := correct + 1;
          end if;
          cyc_sum := cyc_sum + real(cycle - start_cyc + 1);
          if done_cnt < 3 then
            report "goruntu " & integer'image(img) & ": " & integer'image(cycle - start_cyc + 1)
                   & " cevrim (baslangic " & integer'image(start_cyc) & ", bitis "
                   & integer'image(cycle) & ")";
          end if;
          if not GAPS and cycle - start_cyc + 1 > MAX_CYCLES then
            report_mismatch("gecikme", 0, MAX_CYCLES, cycle - start_cyc + 1);
          end if;
          cnt_hid := 0;
          cnt_log := 0;
          done_cnt := done_cnt + 1;
          img := img + 1;
          if done_cnt < n_expected then
            load_expected;
          end if;
        end if;
        -- İlk pikselin kabul edildiği çevrim = görüntünün başlangıcı.
        -- pred_valid'den SONRA bakılır: sonraki görüntünün ilk pikseli, önceki
        -- görüntünün pred_valid darbesiyle aynı çevrimde kabul edilebilir.
        if tvalid = '1' and tready = '1' then
          if beats = 0 then
            start_cyc := cycle;
          end if;
          beats := (beats + 1) mod N_IN;
        end if;
      end if;
    end loop;

    write(l, string'("SONUC: mismatch=") & integer'image(mismatch) & " correct="
             & integer'image(correct) & "/" & integer'image(n_expected) & " cycles=");
    write(l, cyc_sum / real(n_expected), right, 0, 1);
    writeline(output, l);
    finished <= true;
    if mismatch = 0 then
      report "TEST GECTI";
    else
      report "TEST BASARISIZ" severity failure;
    end if;
    wait;
  end process;
end architecture;
