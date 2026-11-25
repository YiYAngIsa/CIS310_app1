# Customer & Sales Analytics — Streamlit

## Run locally

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

The `data/` folder contains the example customers, orders and returns CSV files. The sidebar also accepts replacement files. If you deploy publicly, **do not commit confidential customer data**. Remove `data/*.csv` and provide approved synthetic/public datasets instead (or change the app to load from private storage). This app requires bundled CSV files when no sidebar uploads are supplied.

## Deploy on Streamlit Community Cloud

1. Create a GitHub repository and add `app.py`, `requirements.txt`, and `data/` with **only public or synthetic** CSV files.
2. Visit https://share.streamlit.io/ and sign in with GitHub.
3. Choose **Create app**, select your repository, branch, and entrypoint `app.py`.
4. Deploy and share the generated public URL.
5. Push commits to GitHub to update the app.

## Other deployment options

- Streamlit Community Cloud: convenient GitHub-connected hosted deployment.
- Private server or VM: install dependencies, run `streamlit run app.py --server.address 0.0.0.0 --server.port 8501`, and put HTTPS and access controls in front of the service.
- Docker: containerize the same Python app and deploy to a container host such as Google Cloud Run or Azure Container Apps, configuring the listening port and authentication as needed.

## Methodology

- Orders are line items; Order ID is the order-level key.
- Returns are deduplicated by Order ID; return rate is distinct returned orders / distinct orders.
- Category return rate counts an order once for each category present in that order.
- Customers contain repeated IDs and conflicting regional assignments. The app creates one row per customer for **unambiguous** segments and regions; ambiguous regions remain blank. The regional chart is partial and clearly labeled.
- Invalid order dates are excluded from date-filtered charts.
- Future-dated transactions in the uploaded data are displayed as provided.
