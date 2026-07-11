"""R2 Orders — parse, sanitize, and visualize Rivian R2 forum order data.

Pulls two live Google Sheets (the orders/deliveries tracker and a separate
reservations-only tracker) via their CSV export endpoints, with timestamped
local caching and change detection (diff-against-cache, since the export sends
no Last-Modified/ETag). Cleans the data (dedup, VIN recovery, date
normalization, geo enrichment), removes reservation-holders who have already
ordered, writes r2_orders_clean.csv, and builds an interactive Plotly dashboard
(r2_orders_dashboard.html) with 9 charts.

Tested against pandas 1.0.5 / plotly 6.x / Python 3.9.
"""

__version__ = "1.0.0"
