from odoo import models

class StockPicking(models.Model):
    _inherit = "stock.picking"

    def action_print_inline_wz(self):
        """Podgląd WZ w przeglądarce"""
        return {
            "type": "ir.actions.act_url",
            "url": "/report/inline/stock.report_deliveryslip/%s" % self.id,
            "target": "new",
        }

    def action_print_download_wz(self):
        """Pobierz WZ jako PDF"""
        return {
            "type": "ir.actions.act_url",
            "url": "/report/download/stock.report_deliveryslip/%s" % self.id,
            "target": "self",
        }