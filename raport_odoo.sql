SELECT
    to_char(sp.date_done, 'IYYY-IW') AS tydzien_zdania,
    so.name AS sale_order,
    sol.name AS produkt,
    sp.date_done AS data_zdania,
    SUM(sml.quantity_product_uom * sol.price_unit * (1 - sol.discount / 100)) AS wartosc_wydana
FROM
    stock_picking sp
JOIN
    stock_picking_type spt ON spt.id = sp.picking_type_id
JOIN
    stock_move sm ON sm.picking_id = sp.id
JOIN
    stock_move_line sml ON sml.move_id = sm.id
JOIN
    sale_order_line sol ON sol.id = sm.sale_line_id
JOIN
    sale_order so ON so.id = sol.order_id
WHERE
    sp.state = 'done'
    AND spt.code = 'outgoing'
    AND sp.date_done IS NOT NULL
GROUP BY
    tydzien_zdania,
    sale_order,
    produkt,
    data_zdania
ORDER BY
    data_zdania desc;