"""Interactive customer, order, and returns dashboard. Run: streamlit run app.py"""
from pathlib import Path
import io
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Customer & Sales Analytics", page_icon="📊", layout="wide")
BASE = Path(__file__).resolve().parent
COLORS = {"Furniture": "#D49C35", "Office Supplies": "#238D87", "Technology": "#4776C5"}
UNKNOWN_REGION = "Unknown / ambiguous"

DESCRIPTIONS = {
    "Row ID": "Identifier for an order line", "Order ID": "Identifier for a customer order",
    "Order Date": "Date the order was placed", "Ship Date": "Date the order was shipped",
    "Ship Mode": "Shipping service level", "Customer ID": "Customer identifier",
    "Product ID": "Product identifier", "Category": "Main product category",
    "Sub-Category": "Product subcategory", "Product Name": "Name of purchased product",
    "Sales": "Revenue for this order line", "Quantity": "Number of units purchased",
    "Discount": "Discount proportion applied to line", "Profit": "Profit or loss on this order line",
    "Segment": "Customer market segment", "Country": "Customer country",
    "City": "Customer city", "State": "Customer state",
    "Postal Code": "Customer postal code (identifier)",
    "Region": "Customer geographic region; missing if customer has conflicting regions",
    "Returned": "Whether the order appears in the Returns file",
    "Order Date Parsed": "Parsed order date used for filtering and charts",
    "Ship Date Parsed": "Parsed shipping date",
}


def csv_from_bytes(data):
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            df = pd.read_csv(io.BytesIO(data), encoding=encoding, dtype={"Postal Code": "string"})
            df.columns = df.columns.str.replace("\ufeff", "", regex=False).str.replace("ï»¿", "", regex=False).str.strip()
            return df
        except UnicodeDecodeError:
            pass
    raise ValueError("CSV must be encoded in UTF-8 or Windows-1252")


def require_columns(df, columns, label):
    absent = sorted(set(columns) - set(df.columns))
    if absent:
        raise ValueError(f"{label} is missing required columns: {', '.join(absent)}")


@st.cache_data(show_spinner=False)
def prepare(customer_bytes, order_bytes, return_bytes):
    customers = csv_from_bytes(customer_bytes)
    orders_raw = csv_from_bytes(order_bytes)
    returns = csv_from_bytes(return_bytes)
    require_columns(customers, ["Customer ID", "Segment", "Region"], "Customers")
    require_columns(orders_raw, ["Order ID", "Customer ID", "Order Date", "Category", "Sales", "Profit", "Quantity"], "Orders")
    require_columns(returns, ["Order ID", "Returned"], "Returns")
    orders = orders_raw.copy()
    for column in ("Sales", "Profit", "Quantity", "Discount"):
        if column in orders:
            orders[column] = pd.to_numeric(orders[column], errors="coerce")
    orders["Order Date Parsed"] = pd.to_datetime(orders["Order Date"], format="%m/%d/%Y", errors="coerce")
    if "Ship Date" in orders:
        orders["Ship Date Parsed"] = pd.to_datetime(orders["Ship Date"], format="%m/%d/%Y", errors="coerce")

    # Do not many-to-many join the repeated customer records. Preserve only
    # attributes that have one distinct, non-null value per customer ID.
    lookups = []
    ambiguous = {}
    for column in ("Segment", "Region"):
        counts = customers.groupby("Customer ID")[column].nunique(dropna=True)
        ambiguous[column] = int((counts > 1).sum())
        unique_ids = counts[counts == 1].index
        lookup = (customers[customers["Customer ID"].isin(unique_ids)]
                  .drop_duplicates("Customer ID")[["Customer ID", column]])
        lookups.append(lookup)
    for lookup in lookups:
        orders = orders.merge(lookup, on="Customer ID", how="left", validate="many_to_one")
    returned_ids = set(returns.loc[returns["Returned"].astype(str).str.strip().str.lower().eq("yes"), "Order ID"])
    orders["Returned"] = orders["Order ID"].isin(returned_ids)
    quality = {
        "Customer IDs with conflicting regions": ambiguous["Region"],
        "Customer IDs with conflicting segments": ambiguous["Segment"],
        "Unmatched order lines to customer IDs": int((~orders["Customer ID"].isin(customers["Customer ID"])).sum()),
        "Invalid order dates": int(orders["Order Date Parsed"].isna().sum()),
        "Duplicate Row IDs": int(orders["Row ID"].duplicated().sum()) if "Row ID" in orders else None,
        "Return IDs missing from Orders": int((~returns["Order ID"].isin(orders["Order ID"])).sum()),
    }
    return customers, orders_raw, returns, orders, quality


def money(value):
    return f"${value:,.0f}"


def selected_label(selected, all_values):
    if not selected:
        return "None"
    if set(selected) == set(all_values):
        return "All"
    return ", ".join(selected)


def filter_data(orders):
    st.sidebar.header("Dashboard filters")
    valid_dates = orders["Order Date Parsed"].dropna()
    if valid_dates.empty:
        st.error("There are no valid order dates to filter.")
        st.stop()
    start_limit, end_limit = valid_dates.min().date(), valid_dates.max().date()
    date_range = st.sidebar.date_input("Order date range", value=(start_limit, end_limit),
                                       min_value=start_limit, max_value=end_limit)
    if len(date_range) != 2:
        st.info("Select both the start and end date in the sidebar.")
        st.stop()
    categories = sorted(orders["Category"].dropna().astype(str).unique().tolist())
    segments = sorted(orders["Segment"].dropna().astype(str).unique().tolist())
    regions = sorted(orders["Region"].dropna().astype(str).unique().tolist()) + [UNKNOWN_REGION]
    chosen_categories = st.sidebar.multiselect("Product categories", categories, default=categories)
    chosen_segments = st.sidebar.multiselect("Customer segments", segments, default=segments)
    chosen_regions = st.sidebar.multiselect("Customer regions", regions, default=regions,
                                           help="Unknown / ambiguous includes orders whose customer ID maps to multiple regions or has no region.")
    region_values = orders["Region"].fillna(UNKNOWN_REGION)
    start, end = date_range
    mask = (orders["Order Date Parsed"].between(pd.Timestamp(start), pd.Timestamp(end))
            & orders["Category"].isin(chosen_categories)
            & orders["Segment"].isin(chosen_segments)
            & region_values.isin(chosen_regions))
    selection = {"Date": f"{start} to {end}",
                 "Segments": selected_label(chosen_segments, segments),
                 "Regions": selected_label(chosen_regions, regions),
                 "Categories": selected_label(chosen_categories, categories)}
    st.sidebar.caption("All selections are combined (AND) and apply to charts, KPIs, and exports.")
    return orders.loc[mask].copy(), selection


def show_filters(selection):
    st.caption("**Active filters** · " + "  |  ".join(f"**{key}:** {value}" for key, value in selection.items()))


def monthly_sales(df, selection):
    st.subheader("Monthly sales by product category")
    show_filters(selection)
    if df.empty:
        st.info("No matching orders. Change the filters to see the chart.")
        return
    monthly = (df.assign(Month=df["Order Date Parsed"].dt.to_period("M").dt.to_timestamp())
               .groupby(["Month", "Category"], as_index=False)["Sales"].sum())
    fig = px.line(monthly, x="Month", y="Sales", color="Category", markers=True,
                  color_discrete_map=COLORS, labels={"Month": "Order month", "Sales": "Sales (USD)"})
    fig.update_layout(height=480, hovermode="x unified", legend_title_text="Product category")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Visualization type: multi-series line chart. No Q4 background highlighting.")


def category_return_rate(df):
    st.subheader("Return rate by product category")
    if df.empty:
        st.info("No matching records.")
        return
    by_order_cat = df[["Order ID", "Category", "Returned"]].drop_duplicates(["Order ID", "Category"])
    summary = (by_order_cat.groupby("Category", as_index=False)
               .agg(Orders=("Order ID", "nunique"), Returned_orders=("Returned", "sum")))
    summary["Return rate (%)"] = 100 * summary["Returned_orders"] / summary["Orders"]
    fig = px.bar(summary.sort_values("Return rate (%)"), x="Return rate (%)", y="Category",
                 orientation="h", color="Category", color_discrete_map=COLORS,
                 text="Return rate (%)", hover_data=["Orders", "Returned_orders"])
    fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
    fig.update_layout(showlegend=False, height=350)
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Visualization type: horizontal bar chart. Distinct returned orders / distinct orders within each category. A multi-category order can count in multiple categories.")
    st.dataframe(summary, hide_index=True, use_container_width=True)


def data_dictionary(df):
    def friendly_type(name, series):
        if name in ("Order Date", "Ship Date", "Order Date Parsed", "Ship Date Parsed"):
            return "Date" if "Parsed" in name else "Text (date string)"
        if name in ("Returned",):
            return "Boolean" if pd.api.types.is_bool_dtype(series) else "Categorical"
        if name in ("Row ID", "Order ID", "Customer ID", "Product ID", "Postal Code"):
            return "Identifier"
        if pd.api.types.is_numeric_dtype(series):
            return "Numeric (integer)" if pd.api.types.is_integer_dtype(series) else "Numeric (decimal)"
        if pd.api.types.is_datetime64_any_dtype(series):
            return "Date"
        return "Categorical / text"
    return pd.DataFrame([
        {"Column": col, "Data type": friendly_type(col, df[col]),
         "Description": DESCRIPTIONS.get(col, "Source data field"),
         "Missing values": int(df[col].isna().sum()),
         "Unique values": int(df[col].nunique(dropna=True))}
        for col in df.columns
    ])


def custom_viz(df):
    st.subheader("Build your own visualization")
    st.caption("Choose a chart type and variables from the filtered joined orders. Each plot updates with the dashboard filters.")
    if df.empty:
        st.info("No matching data to visualize.")
        return
    chart = st.selectbox("Visualization type", ["Scatterplot", "Bar chart", "Line chart", "Histogram", "Box plot"])
    numeric = [c for c in df.select_dtypes(include="number").columns if c not in ("Row ID",)]
    dimensions = [c for c in ["Category", "Sub-Category", "Segment", "Region", "Ship Mode", "Customer ID", "Product Name", "Order ID"] if c in df]
    time_cols = [c for c in ["Order Date Parsed", "Ship Date Parsed"] if c in df]
    options = numeric + dimensions + time_cols
    if not numeric:
        st.warning("No numeric fields available for visualization.")
        return
    color_options = ["None"] + [c for c in ["Category", "Segment", "Region", "Ship Mode", "Sub-Category"] if c in df]
    try:
        if chart == "Scatterplot":
            x = st.selectbox("X-axis (numeric)", numeric, index=numeric.index("Sales") if "Sales" in numeric else 0)
            y = st.selectbox("Y-axis (numeric)", numeric, index=numeric.index("Profit") if "Profit" in numeric else 0)
            color = st.selectbox("Color by", color_options)
            fig = px.scatter(df, x=x, y=y, color=None if color == "None" else color,
                             opacity=0.65, hover_data=["Order ID"] if "Order ID" in df else None,
                             color_discrete_map=COLORS)
        elif chart == "Histogram":
            x = st.selectbox("Numeric variable", numeric, index=numeric.index("Sales") if "Sales" in numeric else 0)
            color = st.selectbox("Color by", color_options)
            bins = st.slider("Number of bins", 5, 100, 30)
            fig = px.histogram(df, x=x, color=None if color == "None" else color,
                               nbins=bins, color_discrete_map=COLORS)
        elif chart == "Box plot":
            x = st.selectbox("Group by", dimensions, index=dimensions.index("Category") if "Category" in dimensions else 0)
            y = st.selectbox("Numeric variable", numeric, index=numeric.index("Profit") if "Profit" in numeric else 0)
            fig = px.box(df, x=x, y=y, color=x, color_discrete_map=COLORS)
        else:
            x_options = dimensions + time_cols
            x = st.selectbox("Group / X-axis", x_options, index=x_options.index("Category") if "Category" in x_options else 0)
            y = st.selectbox("Numeric variable", numeric, index=numeric.index("Sales") if "Sales" in numeric else 0)
            agg = st.selectbox("Aggregation", ["Sum", "Mean", "Median", "Count"])
            color = st.selectbox("Split by", color_options)
            split = None if color == "None" or color == x else color
            temp = df[[x, y] + ([split] if split else [])].copy()
            if x in time_cols:
                temp[x] = temp[x].dt.to_period("M").dt.to_timestamp()
            keys = [x] + ([split] if split else [])
            group = temp.groupby(keys, dropna=False, as_index=False)[y]
            plotted = {"Sum": group.sum, "Mean": group.mean, "Median": group.median,
                       "Count": group.count}[agg]()
            if plotted[x].nunique() > 50:
                st.warning("More than 50 X-axis groups; consider choosing a lower-cardinality variable.")
            kwargs = dict(data_frame=plotted, x=x, y=y, color=split, color_discrete_map=COLORS)
            fig = px.bar(**kwargs) if chart == "Bar chart" else px.line(**kwargs, markers=True)
            fig.update_layout(yaxis_title=f"{agg} of {y}")
        fig.update_layout(height=500)
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"Visualization type: {chart}.")
    except (ValueError, TypeError) as exc:
        st.warning(f"Unable to render this variable combination: {exc}")


st.title("Customer & Sales Analytics Dashboard")
st.caption("Interactive sales, profitability, returns, regional coverage, and data exploration")
st.sidebar.subheader("Data sources")
st.sidebar.caption("Upload replacement CSVs or use the bundled example data.")
uploads = {name: st.sidebar.file_uploader(f"{name.title()} CSV", type="csv", key=f"upload_{name}")
           for name in ("customers", "orders", "returns")}
try:
    sources = {name: uploads[name].getvalue() if uploads[name] is not None
               else (BASE / "data" / f"{name}.csv").read_bytes() for name in uploads}
    customers, raw_orders, returns, orders, quality = prepare(sources["customers"], sources["orders"], sources["returns"])
except (ValueError, OSError, pd.errors.ParserError) as exc:
    st.error(f"Could not load the source files: {exc}")
    st.stop()

view, active_filters = filter_data(orders)
tabs = st.tabs(["Overview", "Sales trends", "Profitability", "Returns", "Geography", "Explore & export", "Custom charts"])

with tabs[0]:
    st.subheader("Executive overview")
    show_filters(active_filters)
    if view.empty:
        st.warning("No order lines match the filters. Adjust selections in the sidebar.")
    else:
        # Vertical metric list: easier to read on narrow screens.
        order_level = view.drop_duplicates("Order ID")
        metrics = [
            ("Total sales", money(view["Sales"].sum())),
            ("Total profit", money(view["Profit"].sum())),
            ("Distinct orders", f"{view['Order ID'].nunique():,}"),
            ("Distinct customers", f"{view['Customer ID'].nunique():,}"),
            ("Order return rate", f"{order_level['Returned'].mean():.1%}"),
        ]
        for label, value in metrics:
            st.metric(label, value)
        st.info("Order-level returns are not automatically deducted from sales or profit. Filtering categories may select only part of a multi-category order.")
        category = view.groupby("Category", as_index=False)["Sales"].sum()
        st.plotly_chart(px.bar(category, x="Category", y="Sales", color="Category",
                               color_discrete_map=COLORS), use_container_width=True)
        st.caption("Visualization type: bar chart — sales by category.")

with tabs[1]:
    monthly_sales(view, active_filters)
    if not view.empty:
        st.subheader("Total monthly sales")
        monthly = (view.assign(Month=view["Order Date Parsed"].dt.to_period("M").dt.to_timestamp())
                   .groupby("Month", as_index=False)["Sales"].sum())
        st.plotly_chart(px.line(monthly, x="Month", y="Sales", markers=True), use_container_width=True)
        st.caption("Visualization type: line chart.")

with tabs[2]:
    if not view.empty:
        st.subheader("Profit by product category")
        profit = view.groupby("Category", as_index=False)["Profit"].sum()
        if profit["Profit"].ge(0).all() and profit["Profit"].sum() > 0:
            st.plotly_chart(px.pie(profit, names="Category", values="Profit", color="Category",
                                   color_discrete_map=COLORS), use_container_width=True)
            st.caption("Visualization type: pie chart.")
        else:
            st.warning("Some category profits are negative; a bar chart is more appropriate than a pie chart.")
            st.plotly_chart(px.bar(profit, x="Category", y="Profit", color="Category",
                                   color_discrete_map=COLORS), use_container_width=True)
        st.subheader("Profit by customer segment")
        segments = view.groupby("Segment", as_index=False)["Profit"].sum().sort_values("Profit")
        st.plotly_chart(px.bar(segments, x="Profit", y="Segment", orientation="h"), use_container_width=True)
        st.caption("Visualization type: horizontal bar chart.")
    else:
        st.info("No matching data.")

with tabs[3]:
    category_return_rate(view)

with tabs[4]:
    st.subheader("Sales by region (known assignments only)")
    st.warning(f"{quality['Customer IDs with conflicting regions']:,} customer IDs have conflicting region assignments. "
               "Unknown / ambiguous region sales cannot be allocated reliably.")
    known = view[view["Region"].notna()]
    st.caption(f"Known-region coverage: {len(known):,} of {len(view):,} filtered order lines "
               f"({len(known) / len(view):.1%} if records are selected)." if len(view) else "No matching records.")
    if not known.empty:
        summary = known.groupby("Region", as_index=False)["Sales"].sum()
        st.plotly_chart(px.bar(summary, x="Sales", y="Region", orientation="h"), use_container_width=True)
        st.caption("Visualization type: horizontal bar chart; partial coverage, not complete regional sales.")

with tabs[5]:
    st.subheader("Data sample and data dictionary")
    dataset = st.selectbox("Choose a dataset", ["Filtered joined orders", "Customers (raw)",
                                                  "Orders (raw)", "Returns (raw)"])
    chosen = {"Filtered joined orders": view, "Customers (raw)": customers,
              "Orders (raw)": raw_orders, "Returns (raw)": returns}[dataset]
    st.write(f"**{len(chosen):,} rows × {len(chosen.columns):,} columns**")
    st.markdown("**First five rows**")
    st.dataframe(chosen.head(5), use_container_width=True, hide_index=True)
    st.markdown("**Column summary**")
    st.dataframe(data_dictionary(chosen), use_container_width=True, hide_index=True)
    st.markdown("**Browse records**")
    st.dataframe(chosen.head(1000), use_container_width=True, hide_index=True)
    st.caption("Browse preview is limited to 1,000 rows; the download includes all selected records.")
    st.download_button("Export selected dataset as CSV", chosen.to_csv(index=False).encode("utf-8-sig"),
                       file_name="filtered_orders.csv" if dataset == "Filtered joined orders" else "data_export.csv",
                       mime="text/csv")
    st.subheader("Source data quality checks")
    st.dataframe(pd.DataFrame([{"Check": key, "Value": value} for key, value in quality.items()]),
                 use_container_width=True, hide_index=True)
    st.caption("The filter selections apply to the joined orders; raw tables remain unfiltered for source inspection.")

with tabs[6]:
    show_filters(active_filters)
    custom_viz(view)
