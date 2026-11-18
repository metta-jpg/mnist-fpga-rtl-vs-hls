-- mnist_mlp: 784 -> 32 -> 10 tamsayı MLP hızlandırıcı çekirdeği.
--
-- Akış (durum makinesi):
--   S_LOAD    : 784 piksel AXI-Stream ile giriş tamponuna (xbuf) yazılır.
--   S_L1      : 1. katman. P nöron paralel: her çevrimde bir piksel ve P ağırlık okunur,
--               P akümülatör çarp-topla yapar. 784 çevrim sürer.
--   S_L1_WAIT : çarp-topla boru hattının boşalması beklenir (ROM okuma 1 + çarpma 1 + toplama 1).
--   S_L1_OUT  : P akümülatör sırayla requant ile 8 bite çevrilip gizli tampona (hbuf) yazılır.
--               32/P grup bitene kadar S_L1'e dönülür.
--   S_L2      : 2. katman. Tek çarp-topla birimi, logit başına 32 çevrim.
--   S_L2_WAIT : son çarp-toplanın bitmesi beklenir.
--   S_L2_OUT  : logit hazır; argmax güncellenir (sadece kesin büyükse -> eşitlikte en küçük indeks).
--   S_DONE    : tahmin çıkışa verilir, pred_valid_o 1 çevrim '1' olur, S_LOAD'a dönülür.
--
-- Sayısal davranış Python altın referansıyla birebir aynıdır (model/mnist_fpga/golden.py).
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.mnist_pkg.all;

entity mnist_mlp is
  generic (
    W_BITS    : positive := 8;   -- ağırlık bit genişliği (8/4/2)
    P         : positive := 1;   -- 1. katmanda paralel nöron sayısı, 32'yi bölmeli
    SH1       : positive;        -- gizli katman kaydırma miktarı
    ACC1_BITS : positive;        -- 1. katman akümülatör genişliği
    ACC2_BITS : positive;        -- 2. katman akümülatör genişliği
    DATA_DIR  : string;          -- w1.mem, b1.mem, w2.mem, b2.mem klasörü, sonda '/' yok
    USE_DSP   : boolean := true  -- çarpıcılar DSP48'e mi (true) LUT'a mı (false) yerleşsin
  );
  port (
    clk, rst        : in  std_logic;
    s_axis_tdata    : in  std_logic_vector(7 downto 0);  -- piksel 0..255
    s_axis_tvalid   : in  std_logic;
    s_axis_tready   : out std_logic;
    s_axis_tlast    : in  std_logic;                     -- yok sayılır, çekirdek 784'ü kendi sayar
    pred_o          : out std_logic_vector(3 downto 0);
    pred_valid_o    : out std_logic;                     -- 1 çevrimlik darbe
    -- hata ayıklama (testbench için; üst sarmalayıcıda bağlanmaz)
    hid_valid_o     : out std_logic;
    hid_idx_o       : out std_logic_vector(4 downto 0);
    hid_o           : out std_logic_vector(7 downto 0);
    logit_valid_o   : out std_logic;
    logit_idx_o     : out std_logic_vector(3 downto 0);
    logit_o         : out std_logic_vector(ACC2_BITS - 1 downto 0)
  );
end entity;

architecture rtl of mnist_mlp is
  function clog2(n : positive) return natural is
    variable r : natural := 0;
    variable v : natural := 1;
  begin
    while v < n loop
      v := v * 2;
      r := r + 1;
    end loop;
    return r;
  end function;

  function dsp_str(b : boolean) return string is
  begin
    if b then
      return "yes";
    end if;
    return "no";
  end function;

  -- Piksel (0..255) işaretsiz; işaretli çarpma için başına '0' eklenip 9 bit yapılır
  function to_s9(u : unsigned(7 downto 0)) return signed is
  begin
    return signed('0' & std_logic_vector(u));
  end function;

  constant G       : positive := N_HID / P;              -- 1. katman grup sayısı
  constant A1_BITS : positive := clog2(G * N_IN);        -- lane ROM adres genişliği
  constant A2_BITS : positive := clog2(N_OUT * N_HID);   -- 2. katman ROM adres genişliği

  -- Bias'lar elaborasyonda dosyadan okunur ve sabit olarak gömülür
  constant B1 : int_array(0 to N_HID - 1) := read_bias(DATA_DIR & "/b1.mem", N_HID);
  constant B2 : int_array(0 to N_OUT - 1) := read_bias(DATA_DIR & "/b2.mem", N_OUT);

  type state_t is (S_LOAD, S_L1, S_L1_WAIT, S_L1_OUT, S_L2, S_L2_WAIT, S_L2_OUT, S_DONE);
  signal state : state_t := S_LOAD;

  type xbuf_t is array (0 to N_IN - 1) of unsigned(7 downto 0);
  signal xbuf : xbuf_t;                               -- giriş görüntüsü tamponu (RAM)
  signal x_rd : unsigned(7 downto 0);                 -- tampondan okunan piksel (1 çevrim gecikmeli)
  type hbuf_t is array (0 to N_HID - 1) of unsigned(7 downto 0);
  signal hbuf : hbuf_t;                               -- gizli aktivasyonlar
  signal h_rd : unsigned(7 downto 0);                 -- 2. katmana giden aktivasyon (1 çevrim gecikmeli)

  type w1_arr_t is array (0 to P - 1) of signed(W_BITS - 1 downto 0);
  signal w1   : w1_arr_t;                             -- P kolun o anki ağırlıkları
  signal w2   : signed(W_BITS - 1 downto 0);
  signal a1   : unsigned(A1_BITS - 1 downto 0);       -- 1. katman ROM adresi: grp*784 + cnt
  signal a2   : unsigned(A2_BITS - 1 downto 0);       -- 2. katman ROM adresi: k*32 + j

  type acc1_arr_t is array (0 to P - 1) of signed(ACC1_BITS - 1 downto 0);

  -- DSP politikası: çarp-topla sinyalleri DSP48'e mi LUT'a mı yerleşsin.
  -- (Öznitelik ve akümülatörler aşağıdaki iç block'ta: VHDL büyük/küçük harf ayırmadığı
  -- için 'use_dsp' özniteliği burada USE_DSP generic'iyle çakışırdı.)
  constant DSP_ATTR : string := dsp_str(USE_DSP);

  signal cnt     : natural range 0 to N_IN - 1 := 0;  -- piksel / giriş sayacı
  signal grp     : natural range 0 to G - 1 := 0;     -- 1. katman grup numarası
  signal lane    : natural range 0 to P - 1 := 0;     -- S_L1_OUT'ta yazılan kol
  signal k       : natural range 0 to N_OUT - 1 := 0; -- 2. katman çıkış (logit) numarası
  signal j       : natural range 0 to N_HID - 1 := 0; -- 2. katman giriş numarası
  signal mac1_en : std_logic := '0';                  -- 1. katman çarp-topla etkin
  signal mac2_en : std_logic := '0';                  -- 2. katman çarp-topla etkin
  signal best    : signed(ACC2_BITS - 1 downto 0);    -- argmax: şimdiye kadarki en büyük logit
  signal best_k  : natural range 0 to N_OUT - 1 := 0;
begin
  assert N_HID mod P = 0 report "P, 32'yi bölmeli" severity failure;

  s_axis_tready <= '1' when state = S_LOAD else '0';

  -- ROM adresleri çarpma yerine sayaçla üretilir (a1 = grp*784 + cnt, a2 = k*32 + j).
  -- Gruplar ROM'da arka arkaya durduğu için adres her okumada sadece 1 artar; böylece
  -- adres hesabı için DSP harcanmaz ve USE_DSP=false gerçekten DSP'siz olur.

  -- P adet 1. katman ağırlık ROM'u (her kol r mod P = lane olan nöronları tutar)
  gen_w1 : for p_i in 0 to P - 1 generate
    rom : entity work.weight_rom
      generic map (FILE_NAME => DATA_DIR & "/w1.mem", N_ROWS => N_HID, N_COLS => N_IN,
                   W_BITS => W_BITS, P => P, LANE => p_i)
      port map (clk => clk, addr => a1, dout => w1(p_i));
  end generate;

  rom_w2 : entity work.weight_rom
    generic map (FILE_NAME => DATA_DIR & "/w2.mem", N_ROWS => N_OUT, N_COLS => N_HID,
                 W_BITS => W_BITS, P => 1, LANE => 0)
    port map (clk => clk, addr => a2, dout => w2);

  -- Giriş tamponu: S_LOAD'da yazılır, her çevrim cnt adresinden okunur (senkron okuma -> RAM)
  process (clk)
  begin
    if rising_edge(clk) then
      if rst = '0' and state = S_LOAD and s_axis_tvalid = '1' then
        xbuf(cnt) <= unsigned(s_axis_tdata);
      end if;
      x_rd <= xbuf(cnt);
    end if;
  end process;

  -- Ana durum makinesi ve çarp-topla birimleri
  core : block
    signal acc1 : acc1_arr_t;                         -- 1. katman akümülatörleri
    signal acc2 : signed(ACC2_BITS - 1 downto 0);     -- 2. katman akümülatörü
    -- Çarp-topla iki aşamalı boru hattı: önce çarpım register'a yazılır (DSP'de MREG),
    -- sonraki çevrimde akümülatöre eklenir. LUT modunda 100 MHz'e sığmak için gerekli.
    type prod1_arr_t is array (0 to P - 1) of signed(9 + W_BITS - 1 downto 0);
    signal prod1    : prod1_arr_t;
    signal prod2    : signed(9 + W_BITS - 1 downto 0);
    signal mac1_en2 : std_logic := '0';               -- çarpım hazır, toplama aşaması
    signal mac2_en2 : std_logic := '0';
    attribute use_dsp : string;
    attribute use_dsp of acc1  : signal is DSP_ATTR;
    attribute use_dsp of acc2  : signal is DSP_ATTR;
    attribute use_dsp of prod1 : signal is DSP_ATTR;
    attribute use_dsp of prod2 : signal is DSP_ATTR;
  begin
  process (clk)
  begin
    if rising_edge(clk) then
      if rst = '1' then
        state         <= S_LOAD;
        cnt           <= 0;
        grp           <= 0;
        lane          <= 0;
        k             <= 0;
        j             <= 0;
        a1            <= (others => '0');
        a2            <= (others => '0');
        mac1_en       <= '0';
        mac2_en       <= '0';
        mac1_en2      <= '0';
        mac2_en2      <= '0';
        pred_valid_o  <= '0';
        hid_valid_o   <= '0';
        logit_valid_o <= '0';
      else
        pred_valid_o  <= '0';
        hid_valid_o   <= '0';
        logit_valid_o <= '0';
        mac1_en       <= '0';
        mac2_en       <= '0';
        mac1_en2      <= mac1_en;
        mac2_en2      <= mac2_en;

        -- Çarpma aşaması: okuma bir önceki çevrimde başlatıldıysa veri şimdi hazır
        if mac1_en = '1' then
          for p_i in 0 to P - 1 loop
            prod1(p_i) <= to_s9(x_rd) * w1(p_i);
          end loop;
        end if;
        if mac2_en = '1' then
          prod2 <= to_s9(h_rd) * w2;
        end if;
        -- Toplama aşaması
        if mac1_en2 = '1' then
          for p_i in 0 to P - 1 loop
            acc1(p_i) <= acc1(p_i) + resize(prod1(p_i), ACC1_BITS);
          end loop;
        end if;
        if mac2_en2 = '1' then
          acc2 <= acc2 + resize(prod2, ACC2_BITS);
        end if;

        case state is
          when S_LOAD =>
            if s_axis_tvalid = '1' then
              if cnt = N_IN - 1 then
                cnt   <= 0;
                grp   <= 0;
                a1    <= (others => '0');
                state <= S_L1;
                for p_i in 0 to P - 1 loop
                  acc1(p_i) <= to_signed(B1(p_i), ACC1_BITS);  -- akümülatör bias ile başlar
                end loop;
              else
                cnt <= cnt + 1;
              end if;
            end if;

          when S_L1 =>
            mac1_en <= '1';  -- bu çevrimde adres verildi, sonraki çevrim çarp-topla
            a1      <= a1 + 1;
            if cnt = N_IN - 1 then
              cnt   <= 0;
              state <= S_L1_WAIT;
            else
              cnt <= cnt + 1;
            end if;

          when S_L1_WAIT =>
            -- Boru hattı boşalınca (iki aşama da pasif) akümülatörler son değerinde
            lane <= 0;
            if mac1_en = '0' and mac1_en2 = '0' then
              state <= S_L1_OUT;
            end if;

          when S_L1_OUT =>
            hbuf(grp * P + lane) <= requant(acc1(lane), SH1);
            hid_valid_o <= '1';
            hid_idx_o   <= std_logic_vector(to_unsigned(grp * P + lane, 5));
            hid_o       <= std_logic_vector(requant(acc1(lane), SH1));
            if lane = P - 1 then
              if grp = G - 1 then
                k     <= 0;
                j     <= 0;
                a2    <= (others => '0');
                acc2  <= to_signed(B2(0), ACC2_BITS);
                state <= S_L2;
              else
                grp <= grp + 1;
                for p_i in 0 to P - 1 loop
                  acc1(p_i) <= to_signed(B1((grp + 1) * P + p_i), ACC1_BITS);
                end loop;
                state <= S_L1;
              end if;
            else
              lane <= lane + 1;
            end if;

          when S_L2 =>
            h_rd    <= hbuf(j);
            mac2_en <= '1';
            a2      <= a2 + 1;
            if j = N_HID - 1 then
              j     <= 0;
              state <= S_L2_WAIT;
            else
              j <= j + 1;
            end if;

          when S_L2_WAIT =>
            if mac2_en = '0' and mac2_en2 = '0' then
              state <= S_L2_OUT;
            end if;

          when S_L2_OUT =>
            logit_valid_o <= '1';
            logit_idx_o   <= std_logic_vector(to_unsigned(k, 4));
            logit_o       <= std_logic_vector(acc2);
            if k = 0 or acc2 > best then  -- kesin büyük: eşitlikte en küçük indeks kalır
              best   <= acc2;
              best_k <= k;
            end if;
            if k = N_OUT - 1 then
              state <= S_DONE;
            else
              k     <= k + 1;
              acc2  <= to_signed(B2(k + 1), ACC2_BITS);
              state <= S_L2;
            end if;

          when S_DONE =>
            pred_o       <= std_logic_vector(to_unsigned(best_k, 4));
            pred_valid_o <= '1';
            cnt          <= 0;
            state        <= S_LOAD;
        end case;
      end if;
    end if;
  end process;
  end block;
end architecture;
