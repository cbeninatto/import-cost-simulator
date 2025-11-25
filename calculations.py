from dataclasses import dataclass, field
from typing import List, Tuple
import pandas as pd


@dataclass
class ShipmentConfig:
    state_destination: str
    mode: str
    fx_rate_usd_brl: float

    # Custos internacionais (USD)
    freight_international_usd: float
    insurance_usd: float = 0.0
    insurance_pct: float = 0.0  # usado se insurance_usd == 0
    origin_charges_usd: float = 0.0  # EXW → FOB, origin docs, etc.
    thc_origin_usd: float = 0.0

    # Encargos e custos em BRL
    afrmm_pct: float = 0.0
    siscomex_brl: float = 0.0
    local_port_costs_brl: float = 0.0  # ex.: custos adicionais LCL
    trucking_brl: float = 0.0          # transporte rodoviário
    other_local_costs_brl: float = 0.0 # serviços do agente, etc.

    # Tributação
    regime: str = "presumido"  # "simples" | "presumido" | "real"
    purpose: str = "resale"    # resale / industria (tratamos os dois como geradores de crédito)
    icms_rate: float = 0.18

    # Componentes incluídos na base de ICMS
    da_components: List[str] = field(default_factory=lambda: ["afrmm", "siscomex"])
    # Componentes incluídos no Valor Aduaneiro
    va_components: List[str] = field(
        default_factory=lambda: ["freight", "insurance", "origin_charges", "thc_origin"]
    )

    # Método de rateio (por enquanto, somente FOB)
    allocation_method: str = "FOB"


def _allocate_by_fob(items: pd.DataFrame, total_value: float) -> pd.Series:
    """
    Rateia 'total_value' entre os itens proporcionalmente ao FOB total de cada um.
    Se o FOB total do embarque for zero, divide igualmente.
    """
    fob_total = (items["FOB_Unit_USD"] * items["Quantity"]).sum()
    if fob_total > 0:
        share = (items["FOB_Unit_USD"] * items["Quantity"]) / fob_total
    else:
        # fallback: divide igualmente entre os itens
        n = max(len(items), 1)
        share = pd.Series([1.0 / n] * len(items), index=items.index)
    return share * float(total_value)


def _compute_tax_credits_per_item(
    df: pd.DataFrame,
    cfg: ShipmentConfig
) -> pd.Series:
    """
    Retorna uma Series com o total de créditos de impostos por item,
    de acordo com o regime tributário.
    """
    # Impostos calculados por item
    ii = df["II_BRL"]
    ipi = df["IPI_BRL"]
    pis = df["PIS_BRL"]
    cofins = df["COFINS_BRL"]
    icms = df["ICMS_BRL"]

    # Créditos iniciais (zero)
    credit_ii = pd.Series(0.0, index=df.index)
    credit_ipi = pd.Series(0.0, index=df.index)
    credit_pis = pd.Series(0.0, index=df.index)
    credit_cofins = pd.Series(0.0, index=df.index)
    credit_icms = pd.Series(0.0, index=df.index)

    # Simples Nacional: não consideramos créditos
    if cfg.regime == "simples":
        return (
            credit_ii
            + credit_ipi
            + credit_pis
            + credit_cofins
            + credit_icms
        )

    # Mercadorias para revenda / industrialização geram créditos
    if cfg.purpose == "resale":
        if cfg.regime == "presumido":
            # Modelo simplificado: crédito de IPI e ICMS apenas
            credit_ipi = ipi
            credit_icms = icms

        elif cfg.regime == "real":
            # Modelo simplificado: crédito de IPI, PIS, COFINS e ICMS
            credit_ipi = ipi
            credit_pis = pis
            credit_cofins = cofins
            credit_icms = icms

    total_credit = (
        credit_ii
        + credit_ipi
        + credit_pis
        + credit_cofins
        + credit_icms
    )
    return total_credit


def compute_landed_cost(
    items_df: pd.DataFrame,
    cfg: ShipmentConfig
) -> Tuple[pd.DataFrame, dict]:
    """
    Calcula o custo de importação por item e o resumo do embarque.

    Retorna:
      - per_item: DataFrame com custos e impostos por item
      - summary: dict com totais do embarque
    """
    df = items_df.copy()

    # =========================
    # 1) FOB em USD e BRL
    # =========================
    df["FOB_Total_USD"] = df["FOB_Unit_USD"] * df["Quantity"]
    df["FOB_Total_BRL"] = df["FOB_Total_USD"] * cfg.fx_rate_usd_brl

    fob_total_usd = df["FOB_Total_USD"].sum()
    fob_total_brl = df["FOB_Total_BRL"].sum()

    # =========================
    # 2) Custos internacionais (frete, seguro, origem)
    # =========================
    fx = float(cfg.fx_rate_usd_brl)

    # Frete
    freight_usd = float(cfg.freight_international_usd)
    freight_brl_total = freight_usd * fx
    df["Freight_BRL"] = _allocate_by_fob(df, freight_brl_total)

    # Seguro: valor absoluto ou % sobre FOB
    if cfg.insurance_usd > 0:
        insurance_usd = float(cfg.insurance_usd)
    else:
        insurance_usd = fob_total_usd * float(cfg.insurance_pct)

    insurance_brl_total = insurance_usd * fx
    df["Insurance_BRL"] = _allocate_by_fob(df, insurance_brl_total)

    # Custos de origem (EXW → FOB, documentação, etc.)
    origin_usd = float(cfg.origin_charges_usd)
    origin_brl_total = origin_usd * fx
    df["Origin_BRL"] = _allocate_by_fob(df, origin_brl_total)

    # THC origem, se houver
    thc_usd = float(cfg.thc_origin_usd)
    thc_brl_total = thc_usd * fx
    df["THC_Origin_BRL"] = _allocate_by_fob(df, thc_brl_total)

    # =========================
    # 3) AFRMM, Siscomex e demais custos locais
    # =========================
    # AFRMM sobre o frete
    afrmm_brl_total = float(cfg.afrmm_pct) * freight_usd * fx
    df["AFRMM_BRL"] = _allocate_by_fob(df, afrmm_brl_total)

    # Taxa Siscomex
    siscomex_brl_total = float(cfg.siscomex_brl)
    df["Siscomex_BRL"] = _allocate_by_fob(df, siscomex_brl_total)

    # Custos locais de porto (inclui o extra LCL se informado)
    local_port_brl_total = float(cfg.local_port_costs_brl)
    df["Local_Port_BRL"] = _allocate_by_fob(df, local_port_brl_total)

    # Transporte rodoviário
    trucking_brl_total = float(cfg.trucking_brl)
    df["Truck_BRL"] = _allocate_by_fob(df, trucking_brl_total)

    # Serviços do agente / outros custos locais
    other_local_brl_total = float(cfg.other_local_costs_brl)
    df["Other_Local_BRL"] = _allocate_by_fob(df, other_local_brl_total)

    # =========================
    # 4) Valor Aduaneiro (VA) por item
    # =========================
    # Começa com FOB
    df["VA_BRL"] = df["FOB_Total_BRL"]

    # Mapeamento de componentes VA
    va_components_map = {
        "freight": "Freight_BRL",
        "insurance": "Insurance_BRL",
        "origin_charges": "Origin_BRL",
        "thc_origin": "THC_Origin_BRL",
    }

    for comp in cfg.va_components:
        col_name = va_components_map.get(comp)
        if col_name is not None and col_name in df.columns:
            df["VA_BRL"] += df[col_name]

    # =========================
    # 5) Cálculo dos impostos federais
    # =========================
    # II
    df["II_BRL"] = df["II_rate"] * df["VA_BRL"]

    # IPI (base = VA + II)
    df["IPI_Base_BRL"] = df["VA_BRL"] + df["II_BRL"]
    df["IPI_BRL"] = df["IPI_rate"] * df["IPI_Base_BRL"]

    # PIS/COFINS (modelo: base = VA + II + IPI)
    df["PIS_COF_Base_BRL"] = df["VA_BRL"] + df["II_BRL"] + df["IPI_BRL"]
    df["PIS_BRL"] = df["PIS_rate"] * df["PIS_COF_Base_BRL"]
    df["COFINS_BRL"] = df["COFINS_rate"] * df["PIS_COF_Base_BRL"]

    # =========================
    # 6) Base do ICMS ("por dentro")
    # =========================
    # Carga DA (Despesas Aduaneiras) que entram na base do ICMS
    df["DA_for_ICMS_BRL"] = 0.0

    # Mapeamento de DA: qual coluna representa cada componente
    da_map = {
        "afrmm": "AFRMM_BRL",
        "siscomex": "Siscomex_BRL",
        # se no futuro quiser incluir outros custos na base, mapeie aqui.
    }

    for da_name in cfg.da_components:
        col = da_map.get(da_name)
        if col is not None and col in df.columns:
            df["DA_for_ICMS_BRL"] += df[col]

    base_icms_numerator = (
        df["VA_BRL"]
        + df["II_BRL"]
        + df["IPI_BRL"]
        + df["PIS_BRL"]
        + df["COFINS_BRL"]
        + df["DA_for_ICMS_BRL"]
    )

    icms_rate = float(cfg.icms_rate)
    if icms_rate > 0:
        df["ICMS_BRL"] = base_icms_numerator * icms_rate / (1.0 - icms_rate)
    else:
        df["ICMS_BRL"] = 0.0

    # =========================
    # 7) Créditos de impostos por item
    # =========================
    df["Tax_Credit_BRL"] = _compute_tax_credits_per_item(df, cfg)

    # Impostos pagos (sem considerar créditos)
    df["Tax_paid_total_BRL"] = (
        df["II_BRL"]
        + df["IPI_BRL"]
        + df["PIS_BRL"]
        + df["COFINS_BRL"]
        + df["ICMS_BRL"]
    )

    # Impostos líquidos (pago - créditos)
    df["net_tax_total"] = df["Tax_paid_total_BRL"] - df["Tax_Credit_BRL"]

    # =========================
    # 8) Custo final por item
    # =========================
    # Total de custos diretos (sem impostos)
    df["Direct_costs_BRL"] = (
        df["FOB_Total_BRL"]
        + df["Freight_BRL"]
        + df["Insurance_BRL"]
        + df["Origin_BRL"]
        + df["THC_Origin_BRL"]
        + df["AFRMM_BRL"]
        + df["Siscomex_BRL"]
        + df["Local_Port_BRL"]
        + df["Truck_BRL"]
        + df["Other_Local_BRL"]
    )

    df["Landed_Cost_BRL"] = df["Direct_costs_BRL"] + df["net_tax_total"]

    # Custo unitário
    df["Unit_Cost_BRL"] = df["Landed_Cost_BRL"] / df["Quantity"].replace(0, 1.0)

    # =========================
    # 9) Resumo do embarque
    # =========================
    summary = {
        "FOB_total_USD": float(fob_total_usd),
        "FOB_total_BRL": float(fob_total_brl),
        "Freight_total_BRL": float(freight_brl_total),
        "Tax_paid_total_BRL": float(df["Tax_paid_total_BRL"].sum()),
        "Tax_credit_total_BRL": float(df["Tax_Credit_BRL"].sum()),
        "Final_cost_BRL": float(df["Landed_Cost_BRL"].sum()),
    }

    return df, summary
