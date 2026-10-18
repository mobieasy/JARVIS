import tempfile
import unittest
from datetime import date
from pathlib import Path

from reconcile_invoices import reconcile


class InvoiceTests(unittest.TestCase):
    def report(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'invoices.csv'
            source.write_text('invoice_id,due_date,amount,paid,currency\n' + rows, encoding='utf-8')
            return reconcile(source, date(2026, 10, 18))

    def test_totals_and_due_today(self):
        result = self.report('A,2026-10-17,100.10,20.05,INR\nB,2026-10-18,50,0,INR\nC,2026-10-19,30,30,INR\n')
        self.assertEqual(result['billed'], '180.10')
        self.assertEqual(result['received'], '50.05')
        self.assertEqual(result['outstanding'], '130.05')
        self.assertEqual(result['overdue'], '80.05')

    def test_duplicate_fails_instead_of_double_counting(self):
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.report('A,2026-10-17,10,0,INR\nA,2026-10-17,10,0,INR\n')

    def test_invalid_financial_rows_fail(self):
        for amount, paid, currency in [('-1', '0', 'INR'), ('NaN', '0', 'INR'),
                                       ('1.001', '0', 'INR'), ('10', '11', 'INR'), ('10', '0', 'USD')]:
            with self.subTest(amount=amount, paid=paid, currency=currency), self.assertRaises(ValueError):
                self.report(f'A,2026-10-17,{amount},{paid},{currency}\n')

    def test_bad_date_fails(self):
        with self.assertRaises(ValueError):
            self.report('A,2026-02-30,10,0,INR\n')



if __name__ == '__main__':
    unittest.main()
