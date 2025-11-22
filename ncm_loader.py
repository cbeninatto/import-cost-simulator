import re
from functools import lru_cache

import pandas as pd


@lru_cache(maxsize=1)
def load_ncm_tec_table(combined_path: str = "data/combined_taxes.csv") -> pd.DataFrame:
    """
    Load full NCM/II/IPI table from combined_taxes.csv.

    Returns a DataFrame with columns:
      - NCM_dotted   (original NCM, with dots)
      - Descricao    (DESCRICAO from file)
      - II_rate      (0.xx)
      - IPI_rate     (0.xx)
      - digits       (only digits from NCM)
      - digits_len   (len(digits))
    """
    # encoding='utf-8-sig' strips BOM from first column header if present (﻿NCM)
    df = pd.read_csv(combined_path, dtype=str, encoding="utf-8-sig")

    # Normalize column names (strip whitespace)
    df.columns = [c.strip() for c in df.columns]

    if "NCM" not in df.columns or "DESCRICAO" not in df.columns:
        raise RuntimeError(
            "combined_taxes.csv must have columns 'NCM' and 'DESCRICAO'. "
            f"Colunas encontradas: {list(df.columns)}"
        )

    # digits and level
    df["digits"] = df["NCM"].astype(str).str.replace(r"\D", "", regex=True)
    df["digits_len"] = df["digits"].str.len()

    # II: treat as percentage (0, 2, 4, 10) -> 0.xx
    if "II" in df.columns:
        df["II_rate"] = pd.to_numeric(df["II"], errors="coerce").fillna(0.0) / 100.0
    else:
        df["II_rate"] = 0.0

    def _parse_ipi(value) -> float:
        """
        Parse IPI from combined_taxes.csv:
          - 'NT'  => 0.0
          - '10'  => 0.10
          - '5,5' => 0.055
          - empty/NaN => 0.0
        """
        if value is None:
            return 0.0
        s = str(value).strip().upper()
        if not s or s == "NAN":
            return 0.0
        if "NT" in s:
            return 0.0
        m = re.search(r"\d+(?:[.,]\d+)?", s)
        if not m:
            return 0.0
        num = float(m.group(0).replace(",", "."))
        return num / 100.0

    # IPI: parse via helper
    if "IPI" in df.columns:
        df["IPI_rate"] = df["IPI"].map(_parse_ipi)
    else:
        df["IPI_rate"] = 0.0

    # Rename columns for app
    df = df.rename(columns={"NCM": "NCM_dotted", "DESCRICAO": "Descricao"})

    # enforce types
    df["NCM_dotted"] = df["NCM_dotted"].astype(str)
    df["Descricao"] = df["Descricao"].astype(str)
    df["II_rate"] = df["II_rate"].astype(float)
    df["IPI_rate"] = df["IPI_rate"].astype(float)

    return df
