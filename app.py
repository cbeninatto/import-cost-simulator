def solve_reverse_fob_for_item(base_df: pd.DataFrame,
                               cfg: ShipmentConfig,
                               item_idx,
                               target_unit_brl: float,
                               max_iter: int = 40,
                               tol: float = 0.01):
    """
    Given:
      - base_df: DataFrame used as input to compute_landed_cost (FOB_Unit_USD, Qtd, NCM etc.)
      - cfg: ShipmentConfig for this simulation
      - item_idx: index of the item we want to adjust
      - target_unit_brl: desired unit landed cost in BRL

    Returns:
      (fob_exact_usd, achieved_unit_brl) or (None, None) if infeasible.
    """

    # 1) Cost with FOB = 0 (minimum possible, only taxes & shared costs)
    df_min = base_df.copy()
    df_min.loc[item_idx, "FOB_Unit_USD"] = 0.0

    per_min, _ = compute_landed_cost(df_min, cfg)
    cost_min = float(per_min.loc[item_idx, "Unit_Cost_BRL"])

    # If even with FOB = 0 we are already above target, no solution
    if target_unit_brl <= cost_min + tol:
        return 0.0, cost_min

    # 2) Choose an upper bound for FOB and expand until we pass target
    current_fob = float(base_df.loc[item_idx, "FOB_Unit_USD"])
    if current_fob <= 0:
        high = 1.0
    else:
        high = current_fob * 2.0

    cost_high = None
    for _ in range(25):
        df_high = base_df.copy()
        df_high.loc[item_idx, "FOB_Unit_USD"] = high
        per_high, _ = compute_landed_cost(df_high, cfg)
        cost_high = float(per_high.loc[item_idx, "Unit_Cost_BRL"])
        if cost_high >= target_unit_brl:
            break
        high *= 2.0

    # If even with a very high FOB we never reach target, we just return that
    if cost_high is not None and cost_high < target_unit_brl - tol:
        return high, cost_high

    low = 0.0
    best_fob = high
    best_cost = cost_high

    # 3) Binary search between 0 and high
    for _ in range(max_iter):
        mid = (low + high) / 2.0
        df_mid = base_df.copy()
        df_mid.loc[item_idx, "FOB_Unit_USD"] = mid
        per_mid, _ = compute_landed_cost(df_mid, cfg)
        cost_mid = float(per_mid.loc[item_idx, "Unit_Cost_BRL"])

        # Track best approximation
        if abs(cost_mid - target_unit_brl) < abs(best_cost - target_unit_brl):
            best_fob, best_cost = mid, cost_mid

        if cost_mid >= target_unit_brl:
            high = mid
        else:
            low = mid

        if abs(cost_mid - target_unit_brl) <= tol:
            break

    return best_fob, best_cost
