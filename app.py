import streamlit as st
import pandas as pd
import datetime
import requests
import os
from fpdf import FPDF  # PDF generator

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
# Base CSS (single theme)
# =========================
BASE_CSS = """
<style>
    .block-container {
        padding-top: 2.5rem;
        padding-bottom: 3rem;
        max-width: 1100px;
        margin: 0 auto;
    }
    /* Header with logo and title */
    .app-header {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        margin-top: 0.25rem;
        margin-bottom: 0.4rem;
    }
    .app-logo svg {
        height: 32px;
        max-width: 130px;
        display: block;
        /* render logo white on dark background */
        filter: invert(1) brightness(1.8);
    }
    .app-title {
        display: flex;
        flex-direction: row;
        align-items: baseline;
        gap: 0.3rem;
    }
    .app-title-emoji {
        font-size: 1.4rem;
    }
    .app-title-text {
        font-size: 1.25rem;
        font-weight: 600;
    }

    .step-card {
        background: transparent;
        border-radius: 0;
        padding: 0.4rem 0 0.8rem 0;
        border-top: 2px solid #111827;
        margin-bottom: 0.8rem;
    }
    .step-title {
        font-size: 0.72rem;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        font-weight: 600;
        color: #3b82f6;
        margin-bottom: 0.05rem;
    }
    .section-heading {
        font-size: 1.05rem;
        font-weight: 600;
        margin-bottom: 0.15rem;
    }
    .section-subtitle {
        font-size: 0.84rem;
        color: #6b7280;
        margin-bottom: 0.5rem;
    }
    .small-muted {
        font-size: 0.8rem;
        color: #6b7280;
    }
    div[data-testid="stMetric"] {
        padding-top: 0.15rem;
        padding-bottom: 0.15rem;
    }
    .stTable td,
    .stTable th {
        font-size: 0.85rem;
        padding: 0.3rem 0.5rem;
    }
</style>
"""

st.markdown(BASE_CSS, unsafe_allow_html=True)

# =========================
# Utils
# =========================

def load_logo_svg() -> str | None:
    """Load inline SVG for the header logo from ckstsourcing_logo.svg in repo root."""
    try:
        with open("ckstsourcing_logo.svg", "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


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


def fetch_usd_brl_ptax_previous():
    """
    Busca a cotação de compra do USD/BRL (PTAX) do dia útil anterior,
    voltando até 9 dias se necessário (feriados/fins de semana).
    """
    today = datetime.date.today()
    for i in range(1, 10):
        d = today - datetime.timedelta(days=i)
        date_str = d.strftime("%m-%d-%Y")
        url = (
            "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
            "CotacaoDolarDia(dataCotacao=@dataCotacao)?"
            f"@dataCotacao='{date_str}'&$top=1&$format=json"
        )
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        data = r.json()
        values = data.get("value", [])
        if values:
            # usar cotacaoCompra conforme solicitado
            rate = float(values[0]["cotacaoCompra"])
            return rate, d
    raise RuntimeError("Não foi possível obter a cotação do dólar nos últimos dias úteis.")


def set_ptax_rate():
    """Callback para o botão de buscar câmbio Banco Central (dia útil anterior)."""
    try:
        rate, d = fetch_usd_brl_ptax_previous()
        st.session_state["cambio_input"] = rate
        st.session_state["cambio_date"] = d.strftime("%d/%m/%Y")
        st.session_state["ptax_error"] = ""
    except Exception as e:
        st.session_state["ptax_error"] = str(e)


def prepare_items_df_for_calc(items_df: pd.DataFrame, icms_aliq: float) -> pd.DataFrame:
    """
    Normaliza o DataFrame de itens para o cálculo (tipos numéricos e ICMS_rate).
    """
    clean_df = items_df.copy()
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

    clean_df["ICMS_rate"] = float(icms_aliq)
    return clean_df


def build_shipment_config(
    estado_destino: str,
    equipamento: str,
    incoterm: str,
    cambio: float,
    frete_usd: float,
    exw_extra_origin_usd: float,
    lcl_extra_dest_brl: float,
    transporte_rodoviario_brl: float,
    logistics_agent_fee_brl: float,
    icms_aliq: float,
    purpose: str,
    allocation_method: str,
) -> tuple[ShipmentConfig, str]:
    """
    Constrói ShipmentConfig a partir das entradas da interface,
    retornando também o rótulo de modal para exibição.
    """
    # Modal / AFRMM
    if equipamento.lower() in ["fcl_20", "fcl_40", "lcl"]:
        afrmm_pct = 0.08
        modal_label = "Marítimo (AFRMM 8%)"
    else:
        afrmm_pct = 0.0
        modal_label = "Aéreo (sem AFRMM)"

    # Frete efetivo (CIF ignora frete informado)
    if incoterm == "CIF":
        effective_freight_usd = 0.0
    else:
        effective_freight_usd = frete_usd

    # Custos de origem extras (EXW)
    if incoterm == "EXW":
        origin_charges_usd = exw_extra_origin_usd
    else:
        origin_charges_usd = 0.0

    # Custos locais extras no destino (LCL)
    if equipamento == "LCL":
        local_port_costs_brl = lcl_extra_dest_brl
    else:
        local_port_costs_brl = 0.0

    # Seguro padrão ad valorem (se não informado)
    insurance_usd = 0.0
    insurance_pct = 0.001

    thc_origin_usd = 0.0

    other_local_costs_brl = logistics_agent_fee_brl

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
        regime=regime,  # regime é global, já mapeado abaixo
        purpose=purpose,
        icms_rate=icms_aliq,
        da_components=["afrmm", "siscomex"],
        va_components=["freight", "insurance", "origin_charges", "thc_origin"],
        allocation_method=allocation_method,
    )
    return cfg, modal_label


def solve_fob_target_for_item(
    item_idx: int,
    target_unit_cost_brl: float,
    base_items_df: pd.DataFrame,
    cfg: ShipmentConfig,
    icms_aliq: float,
    max_iter: int = 35,
    tol: float = 0.01,
):
    """
    Faz cálculo reverso para encontrar o FOB unitário (USD) necessário
    para que o item `item_idx` atinja `target_unit_cost_brl` (R$) de custo unitário.

    Retorna dict com:
      - status: "ok" | "too_low" | "too_high"
      - fob_exact
      - min_cost
      - cost_at_current
    """
    # Segurança básica
    if base_items_df.empty:
        return {"status": "empty"}

    # Custo mínimo possível (FOB = 0)
    base_df_zero = prepare_items_df_for_calc(base_items_df, icms_aliq)
    base_df_zero.iloc[item_idx, base_df_zero.columns.get_loc("FOB_Unit_USD")] = 0.0
    per_zero, _ = compute_landed_cost(base_df_zero, cfg)
    min_cost = float(per_zero.iloc[item_idx]["Unit_Cost_BRL"])

    # Custo com FOB atual (para referência)
    current_fob = float(base_items_df.iloc[item_idx]["FOB_Unit_USD"])
    base_df_current = prepare_items_df_for_calc(base_items_df, icms_aliq)
    per_cur, _ = compute_landed_cost(base_df_current, cfg)
    cost_at_current = float(per_cur.iloc[item_idx]["Unit_Cost_BRL"])

    if target_unit_cost_brl < min_cost - tol:
        # Nem com FOB zero chega nesse custo (custo está "abaixo do mínimo")
        return {
            "status": "too_low",
            "min_cost": min_cost,
            "cost_at_current": cost_at_current,
        }

    # Função auxiliar: custo unitário para dado FOB
    def unit_cost_for_fob(fob_value: float) -> float:
        df = prepare_items_df_for_calc(base_items_df, icms_aliq)
        df.iloc[item_idx, df.columns.get_loc("FOB_Unit_USD")] = fob_value
        per, _ = compute_landed_cost(df, cfg)
        return float(per.iloc[item_idx]["Unit_Cost_BRL"])

    # Encontrar um intervalo [0, high] que cubra o target
    low = 0.0
    high = max(current_fob, 1.0)
    cost_high = unit_cost_for_fob(high)

    # Se custo com high ainda abaixo do target, aumenta high progressivamente
    expand_steps = 0
    while cost_high < target_unit_cost_brl and expand_steps < 20:
        high *= 2
        cost_high = unit_cost_for_fob(high)
        expand_steps += 1

    if cost_high < target_unit_cost_brl:
        # Até com FOB absurdamente alto o custo não atinge o target (caso raro)
        return {
            "status": "too_high",
            "min_cost": min_cost,
            "cost_at_current": cost_at_current,
        }

    # Busca binária em [low, high]
    best_fob = high
    for _ in range(max_iter):
        mid = (low + high) / 2.0
        cost_mid = unit_cost_for_fob(mid)

        if abs(cost_mid - target_unit_cost_brl) <= tol:
            best_fob = mid
            break

        if cost_mid < target_unit_cost_brl:
            low = mid
        else:
            best_fob = mid
            high = mid

    return {
        "status": "ok",
        "fob_exact": best_fob,
        "min_cost": min_cost,
        "cost_at_current": cost_at_current,
    }


def generate_pdf_report(
    summary,
    items_df,
    cfg: ShipmentConfig,
    regime_label: str,
    uso_label: str,
    incoterm: str,
    modal_label: str,
    cambio_date: str,
    frete_usd: float,
    transporte_rodoviario_brl: float,
    exw_extra_origin_usd: float,
    lcl_extra_dest_brl: float,
    logistics_agent_fee_brl: float,
):
    """Gera um PDF simples com resumo e itens da simulação."""
    pdf = FPDF()
    # Ensure encoding supports Portuguese accents (CP1252)
    pdf.core_fonts_encoding = "windows-1252"
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Tentar inserir o logo da Cook Street (PNG) usando caminho relativo ao app.py
    logo_path = os.path.join(os.path.dirname(__file__), "ckstsourcing_logo.png")
    if os.path.exists(logo_path):
        try:
            pdf.image(logo_path, x=10, y=8, w=30)
            pdf.ln(18)
        except Exception:
            pdf.ln(4)
    else:
        pdf.ln(4)

    # Header
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Simulação de Custo de Importação", ln=True)

    pdf.set_font("Helvetica", size=10)
    today_str = datetime.date.today().strftime("%d/%m/%Y")
    pdf.cell(0, 6, f"Data da simulação: {today_str}", ln=True)
    if cambio_date:
        pdf.cell(
            0,
            6,
            f"Câmbio Banco Central (compra) utilizado: {cambio_date}",
            ln=True,
        )
    pdf.ln(4)

    # Configurações do embarque
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Configurações do embarque", ln=True)
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 5, f"Estado de destino (UF): {cfg.state_destination}", ln=True)
    pdf.cell(0, 5, f"Regime tributário: {regime_label}", ln=True)
    pdf.cell(0, 5, f"Uso das mercadorias: {uso_label}", ln=True)
    pdf.cell(0, 5, f"Modal: {modal_label}", ln=True)

    # Exibir equipamento com espaço, se for FCL_20 / FCL_40
    equip_display = cfg.mode
    if cfg.mode == "FCL_20":
        equip_display = "FCL 20"
    elif cfg.mode == "FCL_40":
        equip_display = "FCL 40"

    pdf.cell(0, 5, f"Equipamento: {equip_display}", ln=True)
    pdf.cell(0, 5, f"Incoterm: {incoterm}", ln=True)
    pdf.cell(0, 5, f"Câmbio USD/BRL: {cfg.fx_rate_usd_brl:.4f}", ln=True)
    pdf.cell(0, 5, f"Frete internacional (USD): {frete_usd:,.2f}", ln=True)
    pdf.cell(
        0,
        5,
        f"Transporte rodoviário até o destino (R$): {transporte_rodoviario_brl:,.2f}",
        ln=True,
    )
    if exw_extra_origin_usd > 0:
        pdf.cell(0, 5, f"Ajuste EXW para FOB (USD): {exw_extra_origin_usd:,.2f}", ln=True)
    if lcl_extra_dest_brl > 0:
        pdf.cell(0, 5, f"Taxas adicionais LCL no destino (R$): {lcl_extra_dest_brl:,.2f}", ln=True)
    if logistics_agent_fee_brl > 0:
        pdf.cell(
            0,
            5,
            f"Serviços do agente de carga (R$): {logistics_agent_fee_brl:,.2f}",
            ln=True,
        )

    pdf.ln(4)

    # Resumo financeiro
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Resumo financeiro", ln=True)
    pdf.set_font("Helvetica", size=10)

    fob_total_brl = summary.get("FOB_total_BRL", 0.0)
    fob_total_usd = summary.get("FOB_total_USD", 0.0)
    frete_total_brl = summary.get("Freight_total_BRL", 0.0)
    impostos_totais = summary.get("Tax_paid_total_BRL", 0.0)
    creditos_totais = summary.get("Tax_credit_total_BRL", 0.0)
    custo_final_brl = summary.get("Final_cost_BRL", 0.0)

    if fob_total_usd > 0:
        multiplicador = custo_final_brl / fob_total_usd
    else:
        multiplicador = 0.0

    pdf.cell(0, 5, f"FOB total (R$): {fob_total_brl:,.2f}", ln=True)
    pdf.cell(0, 5, f"FOB total (USD): {fob_total_usd:,.2f}", ln=True)
    pdf.cell(0, 5, f"Frete internacional (R$): {frete_total_brl:,.2f}", ln=True)
    pdf.cell(0, 5, f"Impostos totais (R$): {impostos_totais:,.2f}", ln=True)
    pdf.cell(0, 5, f"Créditos de impostos (R$): {creditos_totais:,.2f}", ln=True)
    pdf.cell(0, 5, f"Custo final (R$): {custo_final_brl:,.2f}", ln=True)
    pdf.cell(
        0,
        5,
        f"Multiplicador (Custo final / FOB USD): {multiplicador:,.2f}x",
        ln=True,
    )

    pdf.ln(4)

    # Custo por produto
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Itens da simulação", ln=True)

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(60, 6, "Produto", border=1)
    pdf.cell(25, 6, "NCM", border=1)
    pdf.cell(15, 6, "Qtd.", border=1, align="R")
    pdf.cell(30, 6, "FOB unit. (USD)", border=1, align="R")
    pdf.cell(30, 6, "Custo unit. (R$)", border=1, ln=True, align="R")

    pdf.set_font("Helvetica", size=9)

    for _, row in items_df.iterrows():
        desc = str(row.get("Description", ""))[:40]
        ncm = str(row.get("NCM", ""))
        qtd = float(row.get("Quantity", 0))
        fob_unit = float(row.get("FOB_Unit_USD", 0))
        unit_cost = float(row.get("Unit_Cost_BRL", 0))

        pdf.cell(60, 6, desc, border=1)
        pdf.cell(25, 6, ncm, border=1)
        pdf.cell(15, 6, f"{qtd:.0f}", border=1, align="R")
        pdf.cell(30, 6, f"{fob_unit:,.2f}", border=1, align="R")
        pdf.cell(30, 6, f"{unit_cost:,.2f}", border=1, ln=True, align="R")

    # Observações regime/créditos
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Observações sobre créditos de impostos:", ln=True)
    pdf.set_font("Helvetica", size=9)

    if cfg.regime == "simples":
        pdf.multi_cell(
            0,
            4,
            "Simples Nacional: nesta simulação, não são considerados créditos de IPI, "
            "PIS, COFINS ou ICMS. Todos os impostos compõem o custo final.",
        )
    elif cfg.regime == "presumido":
        pdf.multi_cell(
            0,
            4,
            "Lucro Presumido: créditos considerados de IPI e ICMS sobre mercadorias "
            "para revenda/industrialização. PIS e COFINS tratados como cumulativos, "
            "sem crédito (modelo simplificado).",
        )
    else:
        pdf.multi_cell(
            0,
            4,
            "Lucro Real: créditos considerados de IPI, PIS, COFINS e ICMS sobre "
            "mercadorias para revenda/industrialização (modelo simplificado, não "
            "substitui análise fiscal específica do cliente).",
        )

    # Return bytes (compatible with different fpdf2 versions)
    out = pdf.output(dest="S")
    if isinstance(out, (bytes, bytearray)):
        pdf_bytes = bytes(out)
    else:
        pdf_bytes = out.encode("latin-1")
    return pdf_bytes


# =========================
# Header with logo
# =========================

logo_svg = load_logo_svg()

if logo_svg:
    header_html = f"""
    <div class="app-header">
        <div class="app-logo">
            {logo_svg}
        </div>
        <div class="app-title">
            <span class="app-title-emoji">📦</span>
            <span class="app-title-text">Simulador de Custo de Importação</span>
        </div>
    </div>
    """
else:
    header_html = """
    <div class="app-header">
        <div class="app-title">
            <span class="app-title-emoji">📦</span>
            <span class="app-title-text">Simulador de Custo de Importação</span>
        </div>
    </div>
    """

st.markdown(header_html, unsafe_allow_html=True)
st.markdown("Simule o custo Brasil completo de um embarque com vários produtos.")

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
# Session state
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

if "cambio_input" not in st.session_state:
    st.session_state["cambio_input"] = 5.50

if "cambio_date" not in st.session_state:
    st.session_state["cambio_date"] = ""

if "ptax_error" not in st.session_state:
    st.session_state["ptax_error"] = ""


# =========================
# STEP 1 – SHIPMENT CONFIG
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
        # For now, we always treat as resale/industrialization for credits logic
        purpose = "resale"

    # Row 3: Equipamento (tipo de embarque) | Incoterm
    row3_col1, row3_col2 = st.columns(2)
    with row3_col1:
        equip_label = st.selectbox(
            "Equipamento (tipo de embarque)",
            ["FCL 20", "FCL 40", "LCL", "AIR"],
            index=2,
            help=(
                "FCL 20 / FCL 40 / LCL são tratados como embarque marítimo (AFRMM 8% sobre o frete). "
                "AIR é tratado como embarque aéreo (sem AFRMM)."
            ),
        )
        equip_map = {
            "FCL 20": "FCL_20",
            "FCL 40": "FCL_40",
            "LCL": "LCL",
            "AIR": "AIR",
        }
        equipamento = equip_map[equip_label]

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

    # Row 5: Câmbio USD → BRL (full width) + Banco Central button
    row5_col, = st.columns(1)
    with row5_col:
        cambio = st.number_input(
            "Câmbio USD → BRL",
            value=st.session_state["cambio_input"],
            key="cambio_input",
            min_value=0.0,
            step=0.01,
            format="%.4f",
        )
        st.button(
            "Usar câmbio Banco Central (dia útil anterior)",
            on_click=set_ptax_rate,
            help="Busca automaticamente a cotação de compra PTAX do dia útil anterior no Banco Central.",
        )
        if st.session_state.get("cambio_date"):
            st.caption(
                f"Câmbio Banco Central (compra) de {st.session_state['cambio_date']}."
            )
        if st.session_state.get("ptax_error"):
            st.warning(
                "Não foi possível obter a cotação automaticamente: "
                f"{st.session_state['ptax_error']}"
            )

    # Ajustes avançados (não colapsados)
    st.markdown("##### Ajustes avançados de custos (opcional)")
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
    logistics_agent_fee_brl = st.number_input(
        "Serviços do agente de carga (R$ por embarque)",
        value=0.0,
        min_value=0.0,
        step=50.0,
        help="Honorários do agente de carga / despachante (ex.: serviços Anderson).",
    )

    st.markdown(
        '<div class="small-muted">'
        "Seguro padrão: <strong>0,10% ad valorem</strong> sobre o FOB total (se não informado). "
        "AFRMM (8% sobre o frete) e Taxa Siscomex (R$ 154,23) são incluídos automaticamente "
        "na base do ICMS para embarques marítimos. Serviços do agente de carga são tratados como "
        "custo local adicional (fora da base do ICMS neste modelo simplificado)."
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

        # --- Inputs (no form: Enter won't submit) ---
        col_prod, = st.columns(1)
        with col_prod:
            product_ref = st.text_input(
                "Código ou nome do produto (referência interna)",
                help="Ex.: MV150-ZN-450, Bolsa Neo Preta, etc. Apenas para seu controle.",
            )

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
        selected_idx = None

        if ncm_input.strip():
            digits = normalize_ncm_search(ncm_input)
            if digits is not None and "digits" in NCM_TABLE.columns:
                tmp = NCM_TABLE.copy()
                tmp = tmp[tmp["digits"].str.startswith(digits)]
                if "digits_len" in tmp.columns:
                    tmp = tmp[tmp["digits_len"] == 8]
                matches = tmp

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
            st.info(
                "Nenhum NCM final listado ainda. "
                "Digite parte do NCM ou use palavras da descrição para buscar."
            )

        add_clicked = st.button("➕ Adicionar item à simulação")

        if add_clicked:
            if not product_ref.strip():
                st.error("Informe um código ou nome para o produto (referência interna).")
            elif selected_idx is None:
                st.error("Selecione um NCM final antes de adicionar o item.")
            else:
                row = matches.loc[selected_idx]

                ncm_final = str(row.get("NCM_dotted", "")).strip()

                ii_rate = row.get("II_rate", 0.0)
                if pd.isna(ii_rate):
                    ii_rate = 0.0

                ipi_rate = row.get("IPI_rate", 0.0)
                if pd.isna(ipi_rate):
                    ipi_rate = 0.0

                pis_rate = 0.021
                cofins_rate = 0.0965

                new_item = {
                    "NCM": ncm_final,
                    "Description": product_ref.strip(),
                    "Quantity": float(quantidade),
                    "FOB_Unit_USD": float(fob_unit),
                    "II_rate": float(ii_rate),
                    "IPI_rate": float(ipi_rate),
                    "PIS_rate": float(pis_rate),
                    "COFINS_rate": float(cofins_rate),
                    "ICMS_rate": 0.0,
                }

                st.session_state["items_df"] = pd.concat(
                    [st.session_state["items_df"], pd.DataFrame([new_item])],
                    ignore_index=True,
                )

                st.success(
                    f"Item '{product_ref.strip()}' com NCM {ncm_final} adicionado à simulação."
                )

    st.markdown("#### Itens adicionados")

    items_df = st.session_state["items_df"]
    if items_df.empty:
        st.info("Nenhum item adicionado ainda.")
    else:
        tmp = items_df.copy()
        tmp["FOB_Total_USD"] = tmp["FOB_Unit_USD"] * tmp["Quantity"]
        display_items = tmp[["Description", "NCM", "Quantity", "FOB_Unit_USD", "FOB_Total_USD"]]
