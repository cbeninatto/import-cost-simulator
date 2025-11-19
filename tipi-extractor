import streamlit as st
import pandas as pd
import pdfplumber
import re
from io import BytesIO


st.set_page_config(page_title="TIPI → CSV Extractor", page_icon="📑")

st.title("📑 TIPI → CSV Extractor")
st.markdown(
    """
Upload the official **TIPI PDF** and this app will generate a **tipi.csv** file with:

- `NCM` (only codes in the format `0000.00.00`)
- `Descricao`
- `Aliquota` (e.g. `0`, `10`, `NT`)

The parser is designed to handle **multi-line descriptions**, where the NCM appears on one line and the rate (`0`, `10`, `NT`, etc.) may appear at the end of the next line.
"""
)


uploaded_file = st.file_uploader("Select the TIPI PDF", type=["pdf"])


def extract_tipi_from_pdf(pdf_bytes: bytes) -> pd.DataFrame:
    """
    Extract rows from the TIPI PDF where NCM is in 0000.00.00 format,
    capturing DESCRIPTION (which may span multiple lines) and ALIQUOTA.

    Strategy:
    1) If a line matches: NCM + description + aliquota on the SAME line,
       we capture it directly.
    2) If a line only has NCM + partial description (no aliquota),
       we start a 'pending block' and look at subsequent lines to find
       the aliquota at the end of one of those lines.
    """

    # e.g. "2204.30.00 Outros mostos de uvas 10"
    ncm_full = re.compile(r"^(\d{4}\.\d{2}\.\d{2})\s+(.+?)\s+(NT|\d+)\s*$")
    # e.g. "2204.30.00  ..." but *no* explicit aliquota at the end
    ncm_only = re.compile(r"^(\d{4}\.\d{2}\.\d{2})\b")

    rows = []
    current = None  # pending block when description continues to next lines

    def normalize_description(parts):
        desc = " ".join(parts)
        desc = re.sub(r"\s+", " ", desc).strip(" -")
        return desc

    def finalize_current(cur):
        return {
            "NCM": cur["ncm"],
            "Descricao": normalize_description(cur["desc_parts"]),
            "Aliquota": cur["aliquota"],
        }

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page_index, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue

            for raw_line in text.splitlines():
                line = raw_line.rstrip()
                stripped = line.strip()
                if not stripped:
                    continue

                # 1) Try the full pattern (NCM + description + aliquota all on one line)
                m_full = ncm_full.match(stripped)
                if m_full:
                    # If there is a pending block that already has aliquota, push it
                    if current and current.get("aliquota"):
                        rows.append(finalize_current(current))
                    current = None  # reset block

                    ncm, desc, aliquota = m_full.groups()
                    rows.append(
                        {
                            "NCM": ncm,
                            "Descricao": normalize_description([desc]),
                            "Aliquota": aliquota,
                        }
                    )
                    continue

                # 2) Try a line that starts with NCM but without aliquota at the end
                m_ncm = ncm_only.match(stripped)
                if m_ncm:
                    # If there is a previous pending block that has aliquota, finalize it
                    if current and current.get("aliquota"):
                        rows.append(finalize_current(current))

                    ncm = m_ncm.group(1)
                    rest = stripped[m_ncm.end() :].strip()
                    current = {
                        "ncm": ncm,
                        "desc_parts": [rest] if rest else [],
                        "aliquota": None,
                    }
                    continue

                # 3) Non-NCM line: could be continuation of a pending block
                if current:
                    tokens = stripped.split()
                    if not tokens:
                        continue

                    last = tokens[-1]

                    # If the last token looks like an aliquota, treat it as such
                    if re.fullmatch(r"(NT|\d+)", last):
                        aliquota = last
                        desc_extra = " ".join(tokens[:-1])
                        if desc_extra:
                            current["desc_parts"].append(desc_extra)

                        current["aliquota"] = aliquota
                        rows.append(finalize_current(current))
                        current = None
                    else:
                        # Just more description text
                        current["desc_parts"].append(stripped)

    # End of PDF: if there's a pending block with aliquota, finalize it
    if current and current.get("aliquota"):
        rows.append(finalize_current(current))

    # Remove potential duplicates
    unique = {(r["NCM"], r["Descricao"], r["Aliquota"]): r for r in rows}
    rows = list(unique.values())

    # Sort by NCM
    rows.sort(key=lambda r: r["NCM"])

    df = pd.DataFrame(rows, columns=["NCM", "Descricao", "Aliquota"])
    return df


if uploaded_file is not None:
    pdf_bytes = uploaded_file.read()

    with st.spinner("🔎 Extracting TIPI data..."):
        try:
            df = extract_tipi_from_pdf(pdf_bytes)
        except Exception as e:
            st.error(f"Error while processing PDF: {e}")
        else:
            if df.empty:
                st.warning(
                    "No rows found with NCM in the format 0000.00.00.\n"
                    "Check if the PDF is the official TIPI and if the layout matches the expected structure."
                )
            else:
                st.success(
                    f"✅ Extraction finished — {len(df)} rows "
                    f"({df['NCM'].nunique()} unique NCM codes)."
                )

                st.subheader("Preview (first 100 rows)")
                st.dataframe(df.head(100))

                csv_bytes = df.to_csv(index=False).encode("utf-8-sig")

                st.download_button(
                    "⬇️ Download tipi.csv",
                    data=csv_bytes,
                    file_name="tipi.csv",
                    mime="text/csv",
                )
else:
    st.info("Upload the TIPI PDF to start the extraction.")
