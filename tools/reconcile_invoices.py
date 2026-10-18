"""Validate an invoice CSV and produce a dated, deterministic INR summary.

Bookkeeping helper only: it never sends reminders or changes source records.
"""
import argparse
import csv
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path


def money(value):
    try:
        result = Decimal(value)
        if not result.is_finite() or result < 0 or result != result.quantize(Decimal('0.01')):
            raise ValueError('Amounts must be nonnegative and have at most two decimal places')
    except InvalidOperation as exc:
        raise ValueError('Invalid amount') from exc
    return result


def reconcile(path, as_of):
    seen = set()
    billed = received = overdue = outstanding = Decimal('0')
    details = []
    with Path(path).open(newline='', encoding='utf-8-sig') as source:
        reader = csv.DictReader(source)
        required = {'invoice_id', 'due_date', 'amount', 'paid', 'currency'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('Missing required CSV columns: ' + ', '.join(sorted(required)))
        for row_number, row in enumerate(reader, 2):
            try:
                identifier = row['invoice_id'].strip()
                if not identifier or identifier in seen:
                    raise ValueError('Missing or duplicate invoice ID')
                seen.add(identifier)
                if row['currency'].strip().upper() != 'INR':
                    raise ValueError('This report accepts INR only; do not combine currencies')
                due = date.fromisoformat(row['due_date'])
                amount, paid = money(row['amount']), money(row['paid'])
                if paid > amount:
                    raise ValueError('Paid amount exceeds invoice amount; review credit separately')
                balance = amount - paid
                is_overdue = due < as_of and balance > 0
                billed += amount
                received += paid
                outstanding += balance
                if is_overdue:
                    overdue += balance
                details.append({'invoice_id': identifier, 'due_date': due.isoformat(),
                                'balance': f'{balance:.2f}', 'overdue': is_overdue})
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError(f'CSV row {row_number}: {exc}') from exc
    return {'as_of': as_of.isoformat(), 'currency': 'INR', 'invoice_count': len(seen),
            'billed': f'{billed:.2f}', 'received': f'{received:.2f}',
            'outstanding': f'{outstanding:.2f}', 'overdue': f'{overdue:.2f}',
            'invoices': details}


def render(report):
    lines = ['# Invoice reconciliation', '', f"As of: {report['as_of']} · INR", '',
             'Source: supplied CSV; due dates before the report date count as overdue.', '',
             '| Measure | Amount |', '|---|---:|']
    for key in ('billed', 'received', 'outstanding', 'overdue'):
        lines.append(f"| {key.title()} | {report[key]} |")
    lines += ['', f"Invoices checked: {report['invoice_count']}", '',
              'Review source records before taking action. No messages or payments were sent.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv')
    parser.add_argument('--as-of', required=True, type=date.fromisoformat)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        report = reconcile(args.csv, args.as_of)
    except (ValueError, OSError) as exc:
        parser.exit(1, str(exc) + '\n')
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    output.with_suffix('.md').write_text(render(report), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'invoices'}))


if __name__ == '__main__':
    main()
