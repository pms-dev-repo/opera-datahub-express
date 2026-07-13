CREATE OR REPLACE VIEW public.vw_daily_departures_transportation AS
WITH business_day AS (
    SELECT
        (NOW() AT TIME ZONE 'America/Barbados')::date AS business_date
)
SELECT
    d.room_no,
    d.guest_name,
    d.arrival_date,
    d.departure_date,
    d.nights,
    d.adults,
    d.children,
    d.rooms,
    d.room_type,
    d.reservation_status,
    d.departure_time,
    d.payment_method,
    d.rate_code,
    d.vip,
    t.transport_direction,
    t.transport_type,
    t.transport_datetime,
    t.transport_date,
    t.station_code,
    t.carrier_code AS transport_flight,
    t.transport_code,
    f.airline_code,
    al.airline_name,
    f.origin_iata,
    ao.city AS origin_city,
    ao.country AS origin_country,
    f.destination_iata,
    ad.city AS destination_city,
    ad.country AS destination_country
FROM public.odata_departures_all d
CROSS JOIN business_day bd
LEFT JOIN public.odata_transportation t
    ON UPPER(TRIM(t.guest_name)) = UPPER(TRIM(d.guest_name))
   AND t.transport_direction = 'DROPOFF'
   AND t.transport_date = d.departure_date
LEFT JOIN public.flight_reference f
    ON UPPER(REPLACE(t.carrier_code, ' ', ''))
     = UPPER(f.flight_number::text)
LEFT JOIN public.airlines al
    ON al.airline_code = f.airline_code
LEFT JOIN public.airports ao
    ON ao.iata_code = f.origin_iata
LEFT JOIN public.airports ad
    ON ad.iata_code = f.destination_iata
WHERE
    d.departure_date = bd.business_date
ORDER BY
    t.transport_datetime,
    d.room_no;
