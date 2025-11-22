from dataclasses import dataclass
from typing import List, Dict, Tuple
import pandas as pd


@dataclass
class ShipmentConfig:
    state_destination: str
    mode: str
    fx_rate_usd_brl: float
    freight_international_usd: float
    insurance_usd: float
    insurance_pct: float
    origin_charges_usd: float
    thc_origin_usd: float
    afrmm_pct: float
    siscomex_brl: float
    local_port_costs_brl: float
    trucking_brl: float
    other_local_costs_brl: float
    regime: str          # 'simples', 'presumido', 'real'
    purpose: str         # 'resale' (mercadorias) or 'asset'
    icms_rate: float
    da_components: List[str]
    va_components: List[str]
    allocation_method: str  # currently only 'FOB'


def compute_landed_cost(items_df: pd.DataFrame, cfg: ShipmentConfig) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """Compute import taxes, credits and landed cost per item + summary.

    items_df is expected to have columns:
      - NCM
      - Description
      - Quantity
      - FOB_Unit_USD
      - II_rate
      - IPI_rate
      - PIS_rate
      - COFINS_rate
      - ICMS_rate (ignored; cfg.icms_rate is used)
    """
    df = items_df.copy().reset_index(drop=True)

    # Ensure numeric columns
    num_cols = [
        "Quantity",
        "FOB_Unit_USD",
        "II_rate",
        "IPI_rate",
        "PIS_rate",
        "COFINS_rate",
        "ICMS_rate",
    ]
    for c in num_cols:
        if c not in df.columns:
            df[c] = 0.0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    # Basic FOB values
    df["FOB_Total_USD"] = df["FOB_Unit_USD"] * df["Quantity"]
    df["FOB_Total_BRL"] = df["FOB_Total_USD"] * cfg.fx_rate_usd_brl

    FOB_total_USD = df["FOB_Total_USD"].sum()
    FOB_total_BRL = df["FOB_Total_BRL"].sum()

    if FOB_total_BRL > 0:
        df["share"] = df["FOB_Total_BRL"] / FOB_total_BRL
    else:
        df["share"] = 1.0 / max(len(df), 1)

    # Shared costs (total, in BRL)
    freight_brl = cfg.freight_international_usd * cfg.fx_rate_usd_brl

    if cfg.insurance_usd and cfg.insurance_usd > 0:
        insurance_brl = cfg.insurance_usd * cfg.fx_rate_usd_brl
    else:
        insurance_brl = cfg.insurance_pct * FOB_total_BRL

    origin_brl = cfg.origin_charges_usd * cfg.fx_rate_usd_brl
    thc_brl = cfg.thc_origin_usd * cfg.fx_rate_usd_brl

    afrmm_brl = cfg.afrmm_pct * freight_brl
    siscomex_brl = cfg.siscomex_brl

    local_port_brl = cfg.local_port_costs_brl
    trucking_brl = cfg.trucking_brl
    other_local_brl = cfg.other_local_costs_brl

    # Allocate shared costs by FOB share
    df["Freight_BRL"] = freight_brl * df["share"]
    df["Insurance_BRL"] = insurance_brl * df["share"]
    df["Origin_BRL"] = origin_brl * df["share"]
    df["THC_BRL"] = thc_brl * df["share"]

    df["AFRMM_BRL"] = afrmm_brl * df["share"]
    df["Siscomex_BRL"] = siscomex_brl * df["share"]

    df["Local_Port_BRL"] = local_port_brl * df["share"]
    df["Other_Local_BRL"] = other_local_brl * df["share"]
    df["Truck_BRL"] = trucking_brl * df["share"]

    # CIF / Valor Aduaneiro (simplified)
    df["CIF_BRL"] = (
        df["FOB_Total_BRL"]
        + df["Freight_BRL"]
        + df["Insurance_BRL"]
        + df["Origin_BRL"]
        + df["THC_BRL"]
    )

    # Import taxes
    df["II_BRL"] = df["CIF_BRL"] * df["II_rate"]
    df["PIS_BRL"] = df["CIF_BRL"] * df["PIS_rate"]
    df["COFINS_BRL"] = df["CIF_BRL"] * df["COFINS_rate"]

    # IPI base: CIF + II  (simplified, ignoring IOF)
    df["IPI_base_BRL"] = df["CIF_BRL"] + df["II_BRL"]
    df["IPI_BRL"] = df["IPI_base_BRL"] * df["IPI_rate"]

    # Despesas aduaneiras (DA) relevantes para ICMS: AFRMM + Siscomex
    df["DA_BRL"] = df["AFRMM_BRL"] + df["Siscomex_BRL"]

    # ICMS: base = (CIF + II + IPI + PIS + COFINS + DA) / (1 - ICMS)
    icms_rate = cfg.icms_rate
    base_icms_numerator = (
        df["CIF_BRL"]
        + df["II_BRL"]
        + df["IPI_BRL"]
        + df["PIS_BRL"]
        + df["COFINS_BRL"]
        + df["DA_BRL"]
    )
    if icms_rate >= 1.0:
        df["ICMS_base_BRL"] = base_icms_numerator
        df["ICMS_BRL"] = 0.0
    else:
        df["ICMS_base_BRL"] = base_icms_numerator / (1.0 - icms_rate)
        df["ICMS_BRL"] = df["ICMS_base_BRL"] - base_icms_numerator

    # Local costs not in DA
    df["Local_Non_DA_BRL"] = df["Local_Port_BRL"] + df["Other_Local_BRL"]

    # Gross tax burden (paid)
    df["Tax_paid_BRL"] = (
        df["II_BRL"]
        + df["IPI_BRL"]
        + df["PIS_BRL"]
        + df["COFINS_BRL"]
        + df["ICMS_BRL"]
    )

    # =========================
    # Tax credits by regime (simplified model)
    # =========================
    eligible_for_credits = cfg.purpose == "resale"

    ipi_credit = pd.Series(0.0, index=df.index)
    pis_credit = pd.Series(0.0, index=df.index)
    cofins_credit = pd.Series(0.0, index=df.index)
    icms_credit = pd.Series(0.0, index=df.index)

    regime = cfg.regime.lower()

    if regime == "simples":
        # No credits in this simplified model
        pass

    elif regime == "presumido":
        if eligible_for_credits:
            # Simplified: credit IPI and ICMS on mercadorias
            ipi_credit = df["IPI_BRL"]
            icms_credit = df["ICMS_BRL"]

    elif regime == "real":
        if eligible_for_credits:
            # Simplified non-cumulative model:
            # credit IPI, PIS, COFINS and ICMS on mercadorias
            ipi_credit = df["IPI_BRL"]
            pis_credit = df["PIS_BRL"]
            cofins_credit = df["COFINS_BRL"]
            icms_credit = df["ICMS_BRL"]

    df["IPI_credit_BRL"] = ipi_credit
    df["PIS_credit_BRL"] = pis_credit
    df["COFINS_credit_BRL"] = cofins_credit
    df["ICMS_credit_BRL"] = icms_credit

    df["Tax_credit_BRL"] = (
        df["IPI_credit_BRL"]
        + df["PIS_credit_BRL"]
        + df["COFINS_credit_BRL"]
        + df["ICMS_credit_BRL"]
    )

    df["net_tax_total"] = df["Tax_paid_BRL"] - df["Tax_credit_BRL"]

    # Landed cost per item (full: CIF + taxes + DA + custos locais + caminhão)
    df["Landed_Cost_BRL"] = (
        df["CIF_BRL"]
        + df["II_BRL"]
        + df["IPI_BRL"]
        + df["PIS_BRL"]
        + df["COFINS_BRL"]
        + df["ICMS_BRL"]
        + df["DA_BRL"]
        + df["Local_Non_DA_BRL"]
        + df["Truck_BRL"]
    )

    df["Unit_Cost_BRL"] = df["Landed_Cost_BRL"] / df["Quantity"].replace(0, pd.NA)
    df["Unit_Cost_BRL"] = df["Unit_Cost_BRL"].fillna(0.0)

    # =========================
    # Summary
    # =========================
    FOB_total_BRL = FOB_total_BRL
    VA_total_BRL = df["CIF_BRL"].sum()
    Tax_paid_total_BRL = df["Tax_paid_BRL"].sum()
    Tax_credit_total_BRL = df["Tax_credit_BRL"].sum()
    Net_tax_total_BRL = df["net_tax_total"].sum()
    Landed_total_BRL = df["Landed_Cost_BRL"].sum()
    Truck_total_BRL = df["Truck_BRL"].sum()
    Freight_total_BRL = df["Freight_BRL"].sum()
    total_qty = df["Quantity"].sum()

    # Custo Final (como você pediu): CIF + impostos - créditos
    Final_cost_BRL = VA_total_BRL + Tax_paid_total_BRL - Tax_credit_total_BRL

    # Fator antigo (FOB em R$) – ainda disponível caso queira
    if FOB_total_BRL > 0:
        FOB_to_Brazil_factor = Landed_total_BRL / FOB_total_BRL
    else:
        FOB_to_Brazil_factor = 0.0

    # Novo Multiplicador: Landed_total_BRL / FOB_total_USD (sem converter o denominador)
    if FOB_total_USD > 0:
        FOB_to_Brazil_multiplier = Landed_total_BRL / FOB_total_USD
    else:
        FOB_to_Brazil_multiplier = 0.0

    if total_qty > 0:
        Avg_unit_cost_BRL = Landed_total_BRL / total_qty
    else:
        Avg_unit_cost_BRL = 0.0

    summary = {
        "FOB_total_USD": float(FOB_total_USD),
        "FOB_total_BRL": float(FOB_total_BRL),
        "VA_total_BRL": float(VA_total_BRL),
        "Tax_paid_total_BRL": float(Tax_paid_total_BRL),
        "Tax_credit_total_BRL": float(Tax_credit_total_BRL),
        "Net_tax_total_BRL": float(Net_tax_total_BRL),
        "Landed_total_BRL": float(Landed_total_BRL),
        "Truck_total_BRL": float(Truck_total_BRL),
        "Freight_total_BRL": float(Freight_total_BRL),
        "Final_cost_BRL": float(Final_cost_BRL),
        "FOB_to_Brazil_factor": float(FOB_to_Brazil_factor),
        "FOB_to_Brazil_multiplier": float(FOB_to_Brazil_multiplier),
        "Avg_unit_cost_BRL": float(Avg_unit_cost_BRL),
        # Breakdown of credits by tax (useful for UI if needed)
        "IPI_credit_total_BRL": float(df["IPI_credit_BRL"].sum()),
        "PIS_credit_total_BRL": float(df["PIS_credit_BRL"].sum()),
        "COFINS_credit_total_BRL": float(df["COFINS_credit_BRL"].sum()),
        "ICMS_credit_total_BRL": float(df["ICMS_credit_BRL"].sum()),
    }

    return df, summary
