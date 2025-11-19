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
      - TEC.xlsx (sheet 'TEC')        -> alíquota II (TEC %) + descrição por NCM  (OBRIGATÓRIO)
      - TIPI IPI CSV                  -> alíquota IPI por NCM (tipi_ipi_rates.csv) (OPCIONAL)

    Retorna DataFrame com colunas principais:
      - NCM8          (string, 8 dígitos, sem pontos)
      - NCM_dotted    (string, formato 0000.00.00 conforme TEC)
      - Descricao     (descrição do produto conforme TEC)
      - II_rate       (0.xx)
      - IPI_rate      (0.xx; 0.0 se TIPI não for carregada / não tiver valor)
    """

    # ======================================================
    # 1) TEC: II (TEC %) + descrição por NCM  (OBRIGATÓRIO)
    # ======================================================
    try:
        tec_raw = pd.read_excel(tec_path, sheet_name="TEC", header=None)
    except FileNotFoundError as e:
        raise FileNotFoundError(
            f"Arquivo TEC não encontrado em '{tec_path}'. "
            f"Confirme se o arquivo foi enviado para a pasta data/ com esse nome."
        ) from e
    except ValueError as e:
        # Problema com nome da planilha
        raise ValueError(
            "Não foi possível encontrar a planilha 'TEC' dentro de tec.xlsx. "
            "Confirme o nome da aba no arquivo TEC."
        ) from e

    header_row = None
    for i in range(len(tec_raw)):
        row = list(tec_raw.iloc[i].astype(str))
        if "NCM" in row and "DESCRIÇÃO" in row:
            header_row = i
            break

    if header_row is None:
        raise RuntimeError(
            "Não foi possível encontrar o cabeçalho (NCM / DESCRIÇÃO) na planilha TEC. "
            "Verifique se o layout da planilha é o mesmo do arquivo oficial."
        )

    tec = tec_raw.iloc[header_row:].copy()
    tec.columns = tec.iloc[0]  # primeira linha após header_row é o cabeçalho real
    tec = tec[1:]              # remove a linha de cabeçalho duplicada

    # Normaliza NCM em formato 8 dígitos
    tec["NCM8"] = tec["NCM"].apply(_extract_ncm8_from_dotted)
    tec = tec[tec["NCM8"].notna()].copy()

    # ---- Parse robusto de TEC (%) ----
    # Alguns valores vêm como '10', '10#', '16**', '0BIT', '14BK' etc.
    tec_str = tec["TEC (%)"].astype(str).str.replace(",", ".", regex=False)
    num = tec_str.str.extract(r"(\d+(?:\.\d+)?)", expand=False)
    tec["II_rate"] = pd.to_numeric(num, errors="coerce").fillna(0.0) / 100.0

    # NCM_dotted = coluna original "NCM"
    tec["NCM_dotted"] = tec["NCM"].astype(str).str.strip()

    # Descrição
    tec["Descricao"] = tec["DESCRIÇÃO"].astype(str).str.strip()

    tec_small = tec[["NCM8", "NCM_dotted", "Descricao", "II_rate"]].drop_duplicates()

    # Se, por algum motivo bizarro, não sobrar linha nenhuma, devolve DF vazio
    if tec_small.empty:
        return pd.DataFrame(columns=["NCM8", "NCM_dotted", "Descricao", "II_rate", "IPI_rate"])

    # ======================================================
    # 2) TIPI: IPI por NCM (CSV)  (OPCIONAL)
    # ======================================================
    ipi_df = None
    try:
        # Se o arquivo não existir ou der erro, vamos ignorar TIPI e seguir só com II
        ipi_df = pd.read_csv(tipi_csv_path, dtype={"NCM8": str})
    except FileNotFoundError:
        ipi_df = None
    except Exception:
        # Qualquer outro erro de parsing: considera TIPI indisponível
        ipi_df = None

    if ipi_df is not None and not ipi_df.empty:
        # Garante coluna NCM8
        if "NCM8" not in ipi_df.columns and "NCM" in ipi_df.columns:
            # Tenta derivar NCM8 a partir de NCM (com ou sem pontos)
            def _norm_ncm(val: str) -> str:
                val = str(val)
                digits = "".join(ch for ch in val if ch.isdigit())
                return digits[:8].ljust(8, "0")

            ipi_df["NCM8"] = ipi_df["NCM"].apply(_norm_ncm)

        ipi_df["NCM8"] = ipi_df["NCM8"].astype(str).str.zfill(8)

        # Descobre qual coluna parece ser IPI_rate
        ipi_col = None
        for c in ipi_df.columns:
            if c.lower().strip() in ("ipi_rate", "ipi", "aliquota_ipi", "aliquota"):
                ipi_col = c
                break
        if ipi_col is None:
            # tenta achar algo que contenha 'ipi'
            for c in ipi_df.columns:
                if "ipi" in c.lower():
                    ipi_col = c
                    break

        if ipi_col is not None:
            # Normaliza para 0.xx
            raw = ipi_df[ipi_col].astype(str).str.replace(",", ".", regex=False)
            num_ipi = raw.str.extract(r"(\d+(?:\.\d+)?)", expand=False)
            ipi_df["IPI_rate"] = pd.to_numeric(num_ipi, errors="coerce") / 100.0
        else:
            # Se não achou coluna, trata como sem TIPI
            ipi_df = None

    # ======================================================
    # 3) MERGE TEC + TIPI (se disponível)
    # ======================================================
    if ipi_df is not None and "IPI_rate" in ipi_df.columns:
        ipi_small = ipi_df[["NCM8", "IPI_rate"]].drop_duplicates()
        merged = tec_small.merge(ipi_small, on="NCM8", how="left")
    else:
        merged = tec_small.copy()
        merged["IPI_rate"] = 0.0  # sem TIPI, considera IPI 0 para auto-preenchimento

    # Garante tipos numéricos
    merged["II_rate"] = merged["II_rate"].fillna(0.0).astype(float)
    merged["IPI_rate"] = merged["IPI_rate"].fillna(0.0).astype(float)

    return merged
