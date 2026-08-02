{@type:filter}

variable:
    BreakoutScore(0),
    CloseMA20(0),
    CloseMA60(0),
    VolumeMA20(0),
    AmountMA20(0);

SetTotalBar(60);

BreakoutScore = MyBreakoutStrength;
CloseMA20 = Average(Close, 20);
CloseMA60 = Average(Close, 60);
VolumeMA20 = Average(Volume, 20);
AmountMA20 = Average(GetField("成交金額(億)"), 20);

ret = Close > CloseMA20
  and CloseMA20 > CloseMA60
  and Volume > VolumeMA20 * 1.5
  and AmountMA20 > 1
  and BreakoutScore >= 0;

OutputField(1, BreakoutScore, 2, "突破強度");
OutputField(2, CloseMA20, 2, "20日均線");
OutputField(3, AmountMA20, 2, "20日平均成交金額(億)");
