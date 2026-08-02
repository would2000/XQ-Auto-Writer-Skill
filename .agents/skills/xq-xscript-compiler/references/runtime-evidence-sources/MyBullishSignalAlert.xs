{@type:sensor}

variable:
    RsvValue(0),
    KValue(0),
    DValue(0),
    DifValue(0),
    MacdValue(0),
    OscValue(0),
    VolumeMA20(0);

SetTotalBar(100);

Stochastic(9, 3, 3, RsvValue, KValue, DValue);
MACD(WeightedClose(), 12, 26, 9, DifValue, MacdValue, OscValue);
VolumeMA20 = Average(Volume, 20);

ret = KValue > 80
  and OscValue > 0
  and Volume > VolumeMA20
  and MyBullishSignal;
