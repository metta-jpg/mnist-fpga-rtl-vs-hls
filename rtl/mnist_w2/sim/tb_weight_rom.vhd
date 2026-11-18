-- tb_weight_rom: weight_rom birim testi.
-- Fixture: 4 satır (nöron) x 3 sütun (giriş), P = 2 paralel kol.
-- Lane 0 satır 0 ve 2'yi, lane 1 satır 1 ve 3'ü tutmalı; adres = (r / P) * 3 + c.
-- Beklenen değerler dosyadan değil formülden hesaplanır:
--   8 bit: v = r*3 + c - 6   (-6..5)
--   2 bit: v = ((r*3 + c) mod 3) - 1   (-1, 0, 1; hex '3' -> -1 işaret genişletmesi)
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tb_weight_rom is
  generic (FIX_DIR : string := "sim/fixtures/rom");
end entity;

architecture sim of tb_weight_rom is
  constant P      : positive := 2;
  constant N_ROWS : positive := 4;
  constant N_COLS : positive := 3;
  constant DEPTH  : positive := (N_ROWS / P) * N_COLS;

  signal clk  : std_logic := '0';
  signal addr : unsigned(2 downto 0) := (others => '0');
  signal d8_0, d8_1 : signed(7 downto 0);
  signal d2_0, d2_1 : signed(1 downto 0);
  signal done : boolean := false;
begin
  clk <= not clk after 5 ns when not done;

  u8_0 : entity work.weight_rom
    generic map (FILE_NAME => FIX_DIR & "/w8b.mem", N_ROWS => N_ROWS, N_COLS => N_COLS,
                 W_BITS => 8, P => P, LANE => 0)
    port map (clk => clk, addr => addr, dout => d8_0);
  u8_1 : entity work.weight_rom
    generic map (FILE_NAME => FIX_DIR & "/w8b.mem", N_ROWS => N_ROWS, N_COLS => N_COLS,
                 W_BITS => 8, P => P, LANE => 1)
    port map (clk => clk, addr => addr, dout => d8_1);
  u2_0 : entity work.weight_rom
    generic map (FILE_NAME => FIX_DIR & "/w2b.mem", N_ROWS => N_ROWS, N_COLS => N_COLS,
                 W_BITS => 2, P => P, LANE => 0)
    port map (clk => clk, addr => addr, dout => d2_0);
  u2_1 : entity work.weight_rom
    generic map (FILE_NAME => FIX_DIR & "/w2b.mem", N_ROWS => N_ROWS, N_COLS => N_COLS,
                 W_BITS => 2, P => P, LANE => 1)
    port map (clk => clk, addr => addr, dout => d2_1);

  process
    variable r, n_checked : integer;
    procedure expect(got : signed; exp : integer; name : string; a : integer) is
    begin
      assert to_integer(got) = exp
        report name & " adres " & integer'image(a) & ": " & integer'image(to_integer(got))
               & ", beklenen " & integer'image(exp)
        severity failure;
    end procedure;
  begin
    n_checked := 0;
    for a in 0 to DEPTH - 1 loop
      addr <= to_unsigned(a, addr'length);
      wait until rising_edge(clk);   -- adres örneklenir
      wait until rising_edge(clk);   -- 1 çevrim sonra veri hazır
      wait for 1 ns;
      for lane in 0 to P - 1 loop
        r := (a / N_COLS) * P + lane;  -- bu adresteki satır (nöron)
        if lane = 0 then
          expect(d8_0, r * 3 + (a mod N_COLS) - 6, "8bit lane0", a);
          expect(d2_0, ((r * 3 + (a mod N_COLS)) mod 3) - 1, "2bit lane0", a);
        else
          expect(d8_1, r * 3 + (a mod N_COLS) - 6, "8bit lane1", a);
          expect(d2_1, ((r * 3 + (a mod N_COLS)) mod 3) - 1, "2bit lane1", a);
        end if;
        n_checked := n_checked + 2;
      end loop;
    end loop;
    report "SONUC: mismatch=0 correct=" & integer'image(n_checked) & "/"
           & integer'image(n_checked) & " cycles=0";
    report "TEST GECTI";
    done <= true;
    wait;
  end process;
end architecture;
