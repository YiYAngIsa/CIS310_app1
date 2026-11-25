"""Customer, order and return analytics dashboard.
Run: streamlit run app.py
"""
from pathlib import Path
import io
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Customer & Sales Analytics", page_icon="📊", layout="wide")
BASE = Path(__file__).parent
COLORS = {"Furniture": "#d9a441", "Office Supplies": "#318a86", "Technology": "#4776c5"}


def load_csv(source):
    """Read CSVs with UTF-8 or Windows-1252 encodings."""
    payload = Path(source).read_bytes() if isinstance(source, (str, Path)) else source.getvalue()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return pd.read_csv(io.BytesIO(payload), encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Unable to decode CSV as UTF-8 or Windows-1252")


def validate(df, required, name):
    missing = sorted(set(required) - set(df.columns))
    if missing:
        st.error(f"{name} is missing columns: {', '.join(missing)}")
        st.stop()


@st.cache_data(show_spinner=False)
def prepare(customer_bytes, order_bytes, return_bytes):
    customers = pd.read_csv(io.BytesIO(customer_bytes), encoding="utf-8-sig", dtype={"Postal Code": "string"})
    try:
        orders = pd.read_csv(io.BytesIO(order_bytes), encoding="utf-8-sig")
    except UnicodeDecodeError:
        orders = pd.read_csv(io.BytesIO(order_bytes), encoding="cp1252")
    returns = pd.read_csv(io.BytesIO(return_bytes), encoding="utf-8-sig")
    validate(customers, ["Customer ID", "Segment", "Region"], "Customers")
    validate(orders, ["Order ID", "Customer ID", "Order Date", "Category", "Sales", "Profit", "Quantity"], "Orders")
    validate(returns, ["Order ID", "Returned"], "Returns")
    for col in ("Sales", "Profit", "Quantity"):
        orders[col] = pd.to_numeric(orders[col], errors="coerce")
    orders["Order Date Parsed"] = pd.to_datetime(orders["Order Date"], errors="coerce", format="%m/%d/%Y")
    if "Ship Date" in orders:
        orders["Ship Date Parsed"] = pd.to_datetime(orders["Ship Date"], errors="coerce", format="%m/%d/%Y")
    # One customer may have many rows/regions; only take segment if unique.
    segment_counts = customers.groupby("Customer ID")["Segment"].nunique(dropna=True)
    valid_segment_ids = segment_counts[segment_counts == 1].index
    segment_lookup = (customers[customers["Customer ID"].isin(valid_segment_ids)]
                      .drop_duplicates("Customer ID")[["Customer ID", "Segment"]])
    region_counts = customers.groupby("Customer ID")["Region"].nunique(dropna=True)
    valid_region_ids = region_counts[region_counts == 1].index
    region_lookup = (customers[customers["Customer ID"].isin(valid_region_ids)]
                     .drop_duplicates("Customer ID")[["Customer ID", "Region"]])
    # Returns is order-level, never join directly with duplicate rows.
    returned_ids = set(returns.loc[returns["Returned"].astype(str).str.lower().eq("yes"), "Order ID"])
    orders = orders.merge(segment_lookup, on="Customer ID", how="left", validate="many_to_one")
    orders = orders.merge(region_lookup, on="Customer ID", how="left", validate="many_to_one")
    orders["Returned"] = orders["Order ID"].isin(returned_ids)
    return customers, orders, returns, int((region_counts > 1).sum()), int((segment_counts > 1).sum())


def currency(n):
    return f"${n:,.0f}"


def filtered_orders(orders):
    subset = orders.copy()
    valid_dates = subset["Order Date Parsed"].dropna()
    st.sidebar.header("Filters")
    if valid_dates.empty:
        st.warning("No valid order dates were found.")
        st.stop()
    lo, hi = valid_dates.min().date(), valid_dates.max().date()
    selected = st.sidebar.date_input("Order date range", value=(lo, hi), min_value=lo, max_value=hi)
    if len(selected) != 2:
        st.info("Select both a start and end date.")
        st.stop()
    start, end = selected
    cats = sorted(subset["Category"].dropna().unique().tolist())
    selected_cats = st.sidebar.multiselect("Product categories", cats, default=cats)
    segments = sorted(subset["Segment"].dropna().unique().tolist())
    selected_segments = st.sidebar.multiselect("Customer segments", segments, default=segments)
    subset = subset.loc[
        subset["Order Date Parsed"].between(pd.Timestamp(start), pd.Timestamp(end))
        & subset["Category"].isin(selected_cats)
        & subset["Segment"].isin(selected_segments)
    ].copy()
    st.sidebar.caption("Filters apply to every chart and metric, including returns and regional coverage.")
    return subset


def monthly_chart(df):
    monthly = (df.assign(Month=df["Order Date Parsed"].dt.to_period("M").dt.to_timestamp())
               .groupby(["Month", "Category"], as_index=False)["Sales"].sum())
    fig = px.line(monthly, x="Month", y="Sales", color="Category", markers=True,
                  color_discrete_map=COLORS, labels={"Sales": "Sales (USD)", "Month": "Month"})
    fig.update_layout(hovermode="x unified", legend_title_text="Category", height=470)
    if not monthly.empty:
        for year in range(int(monthly.Month.dt.year.min()), int(monthly.Month.dt.year.max()) + 1):
            fig.add_vrect(x0=f"{year}-10-01", x1=f"{year + 1}-01-01", fillcolor="#e8b85b",
                          opacity=0.17, layer="below", line_width=0,
                          annotation_text="Q4", annotation_position="top left")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Visualization: multi-series line chart. Gold shading = October–December (Q4).")


def returns_chart(df):
    # Each Order ID is counted once per category (multi-category orders may appear in several groups).
    order_cat = df[["Order ID", "Category", "Returned"]].drop_duplicates(["Order ID", "Category"])
    stats = (order_cat.groupby("Category", as_index=False)
             .agg(Orders=("Order ID", "nunique"), Returned_orders=("Returned", "sum")))
    stats["Return rate (%)"] = stats["Returned_orders"].div(stats["Orders"]).mul(100)
    fig = px.bar(stats.sort_values("Return rate (%)"), x="Return rate (%)", y="Category",
                 orientation="h", color="Category", color_discrete_map=COLORS,
                 hover_data=["Orders", "Returned_orders"], text="Return rate (%)")
    fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
    fig.update_layout(showlegend=False, height=350, xaxis_title="Returned orders / category orders (%)")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Visualization: horizontal bar chart. Rate is based on distinct Order IDs per category, not order lines.")
    st.dataframe(stats, hide_index=True, use_container_width=True)


st.title("Customer & Sales Analytics Dashboard")
st.caption("Explore sales, profitability, returns, customer segments and data quality.")
st.sidebar.subheader("Data sources")
st.sidebar.caption("Upload all three CSVs, or leave blank to use the bundled example data.")
uploads = {name: st.sidebar.file_uploader(f"{name.title()} CSV", type="csv", key=name)
           for name in ("customers", "orders", "returns")}
try:
    raw = {name: uploads[name].getvalue() if uploads[name] is not None else (BASE / "data" / f"{name}.csv").read_bytes()
           for name in uploads}
    customers, orders, returns, multi_regions, multi_segments = prepare(raw["customers"], raw["orders"], raw["returns"])
except Exception as exc:
    st.error(f"Unable to load data: {exc}")
    st.stop()

view = filtered_orders(orders)
if view.empty:
    st.warning("No records match the selected filters.")
    st.stop()

pages = st.tabs(["Overview", "Sales trends", "Profitability", "Returns", "Geography", "Data explorer & quality"])
with pages[0]:
    st.subheader("Executive overview")
    order_summary = view.drop_duplicates("Order ID")
    metrics = [
        ("Sales", currency(view.Sales.sum())),
        ("Profit", currency(view.Profit.sum())),
        ("Orders", f"{view['Order ID'].nunique():,}"),
        ("Customers", f"{view['Customer ID'].nunique():,}"),
        ("Order return rate", f"{order_summary.Returned.mean():.1%}"),
    ]
    for col, (label, value) in zip(st.columns(5), metrics):
        col.metric(label, value)
    st.info("Returns are tracked at the order level. Sales and profit are summed at the order-line level. Returned sales are not automatically deducted from revenue.")
    st.subheader("Sales by category")
    summary = view.groupby("Category", as_index=False)[["Sales", "Profit"]].sum()
    st.plotly_chart(px.bar(summary, x="Category", y="Sales", color="Category", color_discrete_map=COLORS), use_container_width=True)

with pages[1]:
    st.subheader("Monthly sales by category")
    monthly_chart(view)
    st.subheader("Monthly total sales")
    total = (view.assign(Month=view["Order Date Parsed"].dt.to_period("M").dt.to_timestamp())
             .groupby("Month", as_index=False)["Sales"].sum())
    st.plotly_chart(px.line(total, x="Month", y="Sales", markers=True, labels={"Sales": "Sales (USD)"}), use_container_width=True)
    st.caption("Visualization: line chart.")

with pages[2]:
    st.subheader("Profit distribution by product category")
    profits = view.groupby("Category", as_index=False)["Profit"].sum()
    if (profits["Profit"] >= 0).all() and profits.Profit.sum() > 0:
        st.plotly_chart(px.pie(profits, names="Category", values="Profit", color="Category",
                               color_discrete_map=COLORS, hole=0), use_container_width=True)
        st.caption("Visualization: pie chart. Pie slices represent the share of nonnegative category profit totals.")
    else:
        st.warning("A pie chart is misleading when category profits are negative or total profit is nonpositive; showing a bar chart instead.")
        st.plotly_chart(px.bar(profits, x="Category", y="Profit", color="Category", color_discrete_map=COLORS), use_container_width=True)
    st.subheader("Profit by customer segment")
    segments = view.groupby("Segment", dropna=False, as_index=False)["Profit"].sum().sort_values("Profit")
    st.plotly_chart(px.bar(segments, x="Profit", y="Segment", orientation="h", text_auto=".2s",
                            labels={"Profit": "Total profit (USD)"}), use_container_width=True)
    st.caption("Visualization: horizontal bar chart.")

with pages[3]:
    st.subheader("Return rate by category")
    returns_chart(view)
    st.caption("Filtering a date range selects orders by order date; return status comes from the supplied Returns file.")

with pages[4]:
    st.subheader("Sales by geographic region")
    known = view[view.Region.notna()]
    coverage = len(known) / len(view)
    st.warning(f"Customer IDs with conflicting region assignments: {multi_regions:,} of {customers['Customer ID'].nunique():,}. "
               f"Only {coverage:.1%} of filtered order lines have an unambiguous customer region. "
               "The chart below covers only those lines; it is NOT total regional sales.")
    if not known.empty:
        regional = known.groupby("Region", as_index=False)["Sales"].sum().sort_values("Sales")
        st.plotly_chart(px.bar(regional, x="Sales", y="Region", orientation="h", text_auto=".3s"), use_container_width=True)
        st.caption("Visualization: horizontal bar chart — partial coverage only. Provide an order-level Region or shipping address for complete results.")
    else:
        st.info("No order lines have an unambiguous region under the current filters.")

with pages[5]:
    st.subheader("Data quality")
    st.dataframe(pd.DataFrame([
        {"Check": "Unmatched order lines to customer IDs", "Value": int((~orders['Customer ID'].isin(customers['Customer ID'])).sum())},
        {"Check": "Customer IDs with conflicting regions", "Value": multi_regions},
        {"Check": "Customer IDs with conflicting segments", "Value": multi_segments},
        {"Check": "Invalid order dates", "Value": int(orders['Order Date Parsed'].isna().sum())},
        {"Check": "Duplicated Row IDs", "Value": int(orders['Row ID'].duplicated().sum()) if 'Row ID' in orders else None},
        {"Check": "Return IDs not found in orders", "Value": int((~returns['Order ID'].isin(orders['Order ID'])).sum())},
    ]), hide_index=True, use_container_width=True)
    st.subheader("Browse data")
    choice = st.selectbox("Dataset", ["Filtered joined orders", "Customers (raw)", "Orders (raw + parsed dates)", "Returns (raw)"])
    selected_df = {"Filtered joined orders": view, "Customers (raw)": customers,
                   "Orders (raw + parsed dates)": orders, "Returns (raw)": returns}[choice]
    st.write(f"{len(selected_df):,} rows × {len(selected_df.columns):,} columns")
    st.dataframe(selected_df.head(1000), use_container_width=True)
    st.download_button("Download selected dataset (CSV)", data=selected_df.to_csv(index=False).encode("utf-8-sig"),
                       file_name="dashboard_export.csv", mime="text/csv")
    st.caption("Preview shows up to 1,000 rows; CSV export includes all selected rows.")
