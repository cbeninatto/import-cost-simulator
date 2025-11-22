import streamlit as st
import pandas as pd

from calculations import ShipmentConfig, compute_landed_cost
from ncm_loader import load_ncm_tec_table


# =========================
# Page config
# =========================
st.set_page_config(
    page_title="Simulador de Custo de Importação",
    page_icon="📦",
    layout="wide",
)

st.title("📦 Simulador de Custo de Importação")

st.markdown(
    "Simule o **custo Brasil** de uma importação com vários produtos no mesmo embarque, "
    "incluindo impostos, frete internacional e transporte rodoviário."
)


# =========================
# Load NCM / II / IPI table
# =========================
LOAD_ERROR = None
try:
    # This reads data/combined_taxes.csv via ncm_loader.py
    NCM_TABLE = load_ncm_tec_table()
except Exception as e:
    NCM_TABLE = None
    LOAD_ERROR = repr(e)


# =========================
# Session state for items
# =========================
if "items_df" not in st.session_state:
    st.session_state["items_df"] = pd.DataFrame(
        columns=[
            "NCM",
            "Description",
            "Quantity",
            "FOB_Unit_USD",
            "II_rate",
            "IPI_rate",
            "PIS_rate",
            "COFINS_rate",
            "ICMS_rate",
        ]
    )


def normalize_ncm_search(value: str):
    """
    Take user input for NCM (0000.00.00, 00000000 or partial),
    strip to digits and return the raw digit string for prefix search.
    """
    if not isinstance(value, str):
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return None
    return digits


# =========================
# PASSO 1 – CONFIGURAÇÕES DO EMBARQUE (SEM SIDEBAR)
# =========================
st.markdown("### Passo 1 – Configurações do embarque")

config_col1, config_col2 = st.columns(2)

with config_col1:
    # Estado de destino
    estado_destino = st.selectbox(
        "Estado de destino (UF)",
        ["RS", "SC", "PR", "SP", "RJ", "MG", "ES", "BA", "GO", "DF", "Outros"],
        index=0,
    )

    # ICMS interno – default por estado (ajustável)
    icms_map_default = {
        "RS": 0.17,
        "SC": 0.17,
        "PR": 0.18,
        "SP": 0.18,
        "RJ": 0.20,
        "MG": 0.18,
        "ES": 0.17,
        "BA": 0.18,
        "GO": 0.17,
        "DF": 0.18,
        "Outros": 0.18,
    }
    icms_aliq_padrao = icms_map_default.get(estado_destino, 0.18)

    icms_aliq = st.number_input(
        "Alíquota interna de ICMS",
        value=icms_aliq_padrao,
        min_value=0.0,
        max_value=1.0,
        step=0.01,
        format="%.2f",
        help="Alíquota interna de ICMS usada para todos os itens (por enquanto).",
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

with config_col2:
    st.markdown("#### Custos principais")

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

    st.markdown("#### Regime e uso")

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

    # Internamente, tratamos ambos como 'resale'
    purpose = "resale"

    st.markdown("#### Incoterm")

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

    allocation_method = "FOB"

st.caption(
    "Por padrão, o seguro internacional é calculado como **0,10% ad valorem** "
    "sobre o valor FOB total. AFRMM (8% sobre o frete marítimo) e Taxa Siscomex "
    "(R$ 154,23) são incluídos automaticamente na base do ICMS para embarques marítimos."
)


# =========================
# PASSO 2 – ITENS DA SIMULAÇÃO
# =========================
st.markdown("### Passo 2 – Itens da simulação")

st.subheader("Adicionar item à simulação")

if NCM_TABLE is None:
    st.error(
        "Não foi possível carregar a tabela de NCM/II/IPI. "
        "Verifique se o arquivo `data/combined_taxes.csv` está presente e com o layout correto."
    )
    if LOAD_ERROR:
        st.code(f"Detalhes técnicos:\n{LOAD_ERROR}", language="text")
else:
    if NCM_TABLE.empty:
        st.warning(
            "A tabela NCM/II/IPI foi carregada, mas está vazia. "
            "Provavelmente há um problema de layout em `combined_taxes.csv`."
        )

    with st.form("add_item_form"):
        col_a, col_b = st.columns(2)
        with col_a:
            descricao_livre = st.text_input(
                "Descrição do produto (livre)",
                help="Texto livre para identificar o produto (ex.: 'corrediça telescópica 450mm zincada').",
            )

        with col_b:
            ncm_input = st.text_input(
                "NCM (0000.00.00 ou 00000000)",
                help="Você pode digitar o NCM completo ou parcial; o sistema sugerirá opções.",
            )

        col_c, col_d = st.columns(2)
        with col_c:
            quantidade = st.number_input(
                "Quantidade",
                min_value=1,
                value=1,
                step=1,
            )
        with col_d:
            fob_unit = st.number_input(
                "FOB unitário (USD)",
                min_value=0.0,
                value=1.00,
                step=0.01,
                format="%.4f",
            )

        st.markdown("### Sugestões de NCM")

        matches = pd.DataFrame()

        # Busca por NCM (prefixo de dígitos)
        if ncm_input.strip():
            digits = normalize_ncm_search(ncm_input)
            if digits is not None and "digits" in NCM_TABLE.columns:
                matches = NCM_TABLE[NCM_TABLE["digits"].str.startswith(digits)].copy()

        # Ou busca por descrição
        elif descricao_livre.strip():
            tokens = [t for t in descricao_livre.lower().split() if t]
            df_search = NCM_TABLE.copy()
            if tokens:
                mask = pd.Series(True, index=df_search.index)
                for t in tokens:
                    mask &= df_search["Descricao"].str.lower().str.contains(t, na=False)
                matches = df_search[mask].copy()

        if not matches.empty:
            # sort by level (4-digit -> 5-digit -> 6-digit -> 8-digit) and code
            sort_cols = ["NCM_dotted"]
            if "digits_len" in matches.columns:
                sort_cols = ["digits_len", "NCM_dotted"]
            matches = matches.sort_values(sort_cols).head(100)
            option_indices = matches.index.tolist()

            selected_idx = st.selectbox(
                "Selecione o NCM sugerido",
                options=option_indices,
                format_func=lambda idx: (
                    f"{matches.loc[idx, 'NCM_dotted']}  {matches.loc[idx, 'Descricao']}"
                ),
            )
        else:
            selected_idx = None
            st.info(
                "Nenhum NCM sugerido ainda. "
                "Digite parte do NCM ou da descrição para buscar."
            )

        submitted = st.form_submit_button("➕ Adicionar item")

        if submitted:
            if selected_idx is None:
                st.error("Selecione um NCM sugerido antes de adicionar o item.")
            else:
                row = matches.loc[selected_idx]
                digits_len = int(row.get("digits_len", 0)) if "digits_len" in row else 0

                # Only allow adding final 8-digit NCMs (0000.00.00)
                if digits_len != 8:
                    st.error(
                        "Selecione um NCM de 8 dígitos (formato 0000.00.00) para adicionar o item."
                    )
                else:
                    descricao_final = descricao_livre.strip() or str(row["Descricao"])

                    ii_rate = row.get("II_rate", 0.0)
                    if pd.isna(ii_rate):
                        ii_rate = 0.0

                    ipi_rate = row.get("IPI_rate", 0.0)
                    if pd.isna(ipi_rate):
                        ipi_rate = 0.0

                    # PIS/COFINS padrão importação (pode ser refinado por NCM no futuro)
                    pis_rate = 0.021     # 2,1%
                    cofins_rate = 0.0965  # 9,65%

                    new_item = {
                        "NCM": row["NCM_dotted"],
                        "Description": descricao_final,
                        "Quantity": float(quantidade),
                        "FOB_Unit_USD": float(fob_unit),
                        "II_rate": float(ii_rate),
                        "IPI_rate": float(ipi_rate),
                        "PIS_rate": float(pis_rate),
                        "COFINS_rate": float(cofins_rate),
                        "ICMS_rate": 0.0,  # será substituído pela alíquota interna da configuração
                    }

                    st.session_state["items_df"] = pd.concat(
                        [st.session_state["items_df"], pd.DataFrame([new_item])],
                        ignore_index=True,
                    )

                    st.success(f"Item com NCM {row['NCM_dotted']} adicionado à simulação.")


# =========================
# LISTA DE ITENS ADICIONADOS
# =========================
st.subheader("Itens adicionados")

if st.session_state["items_df"].empty:
    st.info("Nenhum item adicionado ainda. Use o formulário acima para incluir produtos.")
else:
    st.dataframe(
        st.session_state["items_df"][["NCM", "Description", "Quantity", "FOB_Unit_USD"]],
        use_container_width=True,
    )

    col_r1, col_r2 = st.columns(2)
    with col_r1:
        if st.button("🗑️ Remover último item"):
            st.session_state["items_df"] = st.session_state["items_df"].iloc[:-1, :].copy()
    with col_r2:
        if st.button("🧹 Limpar todos os itens"):
            st.session_state["items_df"] = st.session_state["items_df"].iloc[0:0].copy()


# =========================
# PASSO 3 – RESULTADOS
# =========================
st.markdown("---")
st.markdown("### Passo 3 – Resultados")

if st.button("Calcular custo de importação"):
    items_df = st.session_state["items_df"]

    if items_df.empty:
        st.warning("Adicione pelo menos um item à simulação.")
    else:
        clean_df = items_df.copy()

        # Garantir tipos numéricos
        for col in [
            "Quantity",
            "FOB_Unit_USD",
            "II_rate",
            "IPI_rate",
            "PIS_rate",
            "COFINS_rate",
            "ICMS_rate",
        ]:
            if col not in clean_df.columns:
                clean_df[col] = 0.0
            clean_df[col] = clean_df[col].fillna(0.0).astype(float)

        # ICMS por item = alíquota interna do estado (por enquanto)
        clean_df["ICMS_rate"] = float(icms_aliq)

        # AFRMM: 8% sobre o frete para marítimo; 0 para aéreo
        if equipamento.lower() in ["fcl_20", "fcl_40", "lcl"]:
            afrmm_pct = 0.08
        else:
            afrmm_pct = 0.0

        # Seguro: 0,10% ad valorem sobre o FOB total (cálculo feito em calculations.py)
        insurance_usd = 0.0
        insurance_pct = 0.001  # 0,1%

        origin_charges_usd = 0.0
        thc_origin_usd = 0.0

        local_port_costs_brl = 0.0
        other_local_costs_brl = 0.0

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
        # RESUMO
        # =========================
        st.subheader("Resumo")

        # Get values from summary
        fob_total_brl = summary.get("FOB_total_BRL", 0.0)
        fob_total_usd = summary.get("FOB_total_USD", 0.0)
        impostos_totais = summary.get("Tax_paid_total_BRL", 0.0)
        creditos_totais = summary.get("Tax_credit_total_BRL", 0.0)
        frete_total_brl = summary.get("Freight_total_BRL", 0.0)
        custo_final_brl = summary.get("Final_cost_BRL", 0.0)

        # Multiplicador = Custo final (R$) / FOB total (USD)
        if fob_total_usd > 0:
            multiplicador = custo_final_brl / fob_total_usd
        else:
            multiplicador = 0.0

        col1, col2 = st.columns(2)
        with col1:
            st.metric(
                "FOB total (R$)",
                f"{fob_total_brl:,.2f}",
            )
            st.metric(
                "Frete internacional (R$)",
                f"{frete_total_brl:,.2f}",
            )
            st.metric(
                "Impostos (R$)",
                f"{impostos_totais:,.2f}",
            )
            st.metric(
                "Créditos de impostos (R$)",
                f"{creditos_totais:,.2f}",
            )
        with col2:
            st.metric(
                "Custo final (R$)",
                f"{custo_final_brl:,.2f}",
            )
            st.metric(
                "Multiplicador",
                f"{multiplicador:,.2f}x",
            )

        # Texto explicando quais impostos geram crédito em cada regime
        if regime == "simples":
            credit_text = (
                "Créditos considerados: **nenhum**. "
                "Simples Nacional não aproveita créditos de IPI/PIS/COFINS/ICMS nesta simulação."
            )
        elif regime == "presumido":
            credit_text = (
                "Créditos considerados: **IPI e ICMS** sobre mercadorias para revenda/industrialização. "
                "PIS e COFINS são tratados como cumulativos, sem crédito (modelo simplificado)."
            )
        else:  # lucro real
            credit_text = (
                "Créditos considerados: **IPI, PIS, COFINS e ICMS** sobre mercadorias para revenda/industrialização "
                "(modelo simplificado de regime não cumulativo)."
            )

        st.caption(credit_text)

        # =========================
        # RESULTADOS POR ITEM
        # =========================
        st.subheader("Resultados por item")

        cols_to_show = [
            "NCM",
            "Description",
            "Landed_Cost_BRL",
            "Unit_Cost_BRL",
            "Quantity",
            "FOB_Total_BRL",
            "CIF_BRL",
            "II_BRL",
            "IPI_BRL",
            "PIS_BRL",
            "COFINS_BRL",
            "ICMS_BRL",
            "net_tax_total",
            "Truck_BRL",
        ]

        display_df = per_item[cols_to_show].rename(
            columns={
                "Description": "Descrição",
                "Landed_Cost_BRL": "Custo total por produto (R$)",
                "Unit_Cost_BRL": "Custo unitário por produto (R$)",
                "Quantity": "Quantidade",
                "FOB_Total_BRL": "FOB total (R$)",
                "CIF_BRL": "Valor Aduaneiro / CIF (R$)",
                "II_BRL": "II (R$)",
                "IPI_BRL": "IPI (R$)",
                "PIS_BRL": "PIS-Importação (R$)",
                "COFINS_BRL": "COFINS-Importação (R$)",
                "ICMS_BRL": "ICMS (R$)",
                "net_tax_total": "Impostos líquidos (R$)",
                "Truck_BRL": "Transporte rodoviário (R$)",
            }
        )

        st.dataframe(display_df, use_container_width=True)
