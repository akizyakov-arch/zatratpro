"""Readable chat presentation, independent of report calculations and Excel rows."""
from collections import defaultdict
from decimal import Decimal
import re
from app.services.ai_report_catalog import REPORTS,SOURCES
from app.services.json_formatter import DOCUMENT_TYPE_TITLES

MONTHS=('января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря')
STATUS={'all':'все','approved':'подтверждено','pending':'на проверке / ожидает получения','rejected':'отклонено','canceled':'отменено','duplicates':'возможные дубли','unassigned':'без привязки к оплате'}
WORDS={'advances':('выдача','выдачи','выдач'),'received':('получение','получения','получений'),'documents':('документ','документа','документов'),'items':('позиция','позиции','позиций'),'returns':('возврат','возврата','возвратов')}
COUNTS={'advances':'Выдач','received':'Подтверждений получения','documents':'Документов','items':'Позиций','expenses':'Расходов','returns':'Возвратов','cards':'Расходов по картам','attention':'Операций'}


def amount(value,currency='RUB',signed=False):
    if value is None:return 'сумма не распознана'
    value=Decimal(value)
    text=f'{value:+,.2f}' if signed else f'{value:,.2f}'
    text=text.replace(',',' ').replace('.',',')
    if text.endswith(',00'):text=text[:-3]
    return text+' '+{'RUB':'₽','USD':'$','EUR':'€'}.get(currency,currency)


def metric_amount(key,value,signed=False):
    if key=='Документов':return f'{int(value):+d}' if signed else str(int(value))
    match=re.fullmatch(r'Документы \(([^)]+)\)',key)
    return amount(value,match[1] if match else 'RUB',signed)


def period(start,end):
    if start is None:return 'Всё время'
    if start==end:return f'{start.day} {MONTHS[start.month-1]} {start.year}'
    if (start.year,start.month)==(end.year,end.month):return f'{start.day}–{end.day} {MONTHS[start.month-1]} {start.year}'
    return f'{start:%d.%m.%Y} — {end:%d.%m.%Y}'


def count_text(count,report):
    words=WORDS.get(report,('операция','операции','операций'))
    index=2 if 11<=count%100<=14 else 0 if count%10==1 else 1 if count%10 in (2,3,4) else 2
    return f'{count} {words[index]}'


def format_answer(intent,ctx,project,employee,rows,totals,total_count,pending,previous_rows,previous_totals):
    title='Выдачи денег' if intent.report=='advances' else 'Затраты по документам' if intent.report=='documents' else REPORTS[intent.report]
    lines=[title,f'{ctx["company_name"]} · {period(intent.start,intent.end)} (UTC)']
    for caption,value in [('Проект',project['name'] if project else None),('Сотрудник',employee['name'] if employee else None),('Поставщик',intent.vendor),('Карта',intent.card),('Товар',intent.item)]:
        if value:lines.append(f'{caption}: {value}')
    if intent.project_status:lines.append('Проекты: '+('открытые' if intent.project_status=='active' else 'архивные'))
    if intent.status!='all':lines.append('Статус: '+STATUS[intent.status])
    if intent.report in ('documents','items','overview'):
        lines.append('Чеки: по дате документа (без даты не включены)' if intent.date_basis=='document' else 'Чеки: по дате загрузки')
    lines.append('')
    caption='Выдано' if intent.report=='advances' else 'Итого'
    if totals:
        for key,value in totals.items():lines.append(f'{key}: {metric_amount(key,value)}' if intent.report=='overview' else f'{caption}: {amount(value,key)}')
    elif not rows:lines.append(f'{caption}: 0 ₽')
    if intent.report in SOURCES:
        count=total_count if intent.view=='list' or intent.report=='items' else sum(r.get('count',0) for r in rows)
        lines.append(f'{COUNTS.get(intent.report,"Операций")}: {count}')
    if intent.report=='advances' and intent.status=='all':
        waiting=pending.get('RUB',Decimal(0))
        if waiting:lines.append('Получение не подтверждено: '+amount(waiting))
        elif rows:lines.append('Получение всех выдач подтверждено.')
    if not rows:lines.append('За этот период ничего не найдено.')
    raw_labels=defaultdict(set)
    def clean(label):return re.sub(r' · №\d+(?= ·|$)','',label)
    for row in rows+previous_rows:
        if 'label' in row:raw_labels[clean(row['label'])].add(row['label'])
    def label(text):return clean(text) if len(raw_labels[clean(text)])==1 else text
    if rows:
        lines.append('')
        if intent.view!='list' and intent.report!='items':
            lines.append({'employee':'По сотрудникам','project':'По проектам','vendor':'По поставщикам','card':'По картам','day':'По дням','week':'По неделям','month':'По месяцам','employee_day':'По сотрудникам и дням'}.get(intent.group_by,'Расшифровка'))
        for index,row in enumerate(rows[:intent.limit],1):
            if 'at' in row:
                lines.append(f'{index}. {row["at"]:%d.%m.%Y} · №{row["label"]}')
                lines.append(f'   {row["employee_name"]} · {row["project_name"]}')
                lines.append('   '+amount(row.get('amount'),row['currency']))
                if row.get('item'):
                    qty=format(Decimal(str(row['quantity'])),'f') if row['quantity'] is not None else '?'
                    if '.' in qty:qty=qty.rstrip('0').rstrip('.')
                    lines.append(f'   {row["item"]} · количество: {qty}; цена: {amount(row.get("price"),row["currency"])}')
                if row.get('vendor'):lines.append('   Поставщик: '+row['vendor'])
                if row.get('card'):lines.append('   Карта: '+row['card'])
                if row.get('status') not in (None,'all'):lines.append('   '+STATUS[row['status']].capitalize())
                if row.get('note'):lines.append('   '+DOCUMENT_TYPE_TITLES.get(row['note'],row['note']))
                lines.append('')
            else:
                suffix=' · '+count_text(row['count'],intent.report) if 'count' in row else ''
                if intent.report=='overview' and intent.group_by=='none':
                    lines.append(f'• {row["label"]}: {metric_amount(row["label"],row["amount"])}')
                else:
                    lines.append(f'• {label(row["label"])} — '+('остаток ' if intent.report=='overview' else '')+amount(row.get("amount"),row["currency"])+suffix)
                if 'document_count' in row:
                    lines.append(f'  Документов: {row["document_count"]}')
                    lines.extend('  Затраты по документам: '+amount(value,key.removeprefix('documents_')) for key,value in row.items() if key.startswith('documents_'))
                if 'received' in row:
                    lines.extend([f'  Получено: {amount(row["received"])} · расходы: {amount(row["spent"])}',f'  Возвраты: {amount(row["returned"])} · карты: {amount(row["card_spent"])}',f'  Ожидает получения: {amount(row["pending"])}'])
    if total_count>intent.limit:lines.extend(['',f'Показано {min(intent.limit,len(rows))} из {total_count}. Итог включает все найденные операции.'])
    if total_count>5000 and (intent.view=='list' or intent.report=='items'):lines.append('В Excel — до 5000 строк на период. Для полной детализации сузь запрос.')
    if intent.compare_start:
        lines.extend(['','Сравнение с '+period(intent.compare_start,intent.compare_end)])
        for key in sorted(set(totals)|set(previous_totals)):
            current=totals.get(key,Decimal(0));prior=previous_totals.get(key,Decimal(0))
            currency='RUB' if intent.report=='overview' else key
            prefix=key+': ' if intent.report=='overview' else ''
            old=metric_amount(key,prior) if intent.report=='overview' else amount(prior,currency)
            new=metric_amount(key,current) if intent.report=='overview' else amount(current,currency)
            delta=metric_amount(key,current-prior,True) if intent.report=='overview' else amount(current-prior,currency,signed=True)
            lines.append(f'{prefix}Было {old} → стало {new}')
            lines.append('Изменение: '+delta)
        if intent.view=='summary' and intent.report in SOURCES and intent.report!='items':
            now={(r['label'],r['currency']):r['amount'] for r in rows};before={(r['label'],r['currency']):r['amount'] for r in previous_rows}
            changes=[(name,currency,now.get((name,currency),Decimal(0))-before.get((name,currency),Decimal(0))) for name,currency in set(now)|set(before)]
            changes.sort(key=lambda r:abs(r[2]),reverse=True)
            lines.extend(['','Что изменилось:'])
            lines.extend(f'• {label(name)}: {amount(change,currency,signed=True)}' for name,currency,change in changes[:intent.limit])
    notes=[]
    if intent.report=='overview':notes.append('Документы и движение денег показаны отдельно; эти суммы не складываются.')
    if intent.repeat_after_rejection:notes.append('Только повторные заявки после отказа по тому же документу.')
    if intent.min_count:notes.append(f'Показаны группы с числом операций от {intent.min_count}.')
    if intent.inactive_days:notes.append(f'Нет принятых расходов или возвратов за {intent.inactive_days} дней до конца периода. Это повод для сверки, не установленная просрочка.')
    if intent.group_by=='project' and intent.report in ('cash','debt'):notes.append('Общий итог сводится по сотрудникам между проектами, поэтому может отличаться от суммы проектных остатков.')
    if intent.report=='items':notes.append('Количество — как распознано; разные единицы не складываются автоматически.')
    if notes:lines.extend(['']+notes)
    return '\n'.join(lines).strip()


def format_projects(intent,ctx,rows):
    title='Активные проекты' if intent.project_status=='active' else 'Архивные проекты' if intent.project_status=='archived' else 'Все проекты'
    lines=[title,ctx['company_name'],'',f'Найдено: {len(rows)}']
    for row in rows[:intent.limit]:
        suffix='' if intent.project_status else ' — '+('активный' if row['project_status']=='active' else 'архивный')
        lines.append('• '+row['label']+suffix)
    if not rows:lines.append('Проектов с таким статусом нет.')
    if len(rows)>intent.limit:lines.append(f'Показано {intent.limit} из {len(rows)}. Полный список можно выгрузить в Excel.')
    return '\n'.join(lines)
