CREATE OR REPLACE VIEW public.vw_daily_inhouse_birthdays AS
SELECT
    room_no,
    guest_name,
    company,
    arrival_date,
    departure_date,
    number_of_nights,
    reservation_status,
    birth_date,
    age,
    vip,
    number_of_stays,
    last_stay,
    source,
    travel_agent,
    rate_code
FROM public.odata_gih_birthday
WHERE
    reservation_status = ANY (ARRAY['CKIN'::text, 'CHECKED IN'::text])
ORDER BY
    room_no,
    guest_name;
