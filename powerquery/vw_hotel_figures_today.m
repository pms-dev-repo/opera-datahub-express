let
    Source = Json.Document(Web.Contents("https://YOUR_PROJECT.supabase.co/rest/v1/vw_hotel_figures_today", [Headers=[apikey="YOUR_SUPABASE_ANON_KEY", Authorization="Bearer YOUR_SUPABASE_ANON_KEY"]])),
    Table = Table.FromRecords(Source)
in
    Table
