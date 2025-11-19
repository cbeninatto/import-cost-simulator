import streamlit as st
import pandas as pd

from calculations import ShipmentConfig, compute_landed_cost

st.set_page_config(
    page_title="Simulador de Custo de Importação",
    page_icon="📦",
    layout="wide"
)

st.title("📦 Simulador de Custo de Importação")

st.markdown(
    "Simule o **custo Brasil** de uma importação com vários produtos no mesmo embarque, "
    "incluindo impostos, frete internacional e transporte rodoviário."
)

# =========================
# SIDEBAR – CONFIGURAÇÕES
# =========================
with st.sidebar:
    st.header("Configurações do embarque")

    # Estado de destino
    estado_destino = st.selectbox(
        "Estado de destino (UF)",
        ["RS", "SC", "PR", "SP", "RJ", "MG", "ES", "BA", "GO", "DF", "Outros"],
        index=0,
    )

    # ICMS interno – por enquanto fixo 17% (padrão RS / vários estados)
    icms_aliq_padrao = 0.17
    icms_aliq = st.number_input(
        "Alíquota interna de ICMS",
        value=icms_aliq_padrao,
        min_value=0.0,
        max_value=1.0,
        step=0.01,
        format="%.2f",
    )

    # Equipamento (modo de embarque)
    equipamento = st.selectbox(
        "Equipamento (tipo de embarque)",
        ["FCL_20", "FCL_40", "LCL", "AIR"],
        index=2,
        help="Usado para definir se há AFRMM (marítimo) ou não (aéreo).",
    )

    # Câmbio
    cambio = st.number_input(
        "Câmbio USD → BRL",
        value=5.50,
        min_value=0.0,
        step=0.01,
        format="%.4f",
    )

    st.subheader("Custos principais")

    frete_usd = st.number_input(
        "Frete internacional (USD)",
        value=0.0,
        min_value=0.0,
        step=10.0,
    )

    transporte_rodoviario_brl = st.number_input(
        "Transporte rodoviário até o destino (R$)",
        value=0.0,
        min_value=0.0,
        step=50.0,
    )

    st.subheader("Regime tributário")

    regime_label = st.selectbox(
        "Regime tributário da empresa",
        ["Simples Nacional", "Lucro Presumido", "Lucro Real"],
        index=1,
    )

    regime_map = {
        "Simples Nacional": "simples",
        "Lucro Presumido": "presumido",
        "Lucro Real": "real",
    }
    regime = regime_map[regime_label]

    uso_label = st.selectbox(
        "Uso das mercadorias",
        ["Indústria", "Revenda"],
        index=1,
        help="Ambas as opções são tratadas como mercadorias para revenda/industrialização em termos de créditos.",
    )

    # Internamente, tratamos Indústria e Revenda como 'resale'
    purpose = "resale"

    st.subheader("Incoterm")

    incoterm = st.selectbox(
        "Incoterm",
        ["EXW", "FOB", "CIF"],
        index=0,
        help=(
            "Por enquanto, o Incoterm é usado apenas como informação na simulação. "
            "Os custos compartilhados (frete, seguro etc.) são alocados entre os itens "
            "proporcionalmente ao valor FOB."
        ),
    )

    # Por enquanto, mantemos a alocação sempre por valor FOB
    allocation_method = "FOB"

    st.caption(
        "Por padrão, o seguro internacional é calculado como **0,10% ad valorem** "
        "sobre o valor FOB total. AFRMM (8% sobre o frete marítimo) e Taxa Siscomex "
        "(R$ 154,23) são incluídos automaticamente na base do ICMS para embarques marítimos."
    )

# =========================
# TABELA DE ITENS
# =========================

st.subheader("Itens da simulação")

default_items = pd.DataFrame(
    [
        {
            "NCM": "4202.22.10",
            "Description": "Bolsa sintética exemplo",
            "Quantity": 1000,
            "FOB_Unit_USD": 2.50,
            "Gross_Weight_kg": 0.5,
            "II_rate": 0.35,
            "IPI_rate": 0.065,
            "PIS_rate": 0.021,
            "COFINS_rate": 0.0965,
            "ICMS_rate": 0.0,  # 0 = usa a alíquota ICMS da barra lateral
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
    "Preencha **NCM**, **Quantidade**, **FOB unitário (USD)** e as alíquotas de "
    "**II / IPI / PIS / COFINS**. "
    "Se deixar **ICMS_rate = 0**, será usada a alíquota de ICMS informada na barra lateral."
)

# =========================
# BOTÃO CALCULAR
# =========================

if st.button("Calcular custo de importação"):
    if items_df.empty:
        st.warning("Adicione pelo menos um item à simulação.")
    else:
        # AFRMM: 8% sobre o frete para marítimo; 0 para aéreo
        if equipamento.lower() in ["fcl_20", "fcl_40", "lcl"]:
            afrmm_pct = 0.08
        else:
            afrmm_pct = 0.0

        # Seguro: 0,10% ad valorem sobre o FOB total (cálculo feito em calculations.py)
        insurance_usd = 0.0
        insurance_pct = 0.001  # 0,1%

        # Encargos de origem e THC: por enquanto 0 na simulação base
        origin_charges_usd = 0.0
        thc_origin_usd = 0.0

        # Custos locais além do frete rodoviário: por enquanto 0 (podemos refinar depois)
        local_port_costs_brl = 0.0
        other_local_costs_brl = 0.0

        # Siscomex padrão
        siscomex_brl = 154.23

        cfg = ShipmentConfig(
            state_destination=estado_destino,
            mode=equipamento,
            fx_rate_usd_brl=cambio,
            freight_international_usd=frete_usd,
            insurance_usd=insurance_usd,
            insurance_pct=insurance_pct,
            origin_charges_usd=origin_charges_usd,
            thc_origin_usd=thc_origin_usd,
            afrmm_pct=afrmm_pct,
            siscomex_brl=siscomex_brl,
            local_port_costs_brl=local_port_costs_brl,
            trucking_brl=transporte_rodoviario_brl,
            other_local_costs_brl=other_local_costs_brl,
            regime=regime,
            purpose=purpose,
            icms_rate=icms_aliq,
            da_components=["afrmm", "siscomex"],
            va_components=["freight", "insurance", "origin_charges", "thc_origin"],
            allocation_method=allocation_method,
        )

        per_item, summary = compute_landed_cost(items_df, cfg)

        # =========================
        # RESULTADOS
        # =========================
        st.subheader("Resultados por item")

        cols_to_show = [
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

        display_df = per_item[cols_to_show].rename(
            columns={
                "Description": "Descrição",
                "Quantity": "Quantidade",
                "FOB_Total_BRL": "FOB total (R$)",
                "CIF_BRL": "Valor Aduaneiro / CIF (R$)",
                "II_BRL": "II (R$)",
                "IPI_BRL": "IPI (R$)",
                "PIS_BRL": "PIS-Importação (R$)",
                "COFINS_BRL": "COFINS-Importação (R$)",
                "ICMS_BRL": "ICMS (R$)",
                "net_tax_total": "Impostos líquidos (R$)",
                "Local_Non_DA_BRL": "Custos locais (R$)",
                "Truck_BRL": "Transporte rodoviário (R$)",
                "Landed_Cost_BRL": "Custo total por item (R$)",
                "Unit_Cost_BRL": "Custo unitário (R$)",
            }
        )

        st.dataframe(display_df, use_container_width=True)

        st.subheader("Resumo do embarque")

        col1, col2 = st.columns(2)
        with col1:
            st.metric("FOB total (R$)", f"{summary['FOB_total_BRL']:,.2f}")
            st.metric("Valor aduaneiro total (R$)", f"{summary['VA_total_BRL']:,.2f}")
            st.metric("Custo total landed (R$)", f"{summary['Landed_total_BRL']:,.2f}")
            st.metric(
                "Fator FOB → Custo Brasil",
                f"{summary['FOB_to_Brazil_factor']:.2f}x",
            )
        with col2:
            st.metric("Impostos pagos (R$)", f"{summary['Tax_paid_total_BRL']:,.2f}")
            st.metric("Créditos de impostos (R$)", f"{summary['Tax_credit_total_BRL']:,.2f}")
            st.metric("Custo líquido de impostos (R$)", f"{summary['Net_tax_total_BRL']:,.2f}")
            st.metric("Frete rodoviário total (R$)", f"{summary['Truck_total_BRL']:,.2f}")

        st.markdown(
            "⚠️ **Atenção:** esta é uma simulação simplificada, com regras padrão de base de cálculo e créditos "
            "por regime (Simples / Lucro Presumido / Lucro Real). "
            "Situações específicas podem exigir ajustes conforme orientação do contador e do despachante aduaneiro."
        )
