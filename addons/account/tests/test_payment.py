from flectra.addons.account.tests.account_test_classes import AccountingTestCase
import time

class TestPayment(AccountingTestCase):

    def setUp(self):
        super(TestPayment, self).setUp()
        self.register_payments_model = self.env['account.register.payments']
        self.payment_model = self.env['account.payment']
        self.invoice_model = self.env['account.invoice']
        self.invoice_line_model = self.env['account.invoice.line']
        self.acc_bank_stmt_model = self.env['account.bank.statement']
        self.acc_bank_stmt_line_model = self.env['account.bank.statement.line']

        self.partner_agrolait = self.env.ref("base.res_partner_2")
        self.partner_china_exp = self.env.ref("base.res_partner_3")
        self.currency_chf_id = self.env.ref("base.CHF").id
        self.currency_usd_id = self.env.ref("base.USD").id
        self.currency_eur_id = self.env.ref("base.EUR").id

        company = self.env.ref('base.main_company')
        self.cr.execute("UPDATE res_company SET currency_id = %s WHERE id = %s", [self.currency_eur_id, company.id])
        self.product = self.env.ref("product.product_product_4")
        self.payment_method_manual_in = self.env.ref("account.account_payment_method_manual_in")
        self.payment_method_manual_out = self.env.ref("account.account_payment_method_manual_out")

        self.account_receivable = self.env['account.account'].search([('user_type_id', '=', self.env.ref('account.data_account_type_receivable').id)], limit=1)
        self.account_payable = self.env['account.account'].search([('user_type_id', '=', self.env.ref('account.data_account_type_payable').id)], limit=1)
        self.account_revenue = self.env['account.account'].search([('user_type_id', '=', self.env.ref('account.data_account_type_revenue').id)], limit=1)

        self.bank_journal_euro = self.env['account.journal'].create({'name': 'Bank', 'type': 'bank', 'code': 'BNK67'})
        self.account_eur = self.bank_journal_euro.default_debit_account_id

        self.cash_journal_euro = self.env['account.journal'].create({'name': 'Cash', 'type': 'cash', 'code': 'CASH'})

        self.bank_journal_usd = self.env['account.journal'].create({'name': 'Bank US', 'type': 'bank', 'code': 'BNK68', 'currency_id': self.currency_usd_id})
        self.account_usd = self.bank_journal_usd.default_debit_account_id

        self.transfer_account = self.env['res.users'].browse(self.env.uid).company_id.transfer_account_id
        self.diff_income_account = self.env['res.users'].browse(self.env.uid).company_id.income_currency_exchange_account_id
        self.diff_expense_account = self.env['res.users'].browse(self.env.uid).company_id.expense_currency_exchange_account_id

    def create_invoice(self, amount=100, type='out_invoice', currency_id=None, partner=None, account_id=None):
        """ Returns an open invoice """
        invoice = self.invoice_model.create({
            'partner_id': partner or self.partner_agrolait.id,
            'reference_type': 'none',
            'currency_id': currency_id or self.currency_eur_id,
            'name': type,
            'account_id': account_id or self.account_receivable.id,
            'type': type,
            'date_invoice': time.strftime('%Y') + '-06-26',
        })
        self.invoice_line_model.create({
            'product_id': self.product.id,
            'quantity': 1,
            'price_unit': amount,
            'invoice_id': invoice.id,
            'name': 'something',
            'account_id': self.account_revenue.id,
        })
        invoice.action_invoice_open()
        return invoice

    def reconcile(self, liquidity_aml, amount=0.0, amount_currency=0.0, currency_id=None):
        """ Reconcile a journal entry corresponding to a payment with its bank statement line """
        bank_stmt = self.acc_bank_stmt_model.create({
            'journal_id': liquidity_aml.journal_id.id,
            'date': time.strftime('%Y') + '-07-15',
        })
        bank_stmt_line = self.acc_bank_stmt_line_model.create({
            'name': 'payment',
            'statement_id': bank_stmt.id,
            'partner_id': self.partner_agrolait.id,
            'amount': amount,
            'amount_currency': amount_currency,
            'currency_id': currency_id,
            'date': time.strftime('%Y') + '-07-15'
        })

        amount_in_widget = currency_id and amount_currency or amount
        bank_stmt_line.process_reconciliation(payment_aml_rec=liquidity_aml)
        return bank_stmt

    def check_journal_items(self, aml_recs, aml_dicts):
        def compare_rec_dict(aml_rec, aml_dict):
            return aml_rec.account_id.id == aml_dict['account_id'] \
                and round(aml_rec.debit, 2) == aml_dict['debit'] \
                and round(aml_rec.credit, 2) == aml_dict['credit'] \
                and round(aml_rec.amount_currency, 2) == aml_dict['amount_currency'] \
                and aml_rec.currency_id.id == aml_dict['currency_id']

        for aml_dict in aml_dicts:
            # There is no unique key to identify journal items (an account_payment may create several lines
            # in the same account), so to check the expected entries are created, we check there is a line
            # matching for each dict of expected values
            aml_rec = aml_recs.filtered(lambda r: compare_rec_dict(r, aml_dict))
            self.assertEqual(len(aml_rec), 1, "Expected a move line with values : %s" % str(aml_dict))
            if aml_dict.get('currency_diff'):
                if aml_rec.credit:
                    currency_diff_move = aml_rec.matched_debit_ids[0].full_reconcile_id.exchange_move_id
                else:
                    currency_diff_move = aml_rec.matched_credit_ids[0].full_reconcile_id.exchange_move_id
                for currency_diff_line in currency_diff_move.line_ids:
                    if aml_dict.get('currency_diff') > 0:
                        if currency_diff_line.account_id.id == aml_rec.account_id.id:
                            self.assertAlmostEquals(currency_diff_line.debit, aml_dict.get('currency_diff'))
                        else:
                            self.assertAlmostEquals(currency_diff_line.credit, aml_dict.get('currency_diff'))
                            self.assertIn(currency_diff_line.account_id.id, [self.diff_expense_account.id, self.diff_income_account.id])
                    else:
                        if currency_diff_line.account_id.id == aml_rec.account_id.id:
                            self.assertAlmostEquals(currency_diff_line.credit, abs(aml_dict.get('currency_diff')))
                        else:
                            self.assertAlmostEquals(currency_diff_line.debit, abs(aml_dict.get('currency_diff')))
                            self.assertIn(currency_diff_line.account_id.id, [self.diff_expense_account.id, self.diff_income_account.id])

    def test_full_payment_process(self):
        """ Create a payment for two invoices, post it and reconcile it with a bank statement """
        inv_1 = self.create_invoice(amount=100, currency_id=self.currency_eur_id, partner=self.partner_agrolait.id)
        inv_2 = self.create_invoice(amount=200, currency_id=self.currency_eur_id, partner=self.partner_agrolait.id)

        ctx = { 'active_model': 'account.invoice', 'active_ids': [inv_1.id, inv_2.id] }
        register_payments = self.register_payments_model.with_context(ctx).create({
            'payment_date': time.strftime('%Y') + '-07-15',
            'journal_id': self.bank_journal_euro.id,
            'payment_method_id': self.payment_method_manual_in.id,
        })
        register_payments.create_payments()
        payment = self.payment_model.search([], order="id desc", limit=1)

        self.assertAlmostEquals(payment.amount, 300)
        self.assertEqual(payment.state, 'posted')
        self.assertEqual(payment.state, 'posted')
        self.assertEqual(inv_1.state, 'paid')
        self.assertEqual(inv_2.state, 'paid')

        self.check_journal_items(payment.move_line_ids, [
            {'account_id': self.account_eur.id, 'debit': 300.0, 'credit': 0.0, 'amount_currency': 0, 'currency_id': False},
            {'account_id': inv_1.account_id.id, 'debit': 0.0, 'credit': 300.0, 'amount_currency': 00, 'currency_id': False},
        ])
        self.assertTrue(payment.move_line_ids.filtered(lambda l: l.account_id == inv_1.account_id)[0].full_reconcile_id)

        liquidity_aml = payment.move_line_ids.filtered(lambda r: r.account_id == self.account_eur)
        bank_statement = self.reconcile(liquidity_aml, 200, 0, False)

        self.assertEqual(liquidity_aml.statement_id, bank_statement)
        self.assertEqual(liquidity_aml.statement_line_id, bank_statement.line_ids[0])

        self.assertEqual(payment.state, 'reconciled')

    def test_internal_transfer_journal_usd_journal_eur(self):
        """ Create a transfer from a EUR journal to a USD journal """
        payment = self.payment_model.create({
            'payment_date': time.strftime('%Y') + '-07-15',
            'payment_type': 'transfer',
            'amount': 50,
            'currency_id': self.currency_usd_id,
            'journal_id': self.bank_journal_usd.id,
            'destination_journal_id': self.bank_journal_euro.id,
            'payment_method_id': self.payment_method_manual_out.id,
        })
        payment.post()
        self.check_journal_items(payment.move_line_ids, [
            {'account_id': self.transfer_account.id, 'debit': 32.70, 'credit': 0.0, 'amount_currency': 50, 'currency_id': self.currency_usd_id},
            {'account_id': self.transfer_account.id, 'debit': 0.0, 'credit': 32.70, 'amount_currency': -50, 'currency_id': self.currency_usd_id},
            {'account_id': self.account_eur.id, 'debit': 32.70, 'credit': 0.0, 'amount_currency': 0, 'currency_id': False},
            {'account_id': self.account_usd.id, 'debit': 0.0, 'credit': 32.70, 'amount_currency': -50, 'currency_id': self.currency_usd_id},
        ])

    def test_payment_chf_journal_usd(self):
        payment = self.payment_model.create({
            'payment_date': time.strftime('%Y') + '-07-15',
            'payment_type': 'outbound',
            'amount': 50,
            'currency_id': self.currency_chf_id,
            'journal_id': self.bank_journal_usd.id,
            'partner_type': 'supplier',
            'partner_id': self.partner_china_exp.id,
            'payment_method_id': self.payment_method_manual_out.id,
        })
        payment.post()

        self.check_journal_items(payment.move_line_ids, [
            {'account_id': self.account_usd.id, 'debit': 0.0, 'credit': 38.21, 'amount_currency': -58.42, 'currency_id': self.currency_usd_id},
            {'account_id': self.partner_china_exp.property_account_payable_id.id, 'debit': 38.21, 'credit': 0.0, 'amount_currency': 50, 'currency_id': self.currency_chf_id},
        ])

    def test_multiple_payments_00(self):
        """ Create test to pay several vendor bills/invoices at once """
        # One payment for inv_1 and inv_2 (same partner)
        inv_1 = self.create_invoice(amount=100, currency_id=self.currency_eur_id, partner=self.partner_agrolait.id)
        inv_2 = self.create_invoice(amount=500, currency_id=self.currency_eur_id, partner=self.partner_agrolait.id)
        # One payment for inv_3 (different partner)
        inv_3 = self.create_invoice(amount=200, currency_id=self.currency_eur_id, partner=self.partner_china_exp.id)
        # One payment for inv_4 (Vendor Bill)
        inv_4 = self.create_invoice(amount=50, currency_id=self.currency_eur_id, partner=self.partner_agrolait.id, type='in_invoice')

        ids = [inv_1.id, inv_2.id, inv_3.id, inv_4.id]
        register_payments = self.register_payments_model.with_context(active_ids=ids).create({
            'payment_date': time.strftime('%Y') + '-07-15',
            'journal_id': self.bank_journal_euro.id,
            'payment_method_id': self.payment_method_manual_in.id,
        })
        register_payments.create_payments()
        payment_ids = self.payment_model.search([('invoice_ids', 'in', ids)], order="id desc")

        self.assertEqual(len(payment_ids), 3)
        self.assertAlmostEquals(register_payments.amount, 750)

        inv_1_2_pay = None
        inv_3_pay = None
        inv_4_pay = None
        for payment_id in payment_ids:
            self.assertEqual('posted', payment_id.state)
            if payment_id.partner_id == self.partner_agrolait:
                if payment_id.partner_type == 'supplier':
                    self.assertEqual(payment_id.amount, 50)
                    inv_4_pay = payment_id
                else:
                    self.assertEqual(payment_id.amount, 600)
                    inv_1_2_pay = payment_id
            else:
                self.assertEqual(payment_id.amount, 200)
                inv_3_pay = payment_id

        self.assertIsNotNone(inv_1_2_pay)
        self.assertIsNotNone(inv_3_pay)
        self.assertIsNotNone(inv_4_pay)

        self.check_journal_items(inv_1_2_pay.move_line_ids, [
            {'account_id': self.account_eur.id, 'debit': 600.0, 'credit': 0.0, 'amount_currency': 0.0, 'currency_id': False},
            {'account_id': inv_1.account_id.id, 'debit': 0.0, 'credit': 600.0, 'amount_currency': 0.0, 'currency_id': False},
        ])
        self.assertEqual(inv_1.state, 'paid')
        self.assertEqual(inv_2.state, 'paid')

        self.check_journal_items(inv_3_pay.move_line_ids, [
            {'account_id': self.account_eur.id, 'debit': 200.0, 'credit': 0.0, 'amount_currency': 0.0, 'currency_id': False},
            {'account_id': inv_1.account_id.id, 'debit': 0.0, 'credit': 200.0, 'amount_currency': 0.0, 'currency_id': False},
        ])
        self.assertEqual(inv_3.state, 'paid')

        self.check_journal_items(inv_4_pay.move_line_ids, [
            {'account_id': self.account_eur.id, 'debit': 0.0, 'credit': 50.0, 'amount_currency': 0.0, 'currency_id': False},
            {'account_id': inv_1.account_id.id, 'debit': 50.0, 'credit': 0.0, 'amount_currency': 0.0, 'currency_id': False},
        ])
        self.assertEqual(inv_4.state, 'paid')

    def test_multiple_payments_01(self):
        """ Create test to pay several invoices/refunds at once """
        # One payment for inv_1 and inv_2 (same partner) but inv_2 is refund
        inv_1 = self.create_invoice(amount=550, currency_id=self.currency_eur_id, partner=self.partner_agrolait.id)
        inv_2 = self.create_invoice(amount=100, currency_id=self.currency_eur_id, partner=self.partner_agrolait.id, type='out_refund')

        ids = [inv_1.id, inv_2.id]
        register_payments = self.register_payments_model.with_context(active_ids=ids).create({
            'payment_date': time.strftime('%Y') + '-07-15',
            'journal_id': self.bank_journal_euro.id,
            'payment_method_id': self.payment_method_manual_in.id,
        })
        register_payments.create_payments()
        payment_id = self.payment_model.search([('invoice_ids', 'in', ids)], order="id desc")

        self.assertEqual(len(payment_id), 1)
        self.assertAlmostEquals(register_payments.amount, 450)

        self.assertEqual(payment_id.state, 'posted')

        self.check_journal_items(payment_id.move_line_ids, [
            {'account_id': self.account_eur.id, 'debit': 450.0, 'credit': 0.0, 'amount_currency': 0.0, 'currency_id': False},
            {'account_id': inv_1.account_id.id, 'debit': 0.0, 'credit': 450.0, 'amount_currency': 0.0, 'currency_id': False},
        ])

    def test_partial_payment(self):
        """ Create test to pay invoices (cust. inv + vendor bill) with partial payment """
        # Test Customer Invoice
        inv_1 = self.create_invoice(amount=600, currency_id=self.currency_eur_id, partner=self.partner_agrolait.id)
        ids = [inv_1.id]
        register_payments = self.register_payments_model.with_context(active_ids=ids).create({
            'payment_date': time.strftime('%Y') + '-07-15',
            'journal_id': self.bank_journal_euro.id,
            'payment_method_id': self.payment_method_manual_in.id,
        })

        # Perform the partial payment by setting the amount at 550 instead of 600
        register_payments.amount = 550

        register_payments.create_payments()
        payment_ids = self.payment_model.search([('invoice_ids', 'in', ids)], order="id desc")

        self.assertEqual(len(payment_ids), 1)

        payment_id = payment_ids[0]

        self.assertEqual(payment_id.invoice_ids[0].id, inv_1.id)
        self.assertAlmostEquals(payment_id.amount, 550)
        self.assertEqual(payment_id.payment_type, 'inbound')
        self.assertEqual(payment_id.partner_id, self.partner_agrolait)
        self.assertEqual(payment_id.partner_type, 'customer')

        # Test Vendor Bill
        inv_2 = self.create_invoice(amount=500, currency_id=self.currency_eur_id, type='in_invoice', partner=self.partner_china_exp.id)
        ids = [inv_2.id]
        register_payments = self.register_payments_model.with_context(active_ids=ids).create({
            'payment_date': time.strftime('%Y') + '-07-15',
            'journal_id': self.bank_journal_euro.id,
            'payment_method_id': self.payment_method_manual_in.id,
        })

        # Perform the partial payment by setting the amount at 300 instead of 500
        register_payments.amount = 300

        register_payments.create_payments()
        payment_ids = self.payment_model.search([('invoice_ids', 'in', ids)], order="id desc")

        self.assertEqual(len(payment_ids), 1)

        payment_id = payment_ids[0]

        self.assertEqual(payment_id.invoice_ids[0].id, inv_2.id)
        self.assertAlmostEquals(payment_id.amount, 300)
        self.assertEqual(payment_id.payment_type, 'outbound')
        self.assertEqual(payment_id.partner_id, self.partner_china_exp)
        self.assertEqual(payment_id.partner_type, 'supplier')

    def test_payment_and_writeoff_in_other_currency_1(self):
        # Use case:
        # Company is in EUR, create a customer invoice for 25 EUR and register payment of 25 USD.
        # Mark invoice as fully paid with a write_off
        # Check that all the aml are correctly created.
        invoice = self.create_invoice(amount=25, type='out_invoice', currency_id=self.currency_eur_id, partner=self.partner_agrolait.id)
        # register payment on invoice
        payment = self.payment_model.create({'payment_type': 'inbound',
            'payment_method_id': self.env.ref('account.account_payment_method_manual_in').id,
            'partner_type': 'customer',
            'partner_id': self.partner_agrolait.id,
            'amount': 25,
            'currency_id': self.currency_usd_id,
            'payment_date': time.strftime('%Y') + '-07-15',
            'payment_difference_handling': 'reconcile',
            'writeoff_account_id': self.account_payable.id,
            'journal_id': self.bank_journal_euro.id,
            'invoice_ids': [(4, invoice.id, None)]
            })
        payment.post()
        self.check_journal_items(payment.move_line_ids, [
            {'account_id': self.account_eur.id, 'debit': 16.35, 'credit': 0.0, 'amount_currency': 25.0, 'currency_id': self.currency_usd_id},
            {'account_id': self.account_payable.id, 'debit': 8.65, 'credit': 0.0, 'amount_currency': 13.22, 'currency_id': self.currency_usd_id},
            {'account_id': self.account_receivable.id, 'debit': 0.0, 'credit': 25.0, 'amount_currency': -38.22, 'currency_id': self.currency_usd_id},
        ])
        # Use case:
        # Company is in EUR, create a vendor bill for 25 EUR and register payment of 25 USD.
        # Mark invoice as fully paid with a write_off
        # Check that all the aml are correctly created.
        invoice = self.create_invoice(amount=25, type='in_invoice', currency_id=self.currency_eur_id, partner=self.partner_agrolait.id)
        # register payment on invoice
        payment = self.payment_model.create({'payment_type': 'inbound',
            'payment_method_id': self.env.ref('account.account_payment_method_manual_in').id,
            'partner_type': 'supplier',
            'partner_id': self.partner_agrolait.id,
            'amount': 25,
            'currency_id': self.currency_usd_id,
            'payment_date': time.strftime('%Y') + '-07-15',
            'payment_difference_handling': 'reconcile',
            'writeoff_account_id': self.account_payable.id,
            'journal_id': self.bank_journal_euro.id,
            'invoice_ids': [(4, invoice.id, None)]
            })
        payment.post()
        self.check_journal_items(payment.move_line_ids, [
            {'account_id': self.account_eur.id, 'debit': 16.35, 'credit': 0.0, 'amount_currency': 25.0, 'currency_id': self.currency_usd_id},
            {'account_id': self.account_payable.id, 'debit': 0.0, 'credit': 8.65, 'amount_currency': -13.22, 'currency_id': self.currency_usd_id},
            {'account_id': self.account_receivable.id, 'debit': 0.0, 'credit': 7.7, 'amount_currency': -11.78, 'currency_id': self.currency_usd_id},
        ])

    def test_payment_and_writeoff_out_refund(self):
        # Use case:
        # Company is in EUR, create a credit note for 100 EUR and register payment of 90.
        # Mark invoice as fully paid with a write_off
        # Check that all the aml are correctly created.
        invoice = self.create_invoice(amount=100, type='out_refund', currency_id=self.currency_eur_id, partner=self.partner_agrolait.id)
        # register payment on invoice
        payment = self.payment_model.create({'payment_type': 'outbound',
            'payment_method_id': self.env.ref('account.account_payment_method_manual_in').id,
            'partner_type': 'customer',
            'partner_id': self.partner_agrolait.id,
            'amount': 90,
            'payment_date': time.strftime('%Y') + '-07-15',
            'payment_difference_handling': 'reconcile',
            'writeoff_account_id': self.account_payable.id,
            'journal_id': self.bank_journal_euro.id,
            'invoice_ids': [(4, invoice.id, None)]
            })
        payment.post()
        self.check_journal_items(payment.move_line_ids, [
            {'account_id': self.account_eur.id, 'debit': 0.0, 'credit': 90.0, 'amount_currency': 0.0, 'currency_id': False},
            {'account_id': self.account_payable.id, 'debit': 0.0, 'credit': 10.0, 'amount_currency': 0.0, 'currency_id': False},
            {'account_id': self.account_receivable.id, 'debit': 100.0, 'credit': 0.0, 'amount_currency': 0.0, 'currency_id': False},
        ])
        self.assertEqual(invoice.state, 'paid')

    def test_payment_cancel_keep_name(self):
        self.bank_journal_euro.update_posted = True

        payment = self.payment_model.create({
            'payment_type': 'inbound',
            'payment_method_id': self.payment_method_manual_in.id,
            'partner_type': 'customer',
            'partner_id': self.partner_agrolait.id,
            'amount': 90,
            'payment_date': time.strftime('%Y') + '-07-15',
            'payment_difference_handling': 'reconcile',
            'journal_id': self.bank_journal_euro.id,
        })

        payment.post()
        self.assertEqual(len(payment.move_line_ids.mapped('move_id')), 1)
        name = payment.move_line_ids.mapped('move_id').name
        self.assertTrue(name)

        payment.cancel()
        self.assertFalse(payment.move_line_ids.mapped('move_id'))
        payment.action_draft()

        payment.post()
        self.assertEqual(len(payment.move_line_ids.mapped('move_id')), 1)
        self.assertEqual(name, payment.move_line_ids.mapped('move_id').name)

    def test_payment_transfer_cancel_keep_names(self):
        self.bank_journal_euro.update_posted = True
        self.cash_journal_euro.update_posted = True

        payment = self.payment_model.create({
            'payment_type': 'transfer',
            'payment_method_id': self.payment_method_manual_out.id,
            'amount': 90,
            'payment_date': time.strftime('%Y') + '-07-15',
            'journal_id': self.bank_journal_euro.id,
            'destination_journal_id': self.cash_journal_euro.id,
        })

        payment.post()
        self.assertEqual(len(payment.move_line_ids.mapped('move_id')), 2)

        all_moves = payment.move_line_ids.mapped('move_id')
        move = all_moves.filtered(lambda m: m.journal_id == self.bank_journal_euro)
        transfer_move = all_moves - move
        self.assertEqual(transfer_move.journal_id, self.cash_journal_euro)

        name = move.name
        transfer_name = transfer_move.name
        self.assertTrue(name)
        self.assertTrue(transfer_name)
        self.assertNotEqual(name, transfer_name)

        reconciled_lines = payment.move_line_ids.filtered(lambda l: l.reconciled)
        self.assertEqual(len(reconciled_lines), 2)
        self.assertEqual(reconciled_lines.mapped('move_id'), all_moves)

        reconciled_lines.remove_move_reconcile()
        payment.cancel()
        self.assertFalse(payment.move_line_ids.mapped('move_id'))
        payment.action_draft()

        payment.post()
        self.assertEqual(len(payment.move_line_ids.mapped('move_id')), 2)

        all_moves = payment.move_line_ids.mapped('move_id')
        move = all_moves.filtered(lambda m: m.journal_id == self.bank_journal_euro)
        transfer_move = all_moves - move
        self.assertEqual(transfer_move.journal_id, self.cash_journal_euro)

        self.assertEqual(name, move.name)
        self.assertEqual(transfer_name, transfer_move.name)

    def test_payment_cancel_to_transfer(self):
        self.bank_journal_euro.update_posted = True

        payment = self.payment_model.create({
            'payment_type': 'inbound',
            'payment_method_id': self.payment_method_manual_in.id,
            'partner_type': 'customer',
            'partner_id': self.partner_agrolait.id,
            'amount': 90,
            'payment_date': time.strftime('%Y') + '-07-15',
            'payment_difference_handling': 'reconcile',
            'journal_id': self.bank_journal_euro.id,
        })

        payment.post()
        self.assertEqual(len(payment.move_line_ids.mapped('move_id')), 1)
        name = payment.move_line_ids.mapped('move_id').name
        self.assertTrue(name)

        payment.cancel()
        self.assertFalse(payment.move_line_ids.mapped('move_id'))
        payment.action_draft()

        payment.write({
            'payment_type': 'transfer',
            'payment_method_id': self.payment_method_manual_out.id,
            'partner_id': False,
            'destination_journal_id': self.cash_journal_euro.id,
        })

        payment.post()
        self.assertEqual(len(payment.move_line_ids.mapped('move_id')), 2)

        all_moves = payment.move_line_ids.mapped('move_id')
        move = all_moves.filtered(lambda m: m.journal_id == self.bank_journal_euro)
        transfer_move = all_moves - move
        self.assertEqual(transfer_move.journal_id, self.cash_journal_euro)

        self.assertEqual(name, move.name)
        self.assertTrue(transfer_move.name)
        self.assertNotEqual(name, transfer_move.name)

    def test_payment_and_writeoff_in_other_currency_2(self):
        # Use case:
        # Company is in EUR, create a supplier bill of 5325.6 USD and register payment of 5325 USD, at a different rate
        # Mark invoice as fully paid with a write_off
        # Check that all the aml are correctly created.
        # Set exchange rates  0.895@2017-11-01 and 0.88@2017-12-01
        self.env['res.currency.rate'].create({
            'currency_id': self.currency_usd_id,
            'rate': 0.895,
            'name': time.strftime('%Y') + '-06-26'})
        self.env['res.currency.rate'].create({
            'currency_id': self.currency_usd_id,
            'rate': 0.88,
            'name': time.strftime('%Y') + '-07-15'})
        invoice = self.create_invoice(amount=5325.6, type='in_invoice', currency_id=self.currency_usd_id, partner=self.partner_agrolait.id)
        self.check_journal_items(invoice.move_id.line_ids, [
            {'account_id': self.account_revenue.id, 'debit': 5950.39, 'credit': 0.0, 'amount_currency': 5325.6, 'currency_id': self.currency_usd_id},
            {'account_id': self.account_receivable.id, 'debit': 0.0, 'credit': 5950.39, 'amount_currency': -5325.6, 'currency_id': self.currency_usd_id},
        ])
        # register payment on invoice
        payment = self.payment_model.create({'payment_type': 'outbound',
            'payment_method_id': self.env.ref('account.account_payment_method_manual_in').id,
            'partner_type': 'supplier',
            'partner_id': self.partner_agrolait.id,
            'amount': 5325,
            'currency_id': self.currency_usd_id,
            'payment_date': time.strftime('%Y') + '-07-15',
            'payment_difference_handling': 'reconcile',
            'writeoff_account_id': self.account_revenue.id,
            'journal_id': self.bank_journal_euro.id,
            'invoice_ids': [(4, invoice.id, None)]
            })
        payment.post()
        self.check_journal_items(payment.move_line_ids, [
            {'account_id': self.account_eur.id, 'debit': 0, 'credit': 6051.14, 'amount_currency': -5325.0, 'currency_id': self.currency_usd_id},
            {'account_id': self.account_revenue.id, 'debit': 0.0, 'credit': 0.68, 'amount_currency': -0.6, 'currency_id': self.currency_usd_id},
            {'account_id': self.account_receivable.id, 'debit': 6051.82, 'credit': 0.0, 'amount_currency': 5325.6, 'currency_id': self.currency_usd_id, 'currency_diff': -101.43},
        ])
        #check the invoice status
        self.assertEqual(invoice.state, 'paid')

    def test_payment_and_writeoff_in_other_currency_3(self):
        # Use case related in revision 20935462a0cabeb45480ce70114ff2f4e91eaf79
        # Invoice made in secondary currency for which the rate to the company currency
        # is higher than the foreign currency decimal precision.
        # E.g: Company currency is EUR, create a customer invoice of 247590.40 EUR and
        #       register payment of 267 USD (1 USD = 948 EUR)
        #      Mark invoice as fully paid with a write_off
        #      Check that all the aml are correctly created and that the invoice is paid
        self.env['res.currency.rate'].create({
            'currency_id': self.currency_usd_id,
            'rate': 1,
            'name': time.strftime('%Y') + '-06-26'})
        self.env['res.currency.rate'].create({
            'currency_id': self.currency_eur_id,
            'rate': 948,
            'name': time.strftime('%Y') + '-06-26'})
        invoice = self.create_invoice(amount=247590.4, type='out_invoice', currency_id=self.currency_eur_id, partner=self.partner_agrolait.id)
        self.check_journal_items(invoice.move_id.line_ids, [
            {'account_id': self.account_receivable.id, 'debit': 247590.4, 'credit': 0.0, 'amount_currency': 0.0, 'currency_id': False},
            {'account_id': self.account_revenue.id, 'debit': 0.0, 'credit': 247590.4, 'amount_currency': 0.0, 'currency_id': False},
        ])
        # register payment on invoice
        payment = self.payment_model.create({'payment_type': 'inbound',
            'payment_method_id': self.env.ref('account.account_payment_method_manual_in').id,
            'partner_type': 'customer',
            'partner_id': self.partner_agrolait.id,
            'amount': 267,
            'currency_id': self.currency_usd_id,
            'payment_date': time.strftime('%Y') + '-06-26',
            'payment_difference_handling': 'reconcile',
            'writeoff_account_id': self.account_revenue.id,
            'journal_id': self.bank_journal_euro.id,
            'invoice_ids': [(4, invoice.id, None)],
            'name': 'test_payment_and_writeoff_in_other_currency_3',
            })
        payment.post()
        self.check_journal_items(payment.move_line_ids, [
            {'account_id': self.account_eur.id, 'debit': 253116.0, 'credit': 0.0, 'amount_currency': 267.0, 'currency_id': self.currency_usd_id},
            {'account_id': self.account_revenue.id, 'debit': 0.0, 'credit': 5526.84, 'amount_currency': -5.83, 'currency_id': self.currency_usd_id},
            {'account_id': self.account_receivable.id, 'debit': 0.0, 'credit': 247589.16, 'amount_currency': -261.17, 'currency_id': self.currency_usd_id},
        ])
        # Check the invoice status and the full reconciliation: the difference on the receivable account
        # should have been completed by an exchange rate difference entry
        self.assertEqual(invoice.state, 'paid')
        self.assertTrue(invoice.move_id.line_ids.filtered(lambda l: l.account_id == self.account_receivable)[0].full_reconcile_id)

    def test_partial_payment_inv_foreign_payment_domestic(self):
        """
            Invoice of 1000$ (foreign $) at 01/01 with foreign exchange rate of 0.50000
            Payment of 500 (domestic ???) at 15/01 with foreign exchange rate of 1.00000
            The residuals should be 500 in foreign and 1500 in domestic.
        """
        company = self.env.ref('base.main_company')
        self.env['res.currency.rate'].search([]).unlink()
        self.env['res.currency.rate'].create({
            'name': time.strftime('%Y') + '-01-01',
            'rate': 1.0,
            'currency_id': self.currency_eur_id,
            'company_id': company.id
        })
        self.env['res.currency.rate'].create({
            'name': time.strftime('%Y') + '-01-01',
            'rate': 0.5,  # Don't change this !
            'currency_id': self.currency_usd_id,
            'company_id': self.env.ref('base.main_company').id
        })
        self.env['res.currency.rate'].create({
            'name': time.strftime('%Y') + '-01-15',
            'rate': 1.0,  # Don't change this !
            'currency_id': self.currency_usd_id,
            'company_id': self.env.ref('base.main_company').id
        })
        inv1 = self.invoice_model.create({
            'partner_id': self.partner_agrolait.id,
            'currency_id': self.currency_usd_id,
            'name': 'out_invoice',
            'account_id': self.account_receivable.id,
            'type': 'out_invoice',
            'date_invoice': time.strftime('%Y') + '-01-01',
        })
        self.invoice_line_model.create({
            'product_id': self.product.id,
            'quantity': 1,
            'price_unit': 1000,
            'invoice_id': inv1.id,
            'name': 'something',
            'account_id': self.account_revenue.id,
        })
        inv1.action_invoice_open()
        payment = self.env['account.payment'].create({
            'payment_date': time.strftime('%Y') + '-01-15',
            'payment_method_id': self.payment_method_manual_in.id,
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': inv1.partner_id.id,
            'amount': 500,
            'journal_id': self.bank_journal_euro.id,
            'company_id': company.id,
            'currency_id': self.currency_eur_id,
        })
        payment.post()
        inv1_receivable = inv1.move_id.line_ids.filtered(lambda l: l.account_id.internal_type == 'receivable')
        pay_receivable = payment.move_line_ids.filtered(lambda l: l.account_id.internal_type == 'receivable')

        self.assertEqual(inv1_receivable.balance, 2000)
        self.assertEqual(pay_receivable.balance, -500)

        (inv1_receivable + pay_receivable).reconcile()
        self.assertEqual(inv1.residual, 500)
        self.assertEqual(inv1.residual_company_signed, 1500)
