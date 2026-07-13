CREATE OR REPLACE VIEW public.vw_daily_arrivals_transportation AS
WITH business_day AS (
    SELECT
        (NOW() AT TIME ZONE 'America/Barbados')::date AS business_date
)
SELECT
    a.room_no,
    a.guest_name,
    a.arrival_date,
    a.departure_date,
    a.room_type,
    a.adults,
    a.children,
    a.rooms,
    a.market_code,
    a.reservation_status,
    a.confirmation_no,
    a.vip,
    a.prev_stays,
    a.prev_nights,
    a.last_room,
    a.carrier_code AS arrival_carrier_code,
    a.method_of_arrival,
    t.transport_direction,
    t.transport_type,
    t.transport_datetime,
    t.transport_date,
    t.stay_date AS transport_stay_date,
    t.station_code,
    t.carrier_code AS transport_flight,
    t.transport_code,
    t.room_no AS transport_room_no,
    t.vip AS transport_vip,
    t.reservation_status AS transport_reservation_status,
    fr.airline_code,
    al.airline_name,
    fr.origin_iata,
    origin_airport.airport_name AS origin_airport,
    origin_airport.city AS origin_city,
    origin_airport.country AS origin_country,
    fr.destination_iata,
    destination_airport.airport_name AS destination_airport,
    destination_airport.city AS destination_city,
    destination_airport.country AS destination_country,
    a.share_with,
    a.accompanying_names,
    a.arrival_time,
    a.source_code,
    TO_CHAR(t.transport_time::interval, 'HH24:MI') AS transport_time,
    TO_CHAR(t.transport_time::interval + INTERVAL '1 hour', 'HH24:MI') AS exp_arr_hotel
FROM public.odata_arr_detail a
CROSS JOIN business_day bd
LEFT JOIN public.odata_transportation t
    ON UPPER(TRIM(t.guest_name)) = UPPER(TRIM(a.guest_name))
   AND t.transport_direction = 'PICKUP'
   AND t.stay_date = a.arrival_date
LEFT JOIN public.flight_reference fr
    ON UPPER(REPLACE(TRIM(t.carrier_code), ' ', ''))
     = UPPER(REPLACE(TRIM(fr.flight_number), ' ', ''))
LEFT JOIN public.airlines al
    ON al.airline_code = fr.airline_code
LEFT JOIN public.airports origin_airport
    ON origin_airport.iata_code = fr.origin_iata
LEFT JOIN public.airports destination_airport
    ON destination_airport.iata_code = fr.destination_iata
WHERE
    a.arrival_date = bd.business_date
    AND t.transport_direction = 'PICKUP';
