import os
import re
import pdfplumber
import pandas as pd


BASE_DIR = os.path.dirname(os.path.dirname(__file__))  # repo root
DATA_DIR = os.path.join(BASE_DIR, "data")

TIPI_PDF = os.path.join(
    DATA_DIR,
    "TABELA DE INCIDÊNCIA DO IMPOSTO SOBRE PRODUTOS INDUSTRIALIZADOS (TIPI).pdf",
)
OUTPUT_CSV = os.path.join(DATA_DIR, "tipi_ipi_rates.csv")


def extract_tipi_ipi():
    """
    Parse TIPI PDF and build a CSV with:
      - NCM8      (8-digit NCM, no dots)
      - NCM       (dotted)
      - IPI_raw   (original string found, e.g. '10,00', '0,00', 'NT')
      - IPI_rate  (float 0.xx, None if not parsed)
    """

    if not os.path.exists(TIPI_PDF):
        raise FileNotFoundError(f"TIPI PDF not found at: {TIPI_PDF}")

    rows = []

    # Example line pattern: "0101.21.00  Descrição longa ... 10,00 %"
    pattern_ncm = re.compile(r"\b(\d{4}\.\d{2}\.\d{2})\b")
    pattern_rate = re.compile(r"(\d{1,2},\d{2})\s*%")  # like 10,00 %

    print(f"Opening TIPI PDF: {TIPI_PDF}")

    with pdfplumber.open(TIPI_PDF) as pdf:
        num_pages = len(pdf.pages)
        print(f"TIPI has {num_pages} pages. Parsing...")

        for page_index, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text()
            except Exception as e:
                print(f"Warning: could not extract text from page {page_index}: {e}")
                continue

            if not text:
                continue

            for line in text.splitlines():
                line_stripped = line.strip()
                m_ncm = pattern_ncm.search(line_stripped)
                if not m_ncm:
                    continue

                ncm_dotted = m_ncm.group(1)
                ncm8 = ncm_dotted.replace(".", "")

                # Find all numeric percentages on the line (there may be more than one)
                rates = pattern_rate.findall(line_stripped)
                ipi_raw = None
                ipi_rate = None

                if rates:
                    ipi_raw = rates[-1]  # take the last % in the line
                    try:
                        ipi_rate = float(ipi_raw.replace(",", ".")) / 100.0
                    except Exception:
                        ipi_rate = None
                else:
                    # Look for textual markers: NT (não tributado), 0,00 etc.
                    if "NT" in line_stripped:
                        ipi_raw = "NT"
                        ipi_rate = 0.0
                    elif "0,00" in line_stripped:
                        ipi_raw = "0,00"
                        ipi_rate = 0.0

                rows.append(
                    {
                        "page": page_index,
                        "NCM8": ncm8,
                        "NCM": ncm_dotted,
                        "IPI_raw": ipi_raw,
                        "IPI_rate": ipi_rate,
                        "line": line_stripped,
                    }
                )

            if page_index % 10 == 0:
                print(f"Processed page {page_index}/{num_pages}...")

    if not rows:
        raise RuntimeError("No NCM/IPI lines found in TIPI PDF. Check patterns.")

    df = pd.DataFrame(rows)

    # Deduplicate by NCM8: pick the first non-null IPI_rate (based on page order)
    df_sorted = df.sort_values(["NCM8", "page"])
    agg = (
        df_sorted.groupby("NCM8")
        .agg(
            {
                "NCM": "first",
                "IPI_raw": "first",
                "IPI_rate": "first",
            }
        )
        .reset_index()
    )

    print(f"Extracted {len(agg)} unique NCM records with IPI info.")

    os.makedirs(DATA_DIR, exist_ok=True)
    agg.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    print(f"Saved TIPI IPI table to: {OUTPUT_CSV}")


if __name__ == "__main__":
    extract_tipi_ipi()
