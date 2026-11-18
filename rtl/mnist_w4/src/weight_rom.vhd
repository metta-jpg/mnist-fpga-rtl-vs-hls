-- weight_rom: bir paralel kolun (lane) ağırlıklarını tutan, dosyadan ilklendirilen ROM.
--
-- Dosya nöron önceliklidir: satır r (nöron), sütun c (giriş) -> dosyanın r*N_COLS + c. satırı.
-- P paralel kol varsa bu ROM sadece r mod P = LANE olan nöronları tutar:
--   adres = (r / P) * N_COLS + c
-- Böylece P kolun ROM'ları aynı adresle okunduğunda aynı anda P farklı nöronun
-- aynı girişe ait ağırlığını verir.
-- Her satır W_BITS bitlik ikiye tümleyen hex (ceil(W_BITS/4) hane). Okuma gecikmesi 1 çevrim.
-- Dosya okuma sadece elaborasyonda yapılır; sentezde içerik sabit olarak BRAM/LUT'a gömülür.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.textio.all;

entity weight_rom is
  generic (
    FILE_NAME : string;
    N_ROWS    : positive;  -- toplam nöron sayısı
    N_COLS    : positive;  -- nöron başına giriş sayısı
    W_BITS    : positive;  -- ağırlık bit genişliği
    P         : positive;  -- paralel kol sayısı
    LANE      : natural    -- bu ROM'un kol numarası (0..P-1)
  );
  port (
    clk  : in  std_logic;
    addr : in  unsigned;
    dout : out signed(W_BITS - 1 downto 0)
  );
end entity;

architecture rtl of weight_rom is
  constant DEPTH    : positive := (N_ROWS / P) * N_COLS;
  constant HEX_BITS : positive := 4 * ((W_BITS + 3) / 4);  -- dosyadaki hane sayısı x 4
  type rom_t is array (0 to DEPTH - 1) of signed(W_BITS - 1 downto 0);

  impure function init_rom return rom_t is
    file f       : text open read_mode is FILE_NAME;
    variable l   : line;
    variable v   : std_logic_vector(HEX_BITS - 1 downto 0);
    variable rom : rom_t := (others => (others => '0'));
  begin
    for r in 0 to N_ROWS - 1 loop
      for c in 0 to N_COLS - 1 loop
        readline(f, l);
        hread(l, v);
        if r mod P = LANE then
          -- Alt W_BITS bit ikiye tümleyen değerdir (ör. 2 bitte "3" -> "11" -> -1)
          rom((r / P) * N_COLS + c) := signed(v(W_BITS - 1 downto 0));
        end if;
      end loop;
    end loop;
    return rom;
  end function;

  -- Ağırlıklar blok RAM'de tutulur (spec Bölüm 6-A). Araca bırakıldığında Vivado büyük
  -- ROM'u LUT mantığına dağıtıp ~3500 LUT harcıyor ve 100 MHz'i kaçırıyordu.
  signal ROM : rom_t := init_rom;
  attribute rom_style : string;
  attribute rom_style of ROM : signal is "block";
begin
  process (clk)
  begin
    if rising_edge(clk) then
      if to_integer(addr) < DEPTH then
        dout <= ROM(to_integer(addr));
      else
        dout <= (others => '0');
      end if;
    end if;
  end process;
end architecture;
