# DataHub Express - Daily Planner

Versión 1 para hotel: correo CSV → Python → Supabase → vistas → Excel Power Query.

## Flujo
1. Lee adjuntos `.csv` desde Gmail/IMAP.
2. Identifica cada reporte por los primeros 5 caracteres del archivo.
3. Procesa/normaliza datos.
4. Carga tablas en Supabase Postgres.
5. Borra el correo **solo si el proceso terminó bien**.
6. Excel consume vistas desde Supabase/PostgREST o Postgres.

## Reportes incluidos
| Prefix | Archivo ejemplo | Dataset |
|---|---|---|
| `resfu` | resfutureoccupancy_23507083.csv | Hotel Figures |
| `res_d` | res_detail_23505459.csv | Arrivals |
| `depar` | departure_all_23505938.csv | Departures |
| `pr_bi` | pr_birthday_23506219.csv | Birthdays |
| `trans` | transreq_23505545.csv | Transportation Requests |
| `snaps` | snapshot.csv | Snapshot stays |

## Setup local
```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python -m src.app
```

## Variables requeridas
Ver `.env.example`.

## Supabase
1. Crear nuevo proyecto en Supabase.
2. Copiar connection string Postgres.
3. Ejecutar `sql/001_tables.sql`.
4. Ejecutar `sql/002_views.sql`.
5. En `app_settings`, cambiar `planner_date` para probar cualquier fecha.

```sql
update app_settings set setting_value = '2026-07-06' where setting_key = 'planner_date';
```

Si dejas `planner_date` vacío, las vistas usan `current_date`.

## GitHub Actions
Agregar secrets:
- `DATABASE_URL`
- `EMAIL_HOST`
- `EMAIL_PORT`
- `EMAIL_USER`
- `EMAIL_PASSWORD`
- `EMAIL_FOLDER`

El workflow corre por cron y también manual con `workflow_dispatch`.
