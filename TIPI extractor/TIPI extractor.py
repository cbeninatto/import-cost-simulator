import streamlit as st
import pdfplumber
import pandas as pd
import re
from io import BytesIO


st.set_page_config(page_title="Extrator TIPI → CSV", page_icon="📑")

st.title("📑 Extrator TIPI para CSV")
st.markdown("""
Envie o PDF completo da **TIPI** e o sistema vai gerar um arquivo **tipi.csv** com as colunas:

- `NCM`
- `Descricao`
- `Aliquota`

Somente serão consideradas linhas em que o **NCM** está no formato `0000.00.00`
(ex.: `2204.30.00 Outros mostos de uvas 10`).
""")

uploaded_file = st.file_uploader("Selecione o PDF da TIPI", type=["pdf"])


def extract_tipi_from_pdf(pdf_bytes: bytes) -> pd.DataFrame:
    """
    Lê o PDF da TIPI e extrai apenas as linhas com:
    NCM no formato 0000.00.00 + DESCRIÇÃO + ALÍQUOTA (0 / 5 / NT etc.)
    """
    # Ex.: 2204.30.00 Outros mostos de uvas 10
    pattern = re.compile(r'^(\d{4}\.\d{2}\.\d{2})\s+(.+?)\s+(NT|\d+)\s*$')

    rows = []

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            if not text:
                continue

            for raw_line in text.splitlines():
                line = raw_line.strip()
                match = pattern.match(line)
                if match:
                    ncm, descricao, aliquota = match.groups()

                    # Normalizar espaços na descrição
                    descricao = re.sub(r'\s+', ' ', descricao).strip()

                    rows.append(
                        {
                            "NCM": ncm,
                            "Descricao": descricao,
                            "Aliquota": aliquota,
                        }
                    )

    df = pd.DataFrame(rows)

    if not df.empty:
        df = df.sort_values("NCM").reset_index(drop=True)

    return df


if uploaded_file is not None:
    pdf_bytes = uploaded_file.read()

    with st.spinner("🔎 Extraindo dados da TIPI..."):
        try:
            df = extract_tipi_from_pdf(pdf_bytes)
        except Exception as e:
            st.error(f"Erro ao processar o PDF: {e}")
        else:
            if df.empty:
                st.warning(
                    "Nenhuma linha com NCM no formato 0000.00.00 foi encontrada.\n"
                    "Verifique se o PDF é a TIPI completa e se o layout não foi alterado."
                )
            else:
                st.success(
                    f"✅ Extração concluída — {len(df)} linhas "
                    f"({df['NCM'].nunique()} códigos NCM únicos)."
                )

                st.subheader("Pré-visualização (primeiras 100 linhas)")
                st.dataframe(df.head(100))

                csv_bytes = df.to_csv(index=False).encode("utf-8-sig")

                st.download_button(
                    "⬇️ Baixar tipi.csv",
                    data=csv_bytes,
                    file_name="tipi.csv",
                    mime="text/csv",
                )
else:
    st.info("Envie o PDF da TIPI para iniciar a extração.")
