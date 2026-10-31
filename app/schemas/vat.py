"""VAT is a component of the gross document cost, never an extra expense."""
from decimal import Decimal


def document_vat_total(document):
    if document.vat_total_amount is not None:
        return Decimal(str(document.vat_total_amount))
    items = [item for item in document.items if any(v is not None for v in (item.name,item.quantity,item.price,item.line_total))]
    if items and all(item.vat_amount is not None for item in items):
        return sum((Decimal(str(item.vat_amount)) for item in items), Decimal(0))
    if document.vat_scope == 'no_vat':
        return Decimal(0)
    return None


def vat_scope_label(value):
    return {'document':'Весь документ','mixed':'Смешанный','no_vat':'Без НДС'}.get(value,'Не определено')
