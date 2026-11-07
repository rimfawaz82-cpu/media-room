//+------------------------------------------------------------------+
//| ExportBidAskM1.mq5 — XAE Research Lab                            |
//| Compresses the broker's tick history into one row per minute:     |
//| Bid OHLC, Ask OHLC, real spread (open/min/mean/max), tick count.  |
//| The output is much smaller than a raw tick export but keeps the  |
//| real execution-cost information needed for backtesting.          |
//|                                                                  |
//| Install: MT5 -> File -> Open Data Folder -> MQL5/Scripts,        |
//| copy this file there, compile it in MetaEditor (F7), then drag   |
//| it onto any chart. Output: MQL5/Files/<InpFile>.                 |
//| Tip: export one year at a time (InpFrom / InpTo) to keep files    |
//| small.                                                           |
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict

input string   InpSymbol = "XAUUSD.c";
input datetime InpFrom   = D'2025.01.01 00:00';
input datetime InpTo     = D'2026.01.01 00:00';
input string   InpFile   = "XAUUSD_c_M1_bidask_2025.csv";

int    g_handle;
int    g_digits;

void WriteRow(datetime m, double bo, double bh, double bl, double bc,
              double ao, double ah, double al, double ac,
              double sopen, double smin, double ssum, double smax, int cnt)
  {
   string row = TimeToString(m, TIME_DATE | TIME_MINUTES) + "," +
                DoubleToString(bo, g_digits) + "," + DoubleToString(bh, g_digits) + "," +
                DoubleToString(bl, g_digits) + "," + DoubleToString(bc, g_digits) + "," +
                DoubleToString(ao, g_digits) + "," + DoubleToString(ah, g_digits) + "," +
                DoubleToString(al, g_digits) + "," + DoubleToString(ac, g_digits) + "," +
                DoubleToString(sopen, g_digits) + "," + DoubleToString(smin, g_digits) + "," +
                DoubleToString(ssum / cnt, g_digits + 1) + "," + DoubleToString(smax, g_digits) + "," +
                IntegerToString(cnt) + "\r\n";
   FileWriteString(g_handle, row);
  }

void OnStart()
  {
   if(!SymbolSelect(InpSymbol, true))
     { Print("Symbol not found: ", InpSymbol); return; }
   g_digits = (int)SymbolInfoInteger(InpSymbol, SYMBOL_DIGITS);

   g_handle = FileOpen(InpFile, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(g_handle == INVALID_HANDLE)
     { Print("Cannot open file, error ", GetLastError()); return; }
   FileWriteString(g_handle, "time,bid_o,bid_h,bid_l,bid_c,ask_o,ask_h,ask_l,ask_c,"
                             "spr_open,spr_min,spr_mean,spr_max,ticks\r\n");

   MqlTick t[];
   long rows = 0;
   datetime firstTick = 0;

   for(datetime d = InpFrom; d < InpTo; d += 86400)
     {
      if(IsStopped()) break;
      ulong from = (ulong)d * 1000;
      ulong to   = (ulong)(d + 86400) * 1000 - 1;

      int n = -1;
      for(int k = 0; k < 5 && n < 0; k++)          // history may still be syncing
        {
         ResetLastError();
         n = CopyTicksRange(InpSymbol, t, COPY_TICKS_INFO, from, to);
         if(n < 0) Sleep(1000);
        }
      if(n <= 0) continue;

      datetime cur = 0;
      double bo = 0, bh = 0, bl = 0, bc = 0, ao = 0, ah = 0, al = 0, ac = 0;
      double sopen = 0, smin = 0, smax = 0, ssum = 0;
      int cnt = 0;

      for(int i = 0; i < n; i++)
        {
         double bid = t[i].bid, ask = t[i].ask;
         if(bid <= 0 || ask <= 0) continue;
         datetime m = (datetime)(t[i].time - t[i].time % 60);
         double s = ask - bid;
         if(m != cur)
           {
            if(cnt > 0) { WriteRow(cur, bo, bh, bl, bc, ao, ah, al, ac, sopen, smin, ssum, smax, cnt); rows++; }
            if(firstTick == 0) firstTick = m;
            cur = m;
            bo = bh = bl = bc = bid;
            ao = ah = al = ac = ask;
            sopen = smin = smax = ssum = s;
            cnt = 1;
            continue;
           }
         if(bid > bh) bh = bid;
         if(bid < bl) bl = bid;
         bc = bid;
         if(ask > ah) ah = ask;
         if(ask < al) al = ask;
         ac = ask;
         if(s < smin) smin = s;
         if(s > smax) smax = s;
         ssum += s;
         cnt++;
        }
      if(cnt > 0) { WriteRow(cur, bo, bh, bl, bc, ao, ah, al, ac, sopen, smin, ssum, smax, cnt); rows++; }
      Comment("Exporting ", InpSymbol, "  ", TimeToString(d, TIME_DATE), "  rows: ", rows);
     }

   FileClose(g_handle);
   Comment("");
   PrintFormat("Done: %I64d minute rows written to MQL5/Files/%s. First tick minute: %s",
               rows, InpFile, TimeToString(firstTick, TIME_DATE | TIME_MINUTES));
  }
//+------------------------------------------------------------------+
