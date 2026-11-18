-- mnist_pkg: MNIST MLP hızlandırıcısının ortak sabitleri, tipleri ve fonksiyonları.
--
-- Sayısal kurallar Python altın referansıyla (model/mnist_fpga/golden.py) birebir aynıdır:
--   h = clamp((max(acc1, 0) + 2^(SH1-1)) >> SH1, 0, 255)
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.textio.all;

package mnist_pkg is
  constant N_IN  : positive := 784;  -- giriş pikseli sayısı (28x28)
  constant N_HID : positive := 32;   -- gizli katman nöron sayısı
  constant N_OUT : positive := 10;   -- çıkış sınıfı (0..9)

  type int_array is array (natural range <>) of integer;

  -- Akümülatörü 8 bit gizli aktivasyona çevirir: ReLU, yarımı yukarı yuvarlama,
  -- sağa sh bit kaydırma ve 0..255 doyum.
  function requant(acc : signed; sh : positive) return unsigned;

  -- 32 bit ikiye tümleyen hex satırlarından oluşan bias dosyasını okur
  -- (sadece elaborasyon sırasında çağrılır; sentezde sabit olarak gömülür).
  impure function read_bias(file_name : string; n : positive) return int_array;
end package;

package body mnist_pkg is
  function requant(acc : signed; sh : positive) return unsigned is
    -- Yuvarlama sabiti eklenirken taşma olmasın diye 1 bit geniş çalışılır
    variable a : signed(acc'length downto 0);
    variable s : signed(acc'length downto 0);
  begin
    if acc < 0 then
      return to_unsigned(0, 8);              -- ReLU
    end if;
    a := resize(acc, acc'length + 1) + shift_left(to_signed(1, acc'length + 1), sh - 1);
    s := shift_right(a, sh);                 -- aritmetik sağa kaydırma (a >= 0)
    if s > 255 then
      return to_unsigned(255, 8);            -- doyum
    end if;
    return resize(unsigned(std_logic_vector(s)), 8);
  end function;

  impure function read_bias(file_name : string; n : positive) return int_array is
    file f       : text open read_mode is file_name;
    variable l   : line;
    variable v   : std_logic_vector(31 downto 0);
    variable res : int_array(0 to n - 1);
  begin
    for i in 0 to n - 1 loop
      readline(f, l);
      hread(l, v);
      res(i) := to_integer(signed(v));
    end loop;
    return res;
  end function;
end package body;
