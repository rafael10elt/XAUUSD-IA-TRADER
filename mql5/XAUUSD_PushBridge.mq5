#property strict

input string QueueFileName = "xauusd_push_queue.txt";
input int TimerSeconds = 2;

ulong g_last_position = 0;

int OnInit()
{
   EventSetTimer(TimerSeconds);
   Print("XAUUSD Push Bridge initialized");
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}

void OnTimer()
{
   int handle = FileOpen(QueueFileName, FILE_READ | FILE_TXT | FILE_COMMON | FILE_SHARE_READ);
   if(handle == INVALID_HANDLE)
      return;

   ulong size = (ulong)FileSize(handle);
   if(g_last_position > size)
      g_last_position = 0;

   FileSeek(handle, (long)g_last_position, SEEK_SET);

   while(!FileIsEnding(handle))
   {
      string line = FileReadString(handle);
      if(StringLen(line) > 0)
      {
         SendNotification(line);
         Print(line);
      }
   }

   g_last_position = (ulong)FileTell(handle);
   FileClose(handle);
}
