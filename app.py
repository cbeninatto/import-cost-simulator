import streamlit as st
import pandas as pd

from calculations import ShipmentConfig, compute_landed_cost

st.set_page_config(page_title="Import Cost Simulator", page_icon="📦", layout="wide")

st.title("📦 Import Cost Simulator (Brazil)")

st.markdown(
    "Simulate landed cost of imported goods to Brazil, including taxes and logistics, "
    "for multiple products in a single shipment."
)

with st.sidebar:
    st.header("Shipment configuration")

    state_destination = st.selectbox(
        "Destination state (ICMS internal rate)",
        ["RS", "SC", "PR", "SP", "RJ", "MG", "ES", "BA", "GO", "DF", "Other"],
        index=0,
    )
    icms_rate_default = 0.17
    icms_rate = st.number_input(
        "ICMS internal rate",
        value=icms_rate_default,
        min_value=0.0,
        max_value=1.0,
        step=0.01,
    )

    mode = st.selectbox("Mode", ["FCL_20", "FCL_40", "LCL", "AIR"], index=2)

    fx_rate = st.number_input(
        "USD → BRL exchange rate",
        value=5.50,
        min_value=0.0,
        step=0.01,
    )

    st.subheader("Shared international costs (USD)")
    freight_usd = st.number_input("Freight (USD)", value=0.0, min_value=0.0)
    insurance_usd = st.number_input("Insurance (USD, 0 to use %)", value=0.0, min_value=0.0)
    insurance_pct = st.number_input(
        "Insurance % (e.g. 0.001 = 0.1%)",
        value=0.0,
        min_value=0.0,
        step=0.0001,
        format="%.4f",
    )
    origin_charges_usd = st.number_input("Origin charges (USD)", value=0.0, min_value=0.0)
    thc_origin_usd = st.number_input("THC origin (USD)", value=0.0, min_value=0.0)

    st.subheader("DA and local costs (BRL)")
    afrmm_pct = st.number_input(
        "AFRMM % on freight (ocean only)",
        value=0.08,
        min_value=0.0,
        step=0.01,
    )
    siscomex_brl = st.number_input("Siscomex (BRL)", value=154.23, min_value=0.0)

    local_port_costs_brl = st.number_input(
        "Local port/airport costs (BRL)",
        value=0.0,
        min_value=0.0,
    )
    trucking_brl = st.number_input(
        "Road transport to destination (BRL)",
        value=0.0,
        min_value=0.0,
    )
    other_local_costs_brl = st.number_input(
        "Other local costs (BRL)",
        value=0.0,
        min_value=0.0,
    )

    st.subheader("Tax regime")
    regime = st.selectbox("Tax regime", ["simples", "presumido", "real"], index=1)
    purpose = st.selectbox("Use of goods", ["resale", "consumption"], index=0)

    st.subheader("Advanced")
    allocation_method = st.selectbox(
        "Allocation method for shared costs",
        ["FOB", "WEIGHT"],
        index=0,
    )

    da_components = st.multiselect(
        "DA components (enter ICMS base)",
        options=["afrmm", "siscomex"],
        default=["afrmm", "siscomex"],
    )

    st.markdown(
        "The calculator assumes **PIS/COFINS on VA** and "
        "**ICMS base = VA + II + IPI + PIS + COFINS + DA (por dentro)**."
    )

st.subheader("Items in shipment")

default_items = pd.DataFrame(
    [
        {
            "NCM": "4202.22.10",
            "Description": "Sample bag",
            "Quantity": 1000,
            "FOB_Unit_USD": 2.50,
            "Gross_Weight_kg": 0.5,
            "II_rate": 0.35,
            "IPI_rate": 0.065,
            "PIS_rate": 0.021,
            "COFINS_rate": 0.0965,
            "ICMS_rate": 0.0,  # 0 = use header ICMS rate
        }
    ]
)

items_df = st.data_editor(
    default_items,
    num_rows="dynamic",
    use_container_width=True,
    key="items_editor",
)

st.caption(
    "Fill NCM, quantity, FOB unit price and tax rates. "
    "Leave ICMS_rate = 0 to use the ICMS rate from the sidebar."
)

if st.button("Calculate"):
    if items_df.empty:
        st.warning("Please add at least one item.")
    else:
        cfg = ShipmentConfig(
            state_destination=state_destination,
            mode=mode,
            fx_rate_usd_brl=fx_rate,
            freight_international_usd=freight_usd,
            insurance_usd=insurance_usd,
            insurance_pct=insurance_pct,
            origin_charges_usd=origin_charges_usd,
            thc_origin_usd=thc_origin_usd,
            afrmm_pct=afrmm_pct,
            siscomex_brl=siscomex_brl,
            local_port_costs_brl=local_port_costs_brl,
            trucking_brl=trucking_brl,
            other_local_costs_brl=other_local_costs_brl,
            regime=regime,
            purpose=purpose,
            icms_rate=icms_rate,
            da_components=da_components,
            va_components=["freight", "insurance", "origin_charges", "thc_origin"],
            allocation_method=allocation_method,
        )

        per_item, summary = compute_landed_cost(items_df, cfg)

        st.subheader("Per-item results")
        st.dataframe(
            per_item[
                [
                    "NCM",
                    "Description",
                    "Quantity",
                    "FOB_Total_BRL",
                    "CIF_BRL",
                    "II_BRL",
                    "IPI_BRL",
                    "PIS_BRL",
                    "COFINS_BRL",
                    "ICMS_BRL",
                    "net_tax_total",
                    "Local_Non_DA_BRL",
                    "Truck_BRL",
                    "Landed_Cost_BRL",
                    "Unit_Cost_BRL",
                ]
            ],
            use_container_width=True,
        )

        st.subheader("Shipment summary")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("FOB total (BRL)", f"{summary['FOB_total_BRL']:,.2f}")
            st.metric("Landed total (BRL)", f"{summary['Landed_total_BRL']:,.2f}")
            st.metric("FOB → Brazil factor", f"{summary['FOB_to_Brazil_factor']:.2f}x")
        with col2:
            st.metric("Taxes paid (BRL)", f"{summary['Tax_paid_total_BRL']:,.2f}")
            st.metric("Tax credits (BRL)", f"{summary['Tax_credit_total_BRL']:,.2f}")
            st.metric("Net tax cost (BRL)", f"{summary['Net_tax_total_BRL']:,.2f}")

