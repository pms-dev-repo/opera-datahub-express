# Supabase SQL Views

Version-controlled view definitions for OPERA-DATAHUB-EXPRESS.

All daily date-sensitive views use the current business date in Barbados:

`(NOW() AT TIME ZONE 'America/Barbados')::date`

Files:
- `views/vw_business_date.sql`
- `views/vw_daily_figures.sql`
- `views/vw_daily_arrivals_transportation.sql`
- `views/vw_daily_departures_transportation.sql`
- `views/vw_daily_inhouse_birthdays.sql`
