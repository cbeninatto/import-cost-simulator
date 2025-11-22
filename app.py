        # =========================
        # RESUMO DO EMBARQUE
        # =========================
        st.subheader("Resumo do embarque")

        col1, col2 = st.columns(2)
        with col1:
            st.metric("FOB total (R$)", f"{summary['FOB_total_BRL']:,.2f}")
            st.metric("Valor aduaneiro total (R$)", f"{summary['VA_total_BRL']:,.2f}")
            st.metric("Custo total landed (R$)", f"{summary['Landed_total_BRL']:,.2f}")
            st.metric(
                "Fator FOB → Custo Brasil",
                f"{summary['FOB_to_Brazil_factor']:,.2f}x",
            )
        with col2:
            st.metric("Impostos pagos (R$)", f"{summary['Tax_paid_total_BRL']:,.2f}")
            st.metric(
                "Créditos de impostos (R$)", f"{summary['Tax_credit_total_BRL']:,.2f}",
            )
            st.metric(
                "Custo líquido de impostos (R$)",
                f"{summary['Net_tax_total_BRL']:,.2f}",
            )
            st.metric(
                "Frete rodoviário total (R$)",
                f"{summary.get('Truck_total_BRL', 0):,.2f}",
            )
