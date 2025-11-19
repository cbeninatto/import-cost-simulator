import re
from functools import lru_cache
from typing import Optional

import pandas as pd


def _extract_ncm8_from_dotted(code: str) -> Optional[str]:
    """
    Converte '0101.21.00' -> '01012100'.
    Retorna None se não bater com o padrão.
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
    tipi_csv_path: str = "data/tipi_ipi_rates.csv",
) -> pd.DataFrame:
    """
    Carrega e integra:
      - TEC.xlsx (sheet 'TEC')        -> alíquota II (TEC %) + descrição por NCM
      - TIPI IPI CSV                  -> alíquota IPI por NCM (tipi_ipi_rates.csv)

    Retorna DataFrame com colunas principais:
      - NCM8          (string, 8 dígitos, sem pontos)
      - NCM_dotted    (string, formato 0000.00.00 conforme TEC)
      - Descricao     (descrição do produto conforme TEC)
      - II_rate       (0.xx)
      - IPI_rate      (0.xx ou NaN se não encontrado na TIPI)
    """

    # -------------------------
    # TEC: II (TEC %) + descrição por NCM
    # -------------------------
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
    tec.columns = tec.iloc[0]  # primeira linha após header_row é o cabeçalho real
    tec = tec[1:]              # remove a linha de cabeçalho duplicada

    tec["NCM8"] = tec["NCM"].apply(_extract_ncm8_from_dotted)
    tec = tec[tec["NCM8"].notna()].copy()

    # Converte TEC (%) para alíquota II (0.xx)
    tec["II_rate"] = (
        tec["TEC (%)"]
        .astype(str)
        .str.replace(",", ".", regex=False)
        .astype(float)
        / 100.0
    )

    # NCM_dotted = coluna original "NCM"
    tec["NCM_dotted"] = tec["NCM"].astype(str).str.strip()

    # Descrição
    tec["Descricao"] = tec["DESCRIÇÃO"].astype(str).str.strip()

    tec_small = tec[["NCM8", "NCM_dotted", "Descricao", "II_rate"]].drop_duplicates()

    # -------------------------
    # TIPI: IPI por NCM (CSV)
    # -------------------------
    try:
        tipi = pd.read_csv(tipi_csv_path, dtype={"NCM8": str})
        tipi["NCM8"] = tipi["NCM8"].astype(str).str.zfill(8)

        tipi_small = tipi[["NCM8", "IPI_rate"]]
    except FileNotFoundError:
        # Se ainda não existir o CSV, apenas segue sem IPI_rate
        tipi_small = pd.DataFrame(columns=["NCM8", "IPI_rate"])

    # -------------------------
    # Merge TEC + TIPI
    # -------------------------
    if not tipi_small.empty:
        merged = tec_small.merge(
            tipi_small,
            on="NCM8",
            how="left",
        )
    else:
        merged = tec_small.copy()
        merged["IPI_rate"] = pd.NA

    return merged
