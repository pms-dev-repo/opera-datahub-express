PyMuPDF fix for OPERA DataHub Express

Replace these files in the repository:

1. src/core/pdf/pdf_engine.py
2. src/parsers/pdf_engine.py
3. requirements.txt

Why two PDF engines?
- src/core/pdf/pdf_engine.py is used by Arrival Detail v2.
- src/parsers/pdf_engine.py is used by Departures and other legacy parsers.

The change replaces pdfminer/pdfplumber word extraction with PyMuPDF while
preserving the existing DataFrame columns and visual gray-band metadata.

Validated against:
- odata_arr_detail24563370.pdf: 32 rows
- odata_arr_detail24566109.pdf: 32 rows
- odata_arr_detail24567991.pdf: 32 rows
- odata_departures_all24541135.pdf: 46 rows

After replacing the files:

pip install -r requirements.txt
python -m src.app
