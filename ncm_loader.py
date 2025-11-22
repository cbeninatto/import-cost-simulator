import re
from functools import lru_cache
from typing import Optional

import pandas as pd


def _digits_only(code: str) -> str:
    """Return only the digits from an NCM string."""
    return "".join(ch for ch in str(code) if ch.isdigit())


def _extract_ncm8(code: str) -> Optional[str]:
    """
    Accepts '0000.00.00' or '00000000' and returns an 8-digit NCM (string) or None.
    Used only for final NCMs (leaf codes).
    """
    if code is None:
        return None
    s = str(code).strip()
    digits = _digits_only(s)
    if len(digits) != 8:
        return None
    return digits


def _parse_ipi(value) -> float:
    """
    Parse IPI from combined_taxes.csv:
      - 'NT'  => 0.0
      - '10'  => 0.10
      - '5,5' => 0.055
      - empty/NaN => 0.0
    """
    s = str(value).strip().upper()
    if not s or s == "NAN":
        return 0.0
    if "NT" in s:  # não tributado
        return 0.0
    m = re.search(r"\d+(?:[.,]\d+)?", s)
    if not m:
        return 0.0
    num = float(m.group(0).replace(",", "."))
    return num / 100.0


@lru_cache(maxsize=1)
def load_ncm_tec_table(
    combined_path: str = "data/combined_taxes.csv",
) -> pd.DataFrame:
    """
    Build the main NCM table for the app from:

      - combined_taxes.csv (NCM, DESCRICAO, II, IPI)

    Returns a DataFrame with one row per final NCM (0000.00.00):

      - NCM8        (digits only, 8 chars)
      - NCM_dotted  (0000.00.00)
      - Descricao   (hierarchical description, using 00.00 / 0000.0 / 0000.00 + leaf)
      - II_rate     (0.xx from II column)
      - IPI_rate    (0.xx from IPI column)
    """

    # =========================
    # 1) Load combined_taxes.csv
    # =========================
    df = pd.read_csv(combined_path, dtype={"NCM": str})

    if "NCM" not in df.columns or "DESCRICAO" not in df.columns:
        raise RuntimeError(
            "combined_taxes.csv must have at least the columns 'NCM' and 'DESCRICAO'."
        )

    # Normalize NCM to digits and classify by length
    df["digits"] = df["NCM"].astype(str).str.replace(r"\D", "", regex=True)
    df["digits_len"] = df["digits"].str.len()

    # Levels:
    #  4 → 00.00  (chapter)
    #  5 → 0000.0
    #  6 → 0000.00
    #  8 → 0000.00.00 (final NCM)
    lvl4 = df[df["digits_len"] == 4].copy()
    lvl5 = df[df["digits_len"] == 5].copy()
    lvl6 = df[df["digits_len"] == 6].copy()
    leaves = df[df["digits_len"] == 8].copy()

    if leaves.empty:
        raise RuntimeError(
            "No leaf NCMs (len(digits) == 8) were found in combined_taxes.csv. "
            "Check if the file structure is correct."
        )

    # Build maps for descriptions by level
    map4 = (
        lvl4.drop_duplicates("digits")
        .set_index("digits")["DESCRICAO"]
        .to_dict()
    )
    map5 = (
        lvl5.drop_duplicates("digits")
        .set_index("digits")["DESCRICAO"]
        .to_dict()
    )
    map6 = (
        lvl6.drop_duplicates("digits")
        .set_index("digits")["DESCRICAO"]
        .to_dict()
    )

    # =========================
    # 2) Build hierarchical description for each leaf
    # =========================
    full_desc_list = []
    for _, row in leaves.iterrows():
        d = row["digits"]
        parts = []

        d4 = d[:4]
        d5 = d[:5]
        d6 = d[:6]

        # 00.00 level
        if d4 in map4:
            parts.append(str(map4[d4]).strip())
        # 0000.0 level
        if d5 in map5:
            parts.append(str(map5[d5]).strip())
        # 0000.00 level
        if d6 in map6:
            parts.append(str(map6[d6]).strip())

        # leaf description (0000.00.00)
        leaf_desc = str(row.get("DESCRICAO", "")).strip()
        if leaf_desc:
            parts.append(leaf_desc)

        full_desc = " › ".join(p for p in parts if p)
        full_desc_list.append(full_desc)

    leaves["Descricao"] = full_desc_list

    # NCM8 and NCM_dotted
    leaves["NCM8"] = leaves["digits"].astype(str)
    leaves["NCM_dotted"] = leaves["NCM"].astype(str)

    # =========================
    # 3) Parse II and IPI rates
    # =========================
    # II: treat as percentage (0, 2, 4, 10) → 0.xx
    if "II" in leaves.columns:
        leaves["II_rate"] = (
            pd.to_numeric(leaves["II"], errors="coerce").fillna(0.0) / 100.0
        )
    else:
        leaves["II_rate"] = 0.0

    # IPI: use helper (NT → 0; numbers → % → 0.xx)
    if "IPI" in leaves.columns:
        leaves["IPI_rate"] = leaves["IPI"].map(_parse_ipi)
    else:
        leaves["IPI_rate"] = 0.0

    # Final DataFrame for the app
    result = leaves[["NCM8", "NCM_dotted", "Descricao", "II_rate", "IPI_rate"]].copy()

    # Ensure types
    result["NCM8"] = result["NCM8"].astype(str)
    result["NCM_dotted"] = result["NCM_dotted"].astype(str)
    result["Descricao"] = result["Descricao"].astype(str)
    result["II_rate"] = result["II_rate"].astype(float)
    result["IPI_rate"] = result["IPI_rate"].astype(float)

    return result
