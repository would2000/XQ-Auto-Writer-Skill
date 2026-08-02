{@type:autotrade}

variable:
    MomentumScore(0),
    CloseMA10(0),
    EntriesToday(0);

SetTotalBar(20);

if Date <> Date[1] then
    EntriesToday = 0;

MomentumScore = CodexV1FlowMomentum;
CloseMA10 = Average(Close, 10);

if Position = 1 and Filled = 1 and Close >= FilledAvgPrice + 50 then
    SetPosition(0, MARKET)
else if Position = 1 and Filled = 1 and Close <= FilledAvgPrice - 50 then
    SetPosition(0, MARKET)
else if Position = 1 and (MomentumScore <= 0 or Close < CloseMA10) then
    SetPosition(0, MARKET)
else if Position = 0 and Filled = 0 and EntriesToday = 0
    and MomentumScore > 0 and Close > CloseMA10 then begin
    SetPosition(1, MARKET);
    EntriesToday = 1;
end;
