-- tb_requant: mnist_pkg.requant fonksiyonunun birim testi.
-- Değerler Python testleriyle (model/tests/test_quant.py) aynıdır:
-- ReLU -> (+ 2^(sh-1)) -> sağa sh kaydır -> 0..255 kırp.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.mnist_pkg.all;

entity tb_requant is
end entity;

architecture sim of tb_requant is
  -- Tek bir durumu kontrol eden yardımcı prosedür (26 bit işaretli akümülatör)
  procedure check(acc : integer; sh : positive; expected : natural) is
    variable got : unsigned(7 downto 0);
  begin
    got := requant(to_signed(acc, 26), sh);
    assert to_integer(got) = expected
      report "requant(" & integer'image(acc) & ", " & integer'image(sh) & ") = "
             & integer'image(to_integer(got)) & ", beklenen " & integer'image(expected)
      severity failure;
  end procedure;
begin
  process
  begin
    check(-5, 3, 0);         -- negatif -> ReLU -> 0
    check(0, 3, 0);
    check(3, 3, 0);          -- (3 + 4) >> 3 = 0
    check(4, 3, 1);          -- (4 + 4) >> 3 = 1, yarım yukarı yuvarlanır
    check(1000000, 3, 255);  -- doyum
    check(2048, 12, 1);      -- (2048 + 2048) >> 12 = 1
    check(2047, 12, 0);      -- (2047 + 2048) >> 12 = 0
    report "SONUC: mismatch=0 correct=7/7 cycles=0";
    report "TEST GECTI";
    wait;
  end process;
end architecture;
