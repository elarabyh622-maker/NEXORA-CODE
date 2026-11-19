-- Each sale_id identifies one sales line in the cleaned dataset.
-- orders counts sales lines; revenue is stored in integer piastres.
CREATE VIEW monthly_sales AS
SELECT substr(sold_on, 1, 7) AS month,
       COUNT(*) AS orders,
       SUM(revenue_piastres) AS revenue_piastres
FROM sales
GROUP BY substr(sold_on, 1, 7);

-- The comparison uses the previous observed month in monthly_sales.
-- The first row has no comparison. A previous zero still yields a difference.
CREATE VIEW monthly_comparison AS
WITH with_previous AS (
    SELECT month, orders, revenue_piastres,
           LAG(month) OVER (ORDER BY month) AS previous_month,
           LAG(revenue_piastres) OVER (ORDER BY month) AS previous_revenue_piastres
    FROM monthly_sales
)
SELECT month, orders, revenue_piastres, previous_month, previous_revenue_piastres,
       revenue_piastres - previous_revenue_piastres AS change_piastres
FROM with_previous;
