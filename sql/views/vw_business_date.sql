CREATE OR REPLACE VIEW public.vw_business_date AS
SELECT
    (NOW() AT TIME ZONE 'America/Barbados')::date AS business_date;
