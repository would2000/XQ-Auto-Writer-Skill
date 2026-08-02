{@type:indicator}

variable:
    TrendScore(0),
    ShortAverage(0),
    LongAverage(0),
    VolumeAverage(0);

TrendScore = MyTrendScore();
ShortAverage = Average(Close, 20);
LongAverage = Average(Close, 60);
VolumeAverage = Average(Volume, 20);

if Close > ShortAverage
   and ShortAverage > LongAverage
   and Volume > VolumeAverage * 1.5 then
begin
    Plot2(TrendScore, "強勢趨勢分數");
    NoPlot(1);
end
else
begin
    Plot1(TrendScore, "趨勢分數");
    NoPlot(2);
end;
