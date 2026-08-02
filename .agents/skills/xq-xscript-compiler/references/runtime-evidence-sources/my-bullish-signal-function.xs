{@type:function_bool}

// 收盤價高於 20 日均線時回傳 True。
retval = Close > Average(Close, 20);
