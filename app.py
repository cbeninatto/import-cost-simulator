import streamlit as st
import pandas as pd

from calculations import ShipmentConfig, compute_landed_cost
from ncm_loader import load_ncm_tec_table

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

# Carrega tabela NCM + TEC (II) uma única vez
try:
    NCM_TEC_TABLE = load_ncm_tec_table()
except Exception as e:
    NCM_TEC_TABLE = None
    # Em produção você pode querer logar isso:
    # st.sidebar.error(f"Erro ao carregar tabela de NCM/TEC: {e}")

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

# Começamos com uma tabela vazia, para o usuário adicionar as linhas necessárias
default_items = pd.DataFrame(
    columns=[
        "NCM",
        "Description",
        "Quantity",
        "FOB_Unit_USD",
        "Gross_Weight_kg",
        "II_rate",
        "IPI_rate",
        "PIS_rate",
        "COFINS_rate",
        "ICMS_rate",
    ]
)

items_df = st.data_editor(
    default_items,
    num_rows="dynamic",
    use_container_width=True,
    key="items_editor",
    column_config={
        "NCM": st.column_config.TextColumn(
            "NCM",
            help="Código NCM da mercadoria (8 dígitos).",
        ),
        "Description": st.column_config.TextColumn(
            "Descrição do produto",
            help="Descrição para identificação interna na simulação.",
        ),
        "Quantity": st.column_config.NumberColumn(
            "Quantidade",
            help="Quantidade total desse item no embarque.",
            min_value=0,
            step=1,
            format="%.0f",
        ),
        "FOB_Unit_USD": st.column_config.NumberColumn(
            "FOB unitário (USD)",
            help="Preço FOB unitário em dólares.",
            min_value=0.0,
            step=0.01,
            format="%.4f",
        ),
        "Gross_Weight_kg": st.column_config.NumberColumn(
            "Peso bruto por unidade (kg)",
            help="Opcional, usado se futuramente a alocação for por peso.",
            min_value=0.0,
            step=0.01,
            format="%.3f",
        ),
        "II_rate": st.column_config.NumberColumn(
            "Alíquota II",
            help="Alíquota de Imposto de Importação (ex: 0,35 = 35%).",
            min_value=0.0,
            max_value=1.0,
            step=0.01,
            format="%.4f",
        ),
        "IPI_rate": st.column_config.NumberColumn(
            "Alíquota IPI",
            help="Alíquota de IPI (ex: 0,065 = 6,5%).",
            min_value=0.0,
            max_value=1.0,
            step=0.01,
            format="%.4f",
        ),
        "PIS_rate": st.column_config.NumberColumn(
            "Alíquota PIS-Importação",
            help="Alíquota de PIS-Importação (ex: 0,021 = 2,1%).",
            min_value=0.0,
            max_value=1.0,
            step=0.001,
            format="%.4f",
        ),
        "COFINS_rate": st.column_config.NumberColumn(
            "Alíquota COFINS-Importação",
            help="Alíquota de COFINS-Importação (ex: 0,0965 = 9,65%).",
            min_value=0.0,
            max_value=1.0,
            step=0.001,
            format="%.4f",
        ),
        "ICMS_rate": st.column_config.NumberColumn(
            "Alíquota ICMS específica",
            help=(
                "Opcional. Se deixar em branco ou 0, será usada a alíquota de ICMS "
                "informada na barra lateral."
            ),
            min_value=0.0,
            max_value=1.0,
            step=0.01,
            format="%.4f",
        ),
    },
)

st.caption(
    "Clique em **+** para adicionar novas linhas. "
    "Preencha **NCM**, **Descrição**, **Quantidade**, **FOB unitário (USD)** e as alíquotas de "
    "**II / IPI / PIS / COFINS** conforme o enquadramento fiscal do produto. "
    "Se deixar **Alíquota ICMS específica = 0**, será usada a alíquota de ICMS informada na barra lateral."
)

# =========================
# BOTÃO CALCULAR
# =========================

if st.button("Calcular custo de importação"):
    # Remove linhas completamente vazias (sem NCM e sem quantidade)
    clean_df = items_df.copy()
    clean_df = clean_df[
        ~(clean_df["NCM"].isna() & clean_df["Quantity"].isna())
    ]

    if clean_df.empty:
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

        per_item, summary = compute_landed_cost(clean_df, cfg)

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

                # --- Auto-preenchimento da alíquota de II a partir da tabela NCM/TEC ---
        if NCM_TEC_TABLE is not None and not clean_df.empty:
            # Garante que NCM está em formato string de 8 dígitos
            clean_df["NCM8"] = clean_df["NCM"].astype(str).str.replace(".", "", regex=False).str.zfill(8)

            # Junta com tabela de II por NCM
            clean_df = clean_df.merge(
                NCM_TEC_TABLE[["NCM8", "II_rate"]],
                on="NCM8",
                how="left",
                suffixes=("", "_from_tec"),
            )

            # Se II_rate estiver vazio/0, usa o valor da TEC
            clean_df["II_rate"] = clean_df["II_rate"].fillna(0.0)
            clean_df["II_rate_from_tec"] = clean_df["II_rate_from_tec"].fillna(0.0)

            mask_use_tec = clean_df["II_rate"] == 0.0
            clean_df.loc[mask_use_tec, "II_rate"] = clean_df.loc[mask_use_tec, "II_rate_from_tec"]

            # Remove coluna auxiliar
            clean_df.drop(columns=["NCM8", "II_rate_from_tec"], inplace=True)


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
