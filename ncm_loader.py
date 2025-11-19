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
    if re.match(r'^\d{4}\.\d{2}\.\d{2}$', code):
        return code.replace('.', '')
    return None


@lru_cache(maxsize=1)
def load_ncm_tec_table(
    tec_path: str = "data/tec.xlsx",
    ncm_path: str = "data/Tabela NCM 2022 com Utrib_Comércio Exterior_vigência 01.10.25.xlsx",
) -> pd.DataFrame:
    """
    Load and merge:
      - TEC.xlsx  (sheet 'TEC') -> II (TEC %) por NCM
      - Tabela NCM + uTrib      -> NCM, uTrib, etc.

    Returns a DataFrame with:
      - NCM8           (8-digit string)
      - II_rate        (0.xx)
      - uTrib_abrev    (abreviatura da unidade)
      - uTrib_desc     (descrição da unidade)
      + anything else from NCM file if needed
    """

    # --- Load TEC (II rates) ---
    tec_raw = pd.read_excel(tec_path, sheet_name="TEC", header=None)

    # Find header row containing 'NCM' and 'DESCRIÇÃO'
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

    # Converte TEC (%) para II_rate 0.xx
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

    # Column names may vary slightly; adjust if needed
    utrib_abrev_col = "uTrib para uso em operações de Exportação (Abreviatura)"
    utrib_desc_col = "Descrição da uTrib utilizada em operações de Exportação"

    ncm_small = ncm[["NCM8", utrib_abrev_col, utrib_desc_col]].rename(
        columns={
            utrib_abrev_col: "uTrib_abrev",
            utrib_desc_col: "uTrib_desc",
        }
    )

    # --- Merge ---
    merged = pd.merge(
        ncm_small,
        tec_small,
        on="NCM8",
        how="left",
    )

    return merged
