import pandas as pd
import re
from functools import lru_cache


def _extract_ncm8_from_dotted(code: str) -> str | None:
    """
    Convert '0101.21.00' -> '01012100'.
    Returns None if pattern does not match.
    """
    if not isinstance(code, str):
        return None
    code = code.strip()
    if re.match(r"^\d{4}\.\d{2}\.\d{2}$", code):
        return code.replace(".", "")
    return None


@lru_cache(maxsize=1)
def load_ncm_tec_table(
    tec_path: str = "data/tec.xlsx",
    ncm_path: str = "data/Tabela NCM 2022 com Utrib_Comércio Exterior_vigência 01.10.25.xlsx",
    tipi_csv_path: str = "data/tipi_ipi_rates.csv",
) -> pd.DataFrame:
    """
    Load and merge:
      - TEC.xlsx  -> II (TEC %) por NCM
      - Tabela NCM + uTrib
      - TIPI IPI CSV -> IPI_rate por NCM

    Returns DataFrame with:
      - NCM8
      - uTrib_abrev
      - uTrib_desc
      - II_rate
      - IPI_rate (if TIPI CSV exists; otherwise NaN)
    """

    # --- Load TEC (II rates) ---
    tec_raw = pd.read_excel(tec_path, sheet_name="TEC", header=None)

    header_row = None
    for i in range(len(tec_raw)):
        row = list(tec_raw.iloc[i].astype(str))
        if "NCM" in row and "DESCRIÇÃO" in row:
            header_row = i
            break

    if header_row is None:
        raise RuntimeError("Não foi possível encontrar o cabeçalho (NCM / DESCRIÇÃO) na planilha TEC.")

    tec = tec_raw.iloc[header_row:].copy()
    tec.columns = tec.iloc[0]
    tec = tec[1:]

    tec["NCM8"] = tec["NCM"].apply(_extract_ncm8_from_dotted)
    tec = tec[tec["NCM8"].notna()].copy()

    tec["II_rate"] = (
        tec["TEC (%)"]
        .astype(str)
        .str.replace(",", ".", regex=False)
        .astype(float)
        / 100.0
    )

    tec_small = tec[["NCM8", "II_rate"]].drop_duplicates()

    # --- Load NCM + uTrib ---
    ncm = pd.read_excel(ncm_path, sheet_name="NCM X uTrib_Vig 1-10-2025")
    ncm["NCM8"] = ncm["NCM"].astype(str).str.zfill(8)

    utrib_abrev_col = "uTrib para uso em operações de Exportação (Abreviatura)"
    utrib_desc_col = "Descrição da uTrib utilizada em operações de Exportação"

    ncm_small = ncm[["NCM8", utrib_abrev_col, utrib_desc_col]].rename(
        columns={
            utrib_abrev_col: "uTrib_abrev",
            utrib_desc_col: "uTrib_desc",
        }
    )

    merged = pd.merge(
        ncm_small,
        tec_small,
        on="NCM8",
        how="left",
    )

    # --- Load TIPI IPI CSV (optional) ---
    try:
        tipi = pd.read_csv(tipi_csv_path, dtype={"NCM8": str})
        # Ensure NCM8 is clean 8-digit string
        tipi["NCM8"] = tipi["NCM8"].astype(str).str.zfill(8)

        merged = merged.merge(
            tipi[["NCM8", "IPI_rate"]],
            on="NCM8",
            how="left",
        )
    except FileNotFoundError:
        # If the CSV is not there yet, we simply don't add IPI_rate
        merged["IPI_rate"] = pd.NA

    return merged
