from odoo import models, fields, api

class SaleOrder(models.Model):
    _inherit = "sale.order"

    client_order_ref = fields.Char(string="Nr obcy zamówienia")
    client_project_number = fields.Char(string="Nr projektu klienta")
    client_requested_date = fields.Date(string="Data życzona klienta")

    @api.onchange("client_requested_date")
    def _onchange_client_requested_date(self):
        if self.client_requested_date:
            self.commitment_date = self.client_requested_date

    @api.model
    def create(self, vals):
        if vals.get("client_requested_date") and not vals.get("commitment_date"):
            vals["commitment_date"] = vals["client_requested_date"]
        return super().create(vals)

    def write(self, vals):
        if "client_requested_date" in vals and vals["client_requested_date"]:
            vals["commitment_date"] = vals["client_requested_date"]
        return super().write(vals) 