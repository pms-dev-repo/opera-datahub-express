CREATE OR REPLACE VIEW public.vw_daily_figures AS
WITH
business_day AS (
    SELECT
        (NOW() AT TIME ZONE 'America/Barbados')::date AS business_date
),
figures AS (
    SELECT
        1 AS sort_order,
        'Adults'::text AS metric,
        (
            SELECT COALESCE(SUM(s.adults), 0::bigint)
            FROM public.snapshot s
            CROSS JOIN business_day bd
            WHERE s.stay_date = bd.business_date
        ) AS in_house,
        (
            SELECT COALESCE(SUM(d.adults), 0::bigint)
            FROM public.odata_departures_all d
            CROSS JOIN business_day bd
            WHERE d.departure_date = bd.business_date
        ) AS less_departure,
        (
            SELECT COALESCE(SUM(a.adults), 0::bigint)
            FROM public.odata_arr_detail a
            CROSS JOIN business_day bd
            WHERE a.arrival_date = bd.business_date
        ) AS plus_arrivals

    UNION ALL

    SELECT
        2,
        'Children -18'::text,
        (
            SELECT COALESCE(SUM(s.child_bucket_3), 0::bigint)
            FROM public.snapshot s
            CROSS JOIN business_day bd
            WHERE s.stay_date = bd.business_date
        ),
        (
            SELECT COALESCE(SUM(d.child_bucket_3), 0::bigint)
            FROM public.odata_departures_all d
            CROSS JOIN business_day bd
            WHERE d.departure_date = bd.business_date
        ),
        (
            SELECT COALESCE(SUM(a.child_bucket_3), 0::bigint)
            FROM public.odata_arr_detail a
            CROSS JOIN business_day bd
            WHERE a.arrival_date = bd.business_date
        )

    UNION ALL

    SELECT
        3,
        'Children -12'::text,
        (
            SELECT COALESCE(SUM(s.child_bucket_2), 0::bigint)
            FROM public.snapshot s
            CROSS JOIN business_day bd
            WHERE s.stay_date = bd.business_date
        ),
        (
            SELECT COALESCE(SUM(d.child_bucket_2), 0::bigint)
            FROM public.odata_departures_all d
            CROSS JOIN business_day bd
            WHERE d.departure_date = bd.business_date
        ),
        (
            SELECT COALESCE(SUM(a.child_bucket_2), 0::bigint)
            FROM public.odata_arr_detail a
            CROSS JOIN business_day bd
            WHERE a.arrival_date = bd.business_date
        )

    UNION ALL

    SELECT
        4,
        'Children -3'::text,
        (
            SELECT COALESCE(SUM(s.child_bucket_1), 0::bigint)
            FROM public.snapshot s
            CROSS JOIN business_day bd
            WHERE s.stay_date = bd.business_date
        ),
        (
            SELECT COALESCE(SUM(d.child_bucket_1), 0::bigint)
            FROM public.odata_departures_all d
            CROSS JOIN business_day bd
            WHERE d.departure_date = bd.business_date
        ),
        (
            SELECT COALESCE(SUM(a.child_bucket_1), 0::bigint)
            FROM public.odata_arr_detail a
            CROSS JOIN business_day bd
            WHERE a.arrival_date = bd.business_date
        )

    UNION ALL

    SELECT
        5,
        'Persons'::text,
        (
            SELECT
                COALESCE(SUM(s.adults), 0::bigint)
                + COALESCE(SUM(s.children), 0::bigint)
            FROM public.snapshot s
            CROSS JOIN business_day bd
            WHERE s.stay_date = bd.business_date
        ),
        (
            SELECT
                COALESCE(SUM(d.adults), 0::bigint)
                + COALESCE(SUM(d.children), 0::bigint)
            FROM public.odata_departures_all d
            CROSS JOIN business_day bd
            WHERE d.departure_date = bd.business_date
        ),
        (
            SELECT
                COALESCE(SUM(a.adults), 0::bigint)
                + COALESCE(SUM(a.children), 0::bigint)
            FROM public.odata_arr_detail a
            CROSS JOIN business_day bd
            WHERE a.arrival_date = bd.business_date
        )

    UNION ALL

    SELECT
        6,
        'Rooms'::text,
        (
            SELECT COUNT(*)
            FROM public.snapshot s
            CROSS JOIN business_day bd
            WHERE s.stay_date = bd.business_date
        ),
        (
            SELECT COALESCE(SUM(d.rooms), 0::bigint)
            FROM public.odata_departures_all d
            CROSS JOIN business_day bd
            WHERE d.departure_date = bd.business_date
        ),
        (
            SELECT COALESCE(SUM(a.rooms), 0::bigint)
            FROM public.odata_arr_detail a
            CROSS JOIN business_day bd
            WHERE a.arrival_date = bd.business_date
        )
)
SELECT
    bd.business_date,
    f.sort_order,
    f.metric,
    f.in_house,
    f.less_departure,
    f.plus_arrivals,
    f.in_house - f.less_departure + f.plus_arrivals AS exp_in_house
FROM figures f
CROSS JOIN business_day bd
ORDER BY f.sort_order;
