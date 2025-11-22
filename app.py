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

# =========================
# Global styling (high-contrast, light, sleek cards)
# =========================
st.markdown(
    """
    <style>
        body {
            background-color: #e5e7eb;
        }
        .block-container {
            padding-top: 1.2rem;
            padding-bottom: 3rem;
            max-width: 1100px;
            margin: 0 auto;
        }
        .step-card {
            background: #ffffff;
            border-radius: 12px;
            padding: 1.1rem 1.3rem;
            border: 1px solid #d1d5db;
            box-shadow: 0 8px 18px rgba(15, 23, 42, 0.06);
            margin-bottom: 0.85rem;
        }
        .step-title {
            font-size: 0.8rem;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            font-weight: 600;
            color: #3b82f6;
            margin-bottom: 0.15rem;
        }
        .section-heading {
            font-size: 1.15rem;
            font-weight: 600;
            color: #111827;
            margin-bottom: 0.35rem;
        }
        .section-subtitle {
            font-size: 0.85rem;
            color: #6b7280;
            margin-bottom: 0.75rem;
        }
        .small-muted {
            font-size: 0.8rem;
            color: #6b7280;
        }
        /* Compact metrics */
        div[data-testid="stMetric"] {
            padding-top: 0.25rem;
            padding-bottom: 0.25rem;
        }
        /* Make tables a bit cleaner */
        .stTable td, .stTable th {
            font-size: 0.85rem;
            padding: 0.3rem 0.5rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📦 Simulador de Custo de Importação")

st.markdown(
    "Calcule o **custo Brasil** de um embarque com vários produtos, "
    "incluindo impostos, frete internacional e transporte rodoviário."
)

# =========================
# Load NCM / II / IPI table
# =========================
LOAD_ERROR = None
try:
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
            "Description",      # product name / code (user reference)
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
    Normalize user input for NCM (0000.00.00, 00000000 or partial).
    Returns only the digit string for prefix search.
    """
    if not isinstance(value, str):
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return None
    return digits


# =========================
# STEP 1 – SHIPMENT CONFIG (aligned rows)
# =========================
with st.container():
    st.markdown('<div class="step-card">', unsafe_allow_html=True)
    st.markdown(
        '<div class="step-title">Passo 1</div>'
        '<div class="section-heading">Configurações do embarque</div>'
        '<div class="section-subtitle">Defina o estado de destino, regime, modal, frete e câmbio.</div>',
        unsafe_allow_html=True,
    )

    # Row 1: Estado de destino (UF) | Regime tributário da empresa
    row1_col1, row1_col2 = st.columns(2)
    with row1_col1:
        estado_destino = st.selectbox(
            "Estado de destino (UF)",
            ["RS", "SC", "PR", "SP", "RJ", "MG", "ES", "BA", "GO", "DF", "Outros"],
            index=0,
        )

    with row1_col2:
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

    # Default ICMS by state
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

    # Row 2: Alíquota interna de ICMS | Uso das mercadorias
    row2_col1, row2_col2 = st.columns(2)
    with row2_col1:
        icms_aliq = st.number_input(
            "Alíquota interna de ICMS",
            value=icms_aliq_padrao,
            min_value=0.0,
            max_value=1.0,
            step=0.01,
            format="%.2f",
            help="Alíquota interna de ICMS usada como base para o cálculo (por enquanto, única para todos os itens).",
        )

    with row2_col2:
        uso_label = st.selectbox(
            "Uso das mercadorias",
            ["Indústria", "Revenda"],
            index=1,
            help="Usado para definir se a importação gera créditos (tratado como mercadorias para revenda/industrialização).",
        )
        # Internamente, tratamos ambos como 'resale'
        purpose = "resale"

    # Row 3: Equipamento (tipo de embarque) | Incoterm
    row3_col1, row3_col2 = st.columns(2)
    with row3_col1:
        equipamento = st.selectbox(
            "Equipamento (tipo de embarque)",
            ["FCL_20", "FCL_40", "LCL", "AIR"],
            index=2,
            help=(
                "FCL_20 / FCL_40 / LCL são tratados como embarque marítimo (AFRMM 8% sobre o frete). "
                "AIR é tratado como embarque aéreo (sem AFRMM)."
            ),
        )

    with row3_col2:
        incoterm = st.selectbox(
            "Incoterm",
            ["EXW", "FOB", "CIF"],
            index=0,
            help=(
                "Regra simplificada: para EXW/FOB, o frete informado entra na base de cálculo. "
                "Para CIF, o preço informado é considerado CIF, então o frete é desconsiderado "
                "na base de cálculo dos impostos (evita dupla contagem)."
            ),
        )
        allocation_method = "FOB"

    # Row 4: Frete internacional (USD) | Transporte rodoviário até o destino (R$)
    row4_col1, row4_col2 = st.columns(2)
    with row4_col1:
        frete_usd = st.number_input(
            "Frete internacional (USD)",
            value=0.0,
            min_value=0.0,
            step=10.0,
            help=(
                "Para EXW/FOB: frete considerado nos impostos. "
                "Para CIF: esse valor é ignorado (frete já embutido no preço CIF)."
            ),
        )

    with row4_col2:
        transporte_rodoviario_brl = st.number_input(
            "Transporte rodoviário até o destino (R$)",
            value=0.0,
            min_value=0.0,
            step=50.0,
        )

    # Row 5: Câmbio USD → BRL (full width)
    row5_col, = st.columns(1)
    with row5_col:
        cambio = st.number_input(
            "Câmbio USD → BRL",
            value=5.50,
            min_value=0.0,
            step=0.01,
            format="%.4f",
        )

    # Advanced cost adjustments: EXW uplift and LCL extra handling
    with st.expander("Ajustes avançados de custos (opcional)"):
        exw_extra_origin_usd = st.number_input(
            "Ajuste EXW → FOB (USD por embarque)",
            value=300.0,
            min_value=0.0,
            step=10.0,
            help="Valor aproximado de custos na origem (coleta, terminal, documentação) quando o Incoterm é EXW.",
        )
        lcl_extra_dest_brl = st.number_input(
            "Taxas adicionais LCL no destino (R$ por embarque)",
            value=0.0,
            min_value=0.0,
            step=50.0,
            help="Custos extras de manuseio LCL no destino (ex.: taxas de consolidador, handling).",
        )

    st.markdown(
        '<div class="small-muted">'
        "Seguro padrão: <strong>0,10% ad valorem</strong> sobre o FOB total (se não informado). "
        "AFRMM (8% sobre o frete) e Taxa Siscomex (R$ 154,23) são incluídos automaticamente "
        "na base do ICMS para embarques marítimos."
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)


# =========================
# STEP 2 – ITEMS
# =========================
with st.container():
    st.markdown('<div class="step-card">', unsafe_allow_html=True)
    st.markdown(
        '<div class="step-title">Passo 2</div>'
        '<div class="section-heading">Itens da simulação</div>'
        '<div class="section-subtitle">Informe o código/nome do produto, selecione o NCM e o valor FOB.</div>',
        unsafe_allow_html=True,
    )

    st.subheader("Adicionar item", anchor=False)

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
            # Linha 1: código / nome interno do produto
            col_prod, = st.columns(1)
            with col_prod:
                product_ref = st.text_input(
                    "Código ou nome do produto (referência interna)",
                    help="Ex.: MV150-ZN-450, Bolsa Neo Preta, etc. Apenas para seu controle.",
                )

            # Linha 2: NCM + busca
            col_ncm, col_desc = st.columns([1, 1.2])
            with col_ncm:
                ncm_input = st.text_input(
                    "NCM (0000.00.00 ou 00000000)",
                    help="Digite o NCM completo ou parcial. O sistema filtrará os códigos finais (8 dígitos).",
                )

            with col_desc:
                search_hint = st.text_input(
                    "Busca por descrição (opcional)",
                    help="Use palavras-chave do TEC/TIPI (ex.: 'assento', 'bolsas', 'corrediças').",
                )

            # Linha 3: quantidade + FOB unitário
            col_qtd, col_fob = st.columns(2)
            with col_qtd:
                quantidade = st.number_input(
                    "Quantidade",
                    min_value=1,
                    value=1,
                    step=1,
                )
            with col_fob:
                fob_unit = st.number_input(
                    "FOB unitário (USD)",
                    min_value=0.0,
                    value=1.00,
                    step=0.01,
                    format="%.4f",
                )

            st.markdown("##### Sugestões de NCM finais (8 dígitos)")

            matches = pd.DataFrame()

            # Busca por NCM (prefixo de dígitos)
            if ncm_input.strip():
                digits = normalize_ncm_search(ncm_input)
                if digits is not None and "digits" in NCM_TABLE.columns:
                    tmp = NCM_TABLE.copy()
                    tmp = tmp[tmp["digits"].str.startswith(digits)]
                    # apenas códigos finais (8 dígitos)
                    if "digits_len" in tmp.columns:
                        tmp = tmp[tmp["digits_len"] == 8]
                    matches = tmp

            # Ou busca por descrição
            elif search_hint.strip():
                tokens = [t for t in search_hint.lower().split() if t]
                df_search = NCM_TABLE.copy()
                if tokens:
                    mask = pd.Series(True, index=df_search.index)
                    for t in tokens:
                        mask &= df_search["Descricao"].str.lower().str.contains(t, na=False)
                    tmp = df_search[mask]
                    if "digits_len" in tmp.columns:
                        tmp = tmp[tmp["digits_len"] == 8]
                    matches = tmp

            if not matches.empty:
                # ordenar por NCM completo
                sort_cols = ["NCM_dotted"]
                matches = matches.sort_values(sort_cols).head(80)
                option_indices = matches.index.tolist()

                def format_ncm_option(idx):
                    row = matches.loc[idx]
                    code = str(row.get("NCM_dotted", "")).strip()
                    desc = str(row.get("Descricao", "")).strip()

                    ii = row.get("II_rate", 0.0)
                    ipi = row.get("IPI_rate", 0.0)

                    try:
                        ii_pct = f"{ii * 100:.1f}%"
                    except Exception:
                        ii_pct = "-"
                    try:
                        ipi_pct = f"{ipi * 100:.1f}%"
                    except Exception:
                        ipi_pct = "-"

                    return f"{code}  {desc}  • II {ii_pct}  |  IPI {ipi_pct}"

                selected_idx = st.selectbox(
                    "Selecione o NCM final",
                    options=option_indices,
                    format_func=format_ncm_option,
                )

            else:
                selected_idx = None
                st.info(
                    "Nenhum NCM final listado ainda. "
                    "Digite parte do NCM ou use palavras da descrição para buscar."
                )

            submitted = st.form_submit_button("➕ Adicionar item à simulação")

            if submitted:
                if not product_ref.strip():
                    st.error("Informe um código ou nome para o produto (referência interna).")
                elif selected_idx is None:
                    st.error("Selecione um NCM final antes de adicionar o item.")
                else:
                    row = matches.loc[selected_idx]

                    # Apenas NCMs de 8 dígitos já foram filtrados
                    ncm_final = str(row.get("NCM_dotted", "")).strip()

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
                        "NCM": ncm_final,
                        "Description": product_ref.strip(),
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

                    st.success(
                        f"Item '{product_ref.strip()}' com NCM {ncm_final} adicionado à simulação."
                    )

    # Itens adicionados – visão em lista (sem cara de Excel)
    st.markdown("#### Itens adicionados")

    items_df = st.session_state["items_df"]
    if items_df.empty:
        st.info("Nenhum item adicionado ainda.")
    else:
        # calcular FOB total por item para exibir
        tmp = items_df.copy()
        tmp["FOB_Total_USD"] = tmp["FOB_Unit_USD"] * tmp["Quantity"]
        display_items = tmp[["Description", "NCM", "Quantity", "FOB_Unit_USD", "FOB_Total_USD"]]

        display_items = display_items.rename(
            columns={
                "Description": "Produto",
                "Quantity": "Qtd.",
                "FOB_Unit_USD": "FOB unit. (USD)",
                "FOB_Total_USD": "FOB total (USD)",
            }
        )

        st.table(display_items)

        col_r1, col_r2 = st.columns(2)
        with col_r1:
            if st.button("🗑️ Remover último item"):
                st.session_state["items_df"] = st.session_state["items_df"].iloc[:-1, :].copy()
        with col_r2:
            if st.button("🧹 Limpar todos os itens"):
                st.session_state["items_df"] = st.session_state["items_df"].iloc[0:0].copy()

    st.markdown("</div>", unsafe_allow_html=True)


# =========================
# STEP 3 – RESULTS
# =========================
with st.container():
    st.markdown('<div class="step-card">', unsafe_allow_html=True)
    st.markdown(
        '<div class="step-title">Passo 3</div>'
        '<div class="section-heading">Resultados</div>'
        '<div class="section-subtitle">Resumo do embarque e custo por produto.</div>',
        unsafe_allow_html=True,
    )

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
                modal_label = "Marítimo (AFRMM 8%)"
            else:
                afrmm_pct = 0.0
                modal_label = "Aéreo (sem AFRMM)"

            # Incoterm: define frete efetivo na base de cálculo
            if incoterm == "CIF":
                effective_freight_usd = 0.0
            else:
                effective_freight_usd = frete_usd

            # EXW → FOB uplift: custos de origem só se Incoterm for EXW
            if incoterm == "EXW":
                origin_charges_usd = exw_extra_origin_usd
            else:
                origin_charges_usd = 0.0

            # LCL extra handling no destino
            if equipamento == "LCL":
                local_port_costs_brl = lcl_extra_dest_brl
            else:
                local_port_costs_brl = 0.0

            # Seguro: 0,10% ad valorem sobre o FOB total (cálculo feito em calculations.py)
            insurance_usd = 0.0
            insurance_pct = 0.001  # 0,1%

            thc_origin_usd = 0.0
            other_local_costs_brl = 0.0

            siscomex_brl = 154.23

            cfg = ShipmentConfig(
                state_destination=estado_destino,
                mode=equipamento,
                fx_rate_usd_brl=cambio,
                freight_international_usd=effective_freight_usd,
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

            # ===== Resumo =====
            st.markdown("#### Resumo do embarque")

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
                st.metric("FOB total (R$)", f"{fob_total_brl:,.2f}")
                st.metric("Frete internacional (R$)", f"{frete_total_brl:,.2f}")
                st.metric("Impostos (R$)", f"{impostos_totais:,.2f}")
                st.metric("Créditos de impostos (R$)", f"{creditos_totais:,.2f}")
            with col2:
                st.metric("Custo final (R$)", f"{custo_final_brl:,.2f}")
                st.metric("Multiplicador", f"{multiplicador:,.2f}x")

            # Texto explicando créditos + modal/incoterm
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

            extra_text = f" Modal: **{modal_label}** • Incoterm: **{incoterm}**."
            st.markdown(
                f"<div class='small-muted'>{credit_text}{extra_text}</div>",
                unsafe_allow_html=True,
            )

            # ===== Resultados por item =====
            st.markdown("#### Custo por produto")

            simple_cols = [
                "Description",
                "NCM",
                "Quantity",
                "Landed_Cost_BRL",
                "Unit_Cost_BRL",
            ]
            simple_df = per_item[simple_cols].rename(
                columns={
                    "Description": "Produto",
                    "Quantity": "Qtd.",
                    "Landed_Cost_BRL": "Custo total por produto (R$)",
                    "Unit_Cost_BRL": "Custo unitário por produto (R$)",
                }
            )
            st.table(simple_df)

            with st.expander("Ver detalhes fiscais por item"):
                cols_to_show = [
                    "Description",
                    "NCM",
                    "Quantity",
                    "FOB_Total_BRL",
                    "CIF_BRL",
                    "II_BRL",
                    "IPI_BRL",
                    "PIS_BRL",
                    "COFINS_BRL",
                    "ICMS_BRL",
                    "net_tax_total",
                    "Landed_Cost_BRL",
                    "Unit_Cost_BRL",
                    "Truck_BRL",
                ]

                display_df = per_item[cols_to_show].rename(
                    columns={
                        "Description": "Produto",
                        "Quantity": "Qtd.",
                        "FOB_Total_BRL": "FOB total (R$)",
                        "CIF_BRL": "Valor Aduaneiro / CIF (R$)",
                        "II_BRL": "II (R$)",
                        "IPI_BRL": "IPI (R$)",
                        "PIS_BRL": "PIS-Importação (R$)",
                        "COFINS_BRL": "COFINS-Importação (R$)",
                        "ICMS_BRL": "ICMS (R$)",
                        "net_tax_total": "Impostos líquidos (R$)",
                        "Landed_Cost_BRL": "Custo total por produto (R$)",
                        "Unit_Cost_BRL": "Custo unitário por produto (R$)",
                        "Truck_BRL": "Transporte rodoviário (R$)",
                    }
                )

                st.dataframe(display_df, use_container_width=True)

    st.markdown("</div>", unsafe_allow_html=True)
