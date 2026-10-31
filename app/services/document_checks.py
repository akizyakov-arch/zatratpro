"""Deterministic checks of extracted values; never repair quantities by guessing."""
from decimal import Decimal, InvalidOperation
import hashlib
from app.schemas.vat import document_vat_total


def number(value):
    if value is None:
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def review_fingerprint(document):
    return hashlib.sha256(document.model_dump_json().encode()).hexdigest()


def document_warnings(document):
    warnings = []
    items = [item for item in document.items if any(value is not None for value in (item.name, item.quantity, item.price, item.line_total))]
    for index, item in enumerate(items, 1):
        label = f'Строка {index} «{item.name or "Без названия"}»'
        qty, price, total = map(number, (item.quantity, item.price, item.line_total))
        rate, tax, net = map(number, (item.vat_rate, item.vat_amount, item.line_total_without_vat))
        if qty is None or price is None or total is None:
            warnings.append(f'{label}: не удалось проверить количество, цену или сумму — есть непрочитанные значения.')
            continue
        if qty <= 0 or price < 0 or total < 0:
            warnings.append(f'{label}: неположительное количество или отрицательная сумма/цена; сверь с оригиналом.')
            continue
        if rate is not None and not 0 <= rate <= 100:
            warnings.append(f'{label}: некорректная ставка НДС; сверь с оригиналом.')
            continue
        # Unit prices can be rounded to kopecks while the line uses higher precision.
        tolerance = Decimal('0.02') + abs(qty) * Decimal('0.005')
        base = qty * price
        candidates = []
        if item.price_includes_vat is not False:
            candidates.append(base)
        if item.price_includes_vat is not True:
            if rate is not None:
                candidates.append(base * (1 + rate / 100))
            if tax is not None:
                candidates.append(base + tax)
            if net is not None and abs(base - net) <= tolerance and (tax is not None or rate is not None):
                candidates.append(net + tax if tax is not None else net * (1 + rate / 100))
            if rate is None and tax is None:
                candidates.append(base)
        if not any(abs(total - expected) <= tolerance for expected in candidates):
            suffix = ' с учётом указанного НДС' if rate is not None or tax is not None else '; условия НДС/скидок не установлены'
            warnings.append(f'{label}: количество {qty} × цена {price:.2f} не согласуется с суммой {total:.2f}{suffix}. Проверь количество, цену, НДС и скидки.')
        if net is not None and tax is not None and abs(net + tax - total) > Decimal('0.02'):
            warnings.append(f'{label}: сумма без НДС + НДС не совпадает с итогом строки.')
        if net is not None and tax is not None and rate is not None and abs(net * rate / 100 - tax) > Decimal('0.02'):
            warnings.append(f'{label}: сумма НДС не соответствует указанной ставке.')
    totals = [number(item.line_total) for item in items]
    total = number(document.total)
    if items and total is not None and all(value is not None for value in totals):
        if abs(sum(totals) - total) > Decimal('0.02') * len(items):
            warnings.append(f'Сумма позиций {sum(totals):.2f} не совпадает с итогом документа {total:.2f}. Проверь скидки, доставку и полноту списка.')
    tax = number(document_vat_total(document))
    if tax is not None:
        if tax < 0 or (total is not None and tax > total + Decimal('0.02')):
            warnings.append('НДС документа отрицательный или превышает итог; сверь с оригиналом.')
        known_taxes = [number(item.vat_amount) for item in items]
        if items and all(value is not None for value in known_taxes) and abs(sum(known_taxes) - tax) > Decimal('0.02') * len(items):
            warnings.append('НДС по позициям не совпадает с НДС документа; сверь с оригиналом.')
        if document.vat_scope == 'no_vat' and tax != 0:
            warnings.append('Пометка «без НДС» противоречит положительной сумме НДС.')
    return warnings


def warning_text(document):
    warnings = document_warnings(document)
    if not warnings:
        return ''
    return '⚠️ Нужна проверка по оригиналу:\n' + '\n'.join(warnings) + '\nЗначения автоматически не исправлялись.'
