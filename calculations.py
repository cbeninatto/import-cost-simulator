from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

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

    regime: str      # 'simples', 'presumido', 'real'
    purpose: str     # 'resale', 'consumption'

    icms_rate: float

    da_components: List[str] = field(default_factory=lambda: ["afrmm", "siscomex"])
    va_components: List[str] = field(default_factory=lambda: ["freight", "insurance", "origin_charges", "thc_origin"])
    allocation_method: str = "FOB"


def compute_tax_credits(
    regime: str,
    purpose: str,
    taxes: Dict[str, float],
    options: Optional[Dict[str, bool]] = None
) -> Dict[str, float]:
    II = taxes.get("II", 0.0)
    IPI = taxes.get("IPI", 0.0)
    PIS = taxes.get("PIS", 0.0)
    COFINS = taxes.get("COFINS", 0.0)
    ICMS = taxes.get("ICMS", 0.0)

    # default options
    opts = {
        "ipi_credit_enabled": False,
        "pis_cofins_credit_enabled": False,
        "icms_credit_enabled": False,
    }
    if options:
        opts.update(options)

    credit_II = 0.0

    # default flags
    ipi_enabled = False
    pis_cofins_enabled = False
    icms_enabled = False

    if regime == "simples":
        # no credits by default
        ipi_enabled = False
        pis_cofins_enabled = False
        icms_enabled = False

    elif regime == "presumido":
        if purpose == "resale":
            ipi_enabled = opts.get("ipi_credit_enabled", False)
            pis_cofins_enabled = False
            icms_enabled = True
        else:
            ipi_enabled = False
            pis_cofins_enabled = False
            icms_enabled = False

    elif regime == "real":
        if purpose == "resale":
            ipi_enabled = opts.get("ipi_credit_enabled", True)
            pis_cofins_enabled = opts.get("pis_cofins_credit_enabled", True)
            icms_enabled = opts.get("icms_credit_enabled", True)
        else:
            ipi_enabled = False
            pis_cofins_enabled = False
            icms_enabled = False

    credit_IPI = IPI if (ipi_enabled and purpose == "resale") else 0.0
    credit_PIS = PIS if (pis_cofins_enabled and purpose == "resale") else 0.0
    credit_COFINS = COFINS if (pis_cofins_enabled and purpose == "resale") else 0.0
    credit_ICMS = ICMS if (icms_enabled and purpose == "resale") else 0.0

    net_II = II - credit_II
    net_IPI = IPI - credit_IPI
    net_PIS = PIS - credit_PIS
    net_COFINS = COFINS - credit_COFINS
    net_ICMS = ICMS - credit_ICMS

    return {
        "credit_II": credit_II,
        "credit_IPI": credit_IPI,
        "credit_PIS": credit_PIS,
        "credit_COFINS": credit_COFINS,
        "credit_ICMS": credit_ICMS,
        "net_II": net_II,
        "net_IPI": net_IPI,
        "net_PIS": net_PIS,
        "net_COFINS": net_COFINS,
        "net_ICMS": net_ICMS,
        "net_tax_total": net_II + net_IPI + net_PIS + net_COFINS + net_ICMS,
    }


def _compute_shares(df: pd.DataFrame, method: str) -> pd.Series:
    if method == "WEIGHT" and "Gross_Weight_kg" in df.columns:
        base = df["Gross_Weight_kg"].fillna(0.0)
        if base.sum() == 0:
            base = df["FOB_Total_BRL"]
    elif method == "CIF" and "CIF_BRL" in df.columns:
        base = df["CIF_BRL"]
    else:  # default FOB
        base = df["FOB_Total_BRL"]
    total = base.sum()
    if total == 0:
        return pd.Series([0.0] * len(df), index=df.index)
    return base / total


def compute_landed_cost(
    items_df: pd.DataFrame,
    cfg: ShipmentConfig,
    tax_options: Optional[Dict[str, bool]] = None
) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """
    items_df expected columns:
      - NCM
      - Description
      - Quantity
      - FOB_Unit_USD
      - (optional) Gross_Weight_kg
      - (optional) II_rate, IPI_rate, PIS_rate, COFINS_rate, ICMS_rate
    """
    df = items_df.copy()

    # Basic FOB totals
    df["Quantity"] = df["Quantity"].astype(float)
    df["FOB_Unit_USD"] = df["FOB_Unit_USD"].astype(float)
    df["FOB_Total_USD"] = df["FOB_Unit_USD"] * df["Quantity"]
    df["FOB_Total_BRL"] = df["FOB_Total_USD"] * cfg.fx_rate_usd_brl

    # Shared costs in BRL
    freight_brl = cfg.freight_international_usd * cfg.fx_rate_usd_brl

    # insurance: if 0 and pct > 0, compute on FOB total USD
    insurance_usd = cfg.insurance_usd
    if insurance_usd == 0 and cfg.insurance_pct > 0:
        insurance_usd = cfg.insurance_pct * df["FOB_Total_USD"].sum()
    insurance_brl = insurance_usd * cfg.fx_rate_usd_brl

    origin_brl = cfg.origin_charges_usd * cfg.fx_rate_usd_brl
    thc_origin_brl = cfg.thc_origin_usd * cfg.fx_rate_usd_brl

    afrmm_brl = 0.0
    if cfg.mode.lower().startswith("fcl") or cfg.mode.lower() == "lcl":
        afrmm_brl = cfg.afrmm_pct * freight_brl

    # CIF / Valor Aduaneiro
    df["CIF_BRL"] = df["FOB_Total_BRL"]
    shares_for_va = _compute_shares(df, cfg.allocation_method)

    def alloc(component_total: float) -> pd.Series:
        return shares_for_va * component_total

    if "freight" in cfg.va_components:
        df["CIF_BRL"] += alloc(freight_brl)
    if "insurance" in cfg.va_components:
        df["CIF_BRL"] += alloc(insurance_brl)
    if "origin_charges" in cfg.va_components:
        df["CIF_BRL"] += alloc(origin_brl)
    if "thc_origin" in cfg.va_components:
        df["CIF_BRL"] += alloc(thc_origin_brl)

    # Despesas aduaneiras (DA) for ICMS base
    siscomex_brl = cfg.siscomex_brl
    da_total = 0.0
    if "afrmm" in cfg.da_components:
        da_total += afrmm_brl
    if "siscomex" in cfg.da_components:
        da_total += siscomex_brl

    df["FOB_Total_BRL"] = df["FOB_Total_BRL"].fillna(0.0)
    shares_for_da = _compute_shares(df, cfg.allocation_method)
    df["DA_BRL"] = shares_for_da * da_total

    # Tax rates (if missing, default to 0 for now; user can fill them in the UI)
    for col in ["II_rate", "IPI_rate", "PIS_rate", "COFINS_rate", "ICMS_rate"]:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = df[col].fillna(0.0).astype(float)

    # Compute taxes per item
    df["II_BRL"] = df["CIF_BRL"] * df["II_rate"]
    df["IPI_Base_BRL"] = df["CIF_BRL"] + df["II_BRL"]
    df["IPI_BRL"] = df["IPI_Base_BRL"] * df["IPI_rate"]
    df["PIS_BRL"] = df["CIF_BRL"] * df["PIS_rate"]
    df["COFINS_BRL"] = df["CIF_BRL"] * df["COFINS_rate"]

    # ICMS per item (por dentro)
    df["S_for_ICMS"] = (
        df["CIF_BRL"]
        + df["II_BRL"]
        + df["IPI_BRL"]
        + df["PIS_BRL"]
        + df["COFINS_BRL"]
        + df["DA_BRL"]
    )

    # effective ICMS rate: item-specific or global
    df["ICMS_rate_effective"] = df["ICMS_rate"]
    df.loc[df["ICMS_rate_effective"] == 0.0, "ICMS_rate_effective"] = cfg.icms_rate

    def calc_icms(row):
        rate = row["ICMS_rate_effective"]
        if rate <= 0 or rate >= 1:
            return 0.0
        return row["S_for_ICMS"] * rate / (1.0 - rate)

    df["ICMS_BRL"] = df.apply(calc_icms, axis=1)

    # Tax credits & net tax cost
    credits = {
        "credit_II": [],
        "credit_IPI": [],
        "credit_PIS": [],
        "credit_COFINS": [],
        "credit_ICMS": [],
        "net_II": [],
        "net_IPI": [],
        "net_PIS": [],
        "net_COFINS": [],
        "net_ICMS": [],
        "net_tax_total": [],
    }

    for _, row in df.iterrows():
        taxes = {
            "II": row["II_BRL"],
            "IPI": row["IPI_BRL"],
            "PIS": row["PIS_BRL"],
            "COFINS": row["COFINS_BRL"],
            "ICMS": row["ICMS_BRL"],
        }
        result = compute_tax_credits(cfg.regime, cfg.purpose, taxes, tax_options)
        for k in credits.keys():
            credits[k].append(result[k])

    for k, vals in credits.items():
        df[k] = vals

    df["Tax_Paid_Total_BRL"] = (
        df["II_BRL"]
        + df["IPI_BRL"]
        + df["PIS_BRL"]
        + df["COFINS_BRL"]
        + df["ICMS_BRL"]
    )

    df["Local_Non_DA_BRL"] = alloc(cfg.local_port_costs_brl + cfg.other_local_costs_brl)
    df["Truck_BRL"] = alloc(cfg.trucking_brl)

    df["Landed_Cost_BRL"] = (
        df["CIF_BRL"]
        + df["net_tax_total"]
        + df["Local_Non_DA_BRL"]
        + df["Truck_BRL"]
    )

    df["Unit_Cost_BRL"] = df["Landed_Cost_BRL"] / df["Quantity"]

    # Shipment summary
    summary = {
        "FOB_total_BRL": df["FOB_Total_BRL"].sum(),
        "VA_total_BRL": df["CIF_BRL"].sum(),
        "Tax_paid_total_BRL": df["Tax_Paid_Total_BRL"].sum(),
        "Tax_credit_total_BRL": (
            df["credit_IPI"].sum()
            + df["credit_PIS"].sum()
            + df["credit_COFINS"].sum()
            + df["credit_ICMS"].sum()
        ),
        "Net_tax_total_BRL": df["net_tax_total"].sum(),
        "Local_non_DA_total_BRL": df["Local_Non_DA_BRL"].sum(),
        "Truck_total_BRL": df["Truck_BRL"].sum(),
        "Landed_total_BRL": df["Landed_Cost_BRL"].sum(),
    }

    if summary["FOB_total_BRL"] > 0:
        summary["FOB_to_Brazil_factor"] = (
            summary["Landed_total_BRL"] / summary["FOB_total_BRL"]
        )
    else:
        summary["FOB_to_Brazil_factor"] = 0.0

    return df, summary

