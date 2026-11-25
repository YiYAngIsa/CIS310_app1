# Customer & Sales Analytics — Streamlit dashboard

## Run locally

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

The dashboard loads `data/customers.csv`, `data/orders.csv`, and `data/returns.csv` by default. You can upload replacements in the sidebar. The application reads UTF-8 and Windows-1252 CSV files.

## Features

- Sidebar multi-select filters for **customer segments**, **customer regions**, and **product categories**, plus an order-date range. Multiple selections are supported in each filter. The active selections appear above the monthly sales chart.
- Vertical executive metrics: total sales, total profit, distinct orders, distinct customers, and order return rate. No profit/AOV chart selector; profitability charts remain on their own tab.
- Monthly sales trend by category without Q4 shading; monthly total sales; category sales; category profit pie (or bar when profits are negative); segment profit; category return rate; partial regional sales.
- Data explorer with first five rows, per-column type, description, missing and unique counts, and up to 1,000 browsable records.
- Custom chart builder: scatterplot, bar, line, histogram, box plot, with relevant variable selectors. Bar/line charts aggregate by sum, mean, median, or count.
- CSV export of **all rows matching the current filters** from the joined Orders table; raw data exports are also available.

### Region warning

The Customers file has repeated Customer IDs with conflicting regions. Orders does not contain order-level region. The app safely joins only unambiguous customer-level regions and puts the others in the **Unknown / ambiguous** filter option. Selecting one or more known regions will exclude unknown records; regional charts only cover reliably assigned records. The default selection includes all regions, including Unknown / ambiguous, so it does not silently drop sales.

Returns are matched at the order level by Order ID; order-line sales and profit are summed from Orders. The date filter excludes invalid dates. Future-dated orders remain included if their dates fall within the selected range.

## Deploy as a website with Streamlit Community Cloud

1. Put `app.py` and `requirements.txt` in a GitHub repository.
2. Add only **approved public or synthetic** CSV files to `data/` if you want default data to appear automatically.
3. Go to https://share.streamlit.io/, connect GitHub, and select the repository and `app.py` as the entry point.
4. Click Deploy and share the Streamlit app URL.
5. Push updated code to GitHub to deploy updates.

**Privacy:** The bundled example files may contain customer information. Do not publish them to a public repository without permission. For confidential data, remove the `data/` folder from the public repo and use private, authenticated data storage or a private hosting setup. The app currently expects bundled files when no uploads are supplied.

## Alternative hosting

Deploy to a managed container service, private VM, or internal server with HTTPS and authentication. Start with `streamlit run app.py --server.address 0.0.0.0 --server.port 8501`, and configure your hosting provider's port and network settings.
