"""Read-only, company-scoped execution of the financial question catalogue."""
from collections import defaultdict
from dataclasses import dataclass,field
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal
from io import BytesIO
from openpyxl import Workbook
from app.services.database import get_pool
from app.services.workspace import WorkspaceService,WorkspaceError
from app.services.ai_reports import ReportIntent,ReportQuestionError,resolve_name
from app.services.ai_report_catalog import SOURCES,GROUPS,REPORTS
from app.services.advances import AdvanceService
from app.services.business_cards import BusinessCardService
from app.services.money_reports import cash_and_employee_debt
from app.services.report_exports import _append_row
from app.services.json_formatter import DOCUMENT_TYPE_TITLES

STATUS_LABELS={'all':'все','approved':'принято / подтверждено','pending':'ожидает проверки / получения','rejected':'отклонено','canceled':'отменено','duplicates':'дубли','unassigned':'без привязки к оплате'}


@dataclass
class QuestionResult:
    text: str
    rows: list
    totals: dict
    previous_rows: list=field(default_factory=list)
    company_id: int | None=None

    def workbook(self):
        workbook=Workbook();sheet=workbook.active;sheet.title='Ответ'
        for line in self.text.splitlines():_append_row(sheet,[line])
        for name,rows in [('Данные',self.rows),('Сравнение',self.previous_rows)]:
            if not rows:continue
            table=workbook.create_sheet(name)
            keys=list(dict.fromkeys(key for row in rows for key in row))
            _append_row(table,keys)
            for row in rows:
                _append_row(table,[float(row[key]) if isinstance(row.get(key),Decimal) else row[key].isoformat() if isinstance(row.get(key),datetime) else row.get(key) for key in keys])
        for table in workbook:
            for cells in table:
                for cell in cells:
                    if isinstance(cell.value,str):cell.data_type='s'
        stream=BytesIO();workbook.save(stream)
        return stream.getvalue()


def bounds(intent):
    if bool(intent.start)!=bool(intent.end) or (intent.start and intent.start>intent.end) or intent.end==date.max:
        raise ReportQuestionError('Укажи корректные начальную и конечную даты.')
    start=datetime.combine(intent.start,datetime.min.time(),timezone.utc) if intent.start else datetime(2000,1,1,tzinfo=timezone.utc)
    end=datetime.combine(intent.end+timedelta(days=1),datetime.min.time(),timezone.utc) if intent.end else datetime.now(timezone.utc)
    if start>=end:raise ReportQuestionError('Некорректный период.')
    return start,end


async def scope(c,actor,intent):
    try:ctx=await WorkspaceService()._manager(c,actor)
    except WorkspaceError as exc:raise ReportQuestionError(str(exc)) from None
    projects=await c.fetch('SELECT id,name FROM projects WHERE company_id=$1 ORDER BY id',ctx['company_id'])
    people=await c.fetch("SELECT u.id,COALESCE(NULLIF(trim(concat_ws(' ',u.first_name,u.last_name)),''),u.username,'Пользователь №'||u.id) name FROM users u JOIN company_members cm ON cm.user_id=u.id WHERE cm.company_id=$1 ORDER BY u.id",ctx['company_id'])
    project=resolve_name(projects,intent.project,'проект');employee=resolve_name(people,intent.employee,'сотрудника')
    return ctx,project,employee


def validate(intent):
    if intent.report not in REPORTS:raise ReportQuestionError('Неизвестный отчёт.')
    if intent.min_amount is not None and intent.max_amount is not None and intent.min_amount>intent.max_amount:
        raise ReportQuestionError('Минимальная сумма больше максимальной.')
    statuses={'advances':{'all','approved','pending','canceled'},'received':{'all','approved'},
              'expenses':{'all','approved','pending','rejected'},'returns':{'all','approved','pending','rejected'},
              'cards':{'all','approved','pending','rejected'},'documents':{'all','duplicates','unassigned'},'items':{'all'},'attention':{'all','pending'}}
    if intent.report in statuses and intent.status not in statuses[intent.report]:
        raise ReportQuestionError('Этот статус не применяется к выбранному отчёту.')
    if intent.repeat_after_rejection and intent.report not in ('expenses','cards'):raise ReportQuestionError('Повтор после отказа проверяется для расходов сотрудников и карт.')
    if intent.min_count and (intent.view!='summary' or intent.report not in SOURCES or intent.report=='items'):raise ReportQuestionError('Минимальное число операций применяется к сгруппированным операциям.')
    if intent.inactive_days and intent.report!='cash':raise ReportQuestionError('Отсутствие расходов и возвратов проверяется для денег у сотрудников.')
    if intent.report not in SOURCES:
        if any((intent.vendor,intent.card,intent.item,intent.document_number,intent.document_type,intent.min_amount is not None,intent.max_amount is not None,intent.older_than_days,intent.status!='all')):
            raise ReportQuestionError('Для сводки/остатка доступны фильтры проекта, сотрудника и периода. Для деталей запроси отдельный отчёт операций.')
        if intent.group_by not in ('project','employee','none'):
            raise ReportQuestionError('Остатки и сводку можно разбить по проектам или сотрудникам.')
    if intent.item and intent.report!='items':raise ReportQuestionError('Для поиска товаров запроси позиции документов.')
    if intent.card and intent.report!='cards':raise ReportQuestionError('Фильтр карты доступен для расходов по бизнес-картам.')
    if (intent.document_type or intent.document_number) and intent.report not in ('documents','items'):
        raise ReportQuestionError('Номер и тип документа применяются к документам и товарам.')
    if intent.vendor and intent.report not in ('documents','items','expenses','cards'):
        raise ReportQuestionError('В этом отчёте нет поставщика. Запроси документы или расходы.')
    if intent.group_by=='card' and intent.report!='cards':raise ReportQuestionError('Разбивка по картам доступна только для расходов по картам.')
    if intent.group_by=='item' and intent.report!='items':raise ReportQuestionError('Разбивка по товарам доступна только для позиций документов.')
    if intent.group_by=='vendor' and intent.report not in ('documents','items','expenses','cards'):
        raise ReportQuestionError('Для разбивки по поставщикам запроси документы или расходы.')


async def event_rows(c,intent,ctx,project,employee):
    start,end=bounds(intent)
    source=SOURCES[intent.report]
    clauses=['e.company_id=$1','($2::bigint IS NULL OR e.project_id=$2)','($3::bigint IS NULL OR e.employee_id=$3)','e.at>=$4','e.at<$5']
    params=[ctx['company_id'],project['id'] if project else None,employee['id'] if employee else None,start,end]
    def add(condition,value):
        params.append(value);clauses.append(condition.replace('?',f'${len(params)}'))
    status=intent.status
    # "all" on advances means all non-cancelled issues; other statuses are explicit.
    if intent.report=='advances' and status=='all':clauses.append("e.status<>'canceled'")
    elif status not in ('all','unassigned'):add('e.status=?',status)
    if status=='unassigned':
        clauses.append("NOT EXISTS(SELECT 1 FROM advance_expenses ae WHERE ae.document_id=e.document_id AND ae.rejected_at IS NULL) AND NOT EXISTS(SELECT 1 FROM card_expenses ce WHERE ce.document_id=e.document_id AND ce.rejected_at IS NULL)")
    for field in ('vendor','card','item'):
        value=getattr(intent,field)
        if value:add(f'position(lower(?) in lower(COALESCE(e.{field},\'\')))>0',value)
    if intent.project_status:add('p.status=?',intent.project_status)
    if intent.document_number:add('lower(e.label)=lower(?)',intent.document_number)
    if intent.document_type:
        add('e.doc_type=?',intent.document_type)
    if intent.min_amount is not None:add('e.amount>=?',intent.min_amount)
    if intent.max_amount is not None:add('e.amount<=?',intent.max_amount)
    if intent.older_than_days:add("e.at<=clock_timestamp()-(?::int*interval '1 day')",intent.older_than_days)
    if intent.repeat_after_rejection:
        clauses.append("(EXISTS(SELECT 1 FROM advance_expenses history WHERE history.document_id=e.document_id AND history.rejected_at<e.submitted_at) OR EXISTS(SELECT 1 FROM card_expenses history WHERE history.document_id=e.document_id AND history.rejected_at<e.submitted_at))")
    where=' AND '.join(clauses)
    selected=f'''WITH events AS ({source}), selected AS (
      SELECT e.*,p.name project_name,COALESCE(NULLIF(concat_ws(' ',u.first_name,u.last_name),''),u.username,'Сотрудник №'||u.id) employee_name
      FROM events e JOIN projects p ON p.id=e.project_id AND p.company_id=e.company_id JOIN users u ON u.id=e.employee_id WHERE {where})'''
    totals={r['currency']:r['amount'] for r in await c.fetch(selected+' SELECT currency,COALESCE(sum(amount),0) amount FROM selected GROUP BY currency',*params)}
    if intent.view=='list' or intent.report=='items':
        # Totals cover all matching rows. Details are capped for chat and clearly labelled.
        order={'amount_desc':'amount DESC NULLS LAST,at DESC,label','amount_asc':'amount ASC NULLS LAST,at DESC,label','newest':'at DESC,label','oldest':'at,label','count_desc':'at DESC,label'}[intent.sort]
        total=await c.fetchval(selected+' SELECT count(*) FROM selected',*params)
        rows=await c.fetch(selected+f' SELECT at,label,project_name,employee_name,vendor,card,item,quantity,price,amount,currency,status,note FROM selected ORDER BY {order} LIMIT 5000',*params)
        return [dict(r) for r in rows],totals,total
    expr=GROUPS[intent.group_by]
    order={'amount_desc':'amount DESC NULLS LAST,label','amount_asc':'amount ASC NULLS LAST,label','newest':'last_at DESC,label','oldest':'first_at,label','count_desc':'count DESC,label'}[intent.sort]
    having=''
    if intent.min_count:
        params.append(intent.min_count);having=f' HAVING count(*)>=${len(params)}'
    rows=await c.fetch(selected+f' SELECT {expr} label,currency,COALESCE(sum(amount),0) amount,count(*) count,min(at) first_at,max(at) last_at FROM selected GROUP BY {expr},currency{having} ORDER BY {order}',*params)
    if intent.min_count:
        totals={}
        for row in rows:totals[row['currency']]=totals.get(row['currency'],Decimal(0))+row['amount']
    return [dict(r) for r in rows],totals,len(rows)


async def balance_rows(c,intent,ctx,project,employee):
    start,end=bounds(intent)
    report=await AdvanceService().report(ctx['id'],start,end,connection=c,project_id=project['id'] if project else None,employee_id=employee['id'] if employee else None)
    project_ids=None
    if intent.project_status:
        project_ids={r['id'] for r in await c.fetch('SELECT id FROM projects WHERE company_id=$1 AND status=$2',ctx['company_id'],intent.project_status)}
        report['rows']=[r for r in report['rows'] if r['project_id'] in project_ids]
        report['totals']={key:sum((r[key] for r in report['rows']),Decimal(0)) for key in report['totals']}
    if intent.inactive_days:
        recent={r['employee_id'] for r in await c.fetch("SELECT DISTINCT a.employee_id FROM advances a WHERE a.company_id=$1 AND (EXISTS(SELECT 1 FROM advance_expenses e WHERE e.advance_id=a.id AND e.approved_at >= $2 AND e.approved_at < $3) OR EXISTS(SELECT 1 FROM advance_returns r WHERE r.advance_id=a.id AND r.approved_at >= $2 AND r.approved_at < $3))",ctx['company_id'],end-timedelta(days=intent.inactive_days),end)}
        report['rows']=[r for r in report['rows'] if r['employee_id'] not in recent]
        report['totals']={key:sum((r[key] for r in report['rows']),Decimal(0)) for key in report['totals']}
    cash,debt=cash_and_employee_debt(report)
    if intent.report in ('overview','attention'):
        cards=await BusinessCardService().report(ctx['id'],start,end,connection=c,project_id=project['id'] if project else None,employee_id=employee['id'] if employee else None)
        if project_ids is not None:cards=[r for r in cards if r['project_id'] in project_ids]
        t=report['totals']
        values={'Получено':t['received'],'Принятые расходы сотрудников':t['spent'],'Возвраты':t['returned'],
                'У сотрудников':cash,'Компания должна':debt,'Ожидает получения':t['pending'],
                'Расходы на проверке':t['pending_expenses'],'Возвраты на проверке':t['pending_returns'],
                'Бизнес-карты: принято':sum((r['amount'] for r in cards if r['accepted']),Decimal(0)),
                'Бизнес-карты: на проверке':sum((r['amount'] for r in cards if not r['accepted']),Decimal(0))}
        if intent.report=='attention':values={k:v for k,v in values.items() if 'проверке' in k or 'Ожидает' in k}
        if intent.group_by=='none':
            rows=[{'label':k,'amount':v,'currency':'RUB'} for k,v in values.items()]
        else:
            groups={}
            def group(key,name):
                return groups.setdefault(key,dict(label=name,received=Decimal(0),spent=Decimal(0),returned=Decimal(0),amount=Decimal(0),pending=Decimal(0),card_spent=Decimal(0),currency='RUB'))
            for r in report['rows']:
                key=r['project_id'] if intent.group_by=='project' else r['employee_id']
                name=r['project_name'] if intent.group_by=='project' else ' '.join(filter(None,(r['first_name'],r['last_name']))) or str(key)
                g=group(key,name)
                for field in ('received','spent','returned','pending'):g[field]+=r[field]
                g['amount']+=r['closing']
            for r in cards:
                key=r['project_id'] if intent.group_by=='project' else r['submitted_by']
                name=r['project_name'] if intent.group_by=='project' else ' '.join(filter(None,(r['first_name'],r['last_name']))) or str(key)
                g=group(key,name)
                if r['accepted']:g['card_spent']+=r['amount']
            rows=list(groups.values())
        return rows,values,len(rows)
    grouped=defaultdict(lambda:defaultdict(Decimal))
    for row in report['rows']:
        name=(row['project_name'] if intent.group_by=='project' else (' '.join(filter(None,(row['first_name'],row['last_name']))) or str(row['employee_id'])) if intent.group_by=='employee' else 'Всего')
        grouped[name][row['employee_id']]+=row['closing']
    rows=[]
    for label,people in grouped.items():
        amount=sum((max(v,Decimal(0)) if intent.report=='cash' else max(-v,Decimal(0)) if intent.report=='debt' else v for v in people.values()),Decimal(0))
        if amount>0 or intent.report=='balance':rows.append({'label':label,'amount':amount,'currency':'RUB'})
    rows.sort(key=lambda r:(r['amount'],r['label']),reverse=intent.sort!='amount_asc')
    total=cash if intent.report=='cash' else debt if intent.report=='debt' else report['totals']['closing']
    return rows,{'RUB':total},len(rows)


async def build_report(actor,intent):
    validate(intent);bounds(intent)
    if bool(intent.compare_start)!=bool(intent.compare_end) or (intent.compare_start and intent.compare_start>intent.compare_end):
        raise ReportQuestionError('Укажи корректный период сравнения.')
    async with get_pool().acquire() as c,c.transaction(isolation='repeatable_read',readonly=True):
        ctx,project,employee=await scope(c,actor,intent)
        runner=event_rows if intent.report in SOURCES else balance_rows
        rows,totals,total_count=await runner(c,intent,ctx,project,employee)
        previous_rows=[];previous_totals={};pt={}
        if intent.report=='advances' and intent.status=='all':
            pending=intent.model_copy(update={'status':'pending','compare_start':None,'compare_end':None})
            _,pt,_=await event_rows(c,pending,ctx,project,employee)
        if intent.compare_start:
            previous=intent.model_copy(update={'start':intent.compare_start,'end':intent.compare_end,'compare_start':None,'compare_end':None})
            bounds(previous)
            previous_rows,previous_totals,_=await runner(c,previous,ctx,project,employee)
    period=f'{intent.start:%d.%m.%Y} — {intent.end:%d.%m.%Y}' if intent.start else 'всё время'
    lines=[REPORTS[intent.report],f'Период UTC: {period}',f'Компания: {ctx["company_name"]}']
    if project:lines.append('Проект: '+project['name'])
    if intent.project_status:lines.append('Проекты: '+('открытые' if intent.project_status=='active' else 'архивные'))
    if employee:lines.append('Сотрудник: '+employee['name'])
    if intent.vendor:lines.append('Поставщик: '+intent.vendor)
    if intent.card:lines.append('Карта: '+intent.card)
    if intent.item:lines.append('Товар: '+intent.item)
    if intent.repeat_after_rejection:lines.append('Только повторные заявки после отказа по тому же документу.')
    if intent.min_count:lines.append(f'В группе не меньше {intent.min_count} операций.')
    if intent.inactive_days:lines.append(f'Нет принятых расходов или возвратов за {intent.inactive_days} дней до конца периода. Это признак для проверки, а не установленная просрочка.')
    if intent.status!='all':lines.append('Статус: '+STATUS_LABELS[intent.status])
    for currency,amount in totals.items():lines.append(f'{currency}: {amount:.2f} ₽' if intent.report=='overview' else f'Всего {currency}: {amount:.2f}')
    if intent.report in SOURCES:
        matched_count=total_count if intent.view=='list' or intent.report=='items' else sum(r.get('count',0) for r in rows)
        lines.append(f'Найдено записей: {matched_count}')
    if not rows:lines.append('За выбранный период операций не найдено. Всего: 0.00 ₽')
    # Compatibility wording for the first report and a useful received/pending distinction.
    if intent.report=='advances':
        lines.append(f'Всего: {totals.get("RUB",Decimal(0)):.2f} ₽')
        if intent.status=='all':
            lines.append(f'Из них ещё не подтверждено получение: {pt.get("RUB",Decimal(0)):.2f} ₽')
    for row in rows[:intent.limit]:
        if 'at' in row:
            line=f'{row["at"]:%d.%m.%Y} · {row["label"]} · {row["employee_name"]} · {row["project_name"]}'
            if row.get('item'):line+=f' · {row["item"]} · количество {row["quantity"]}; цена {row["price"]}'
            if row.get('vendor'):line+=' · '+row['vendor']
            if row.get('card'):line+=' · '+row['card']
            if row.get('status') not in (None,'all'):line+=' · '+STATUS_LABELS[row['status']]
            if row.get('note'):line+=' · '+DOCUMENT_TYPE_TITLES.get(row['note'],row['note'])
        else:
            line=row['label']
            if 'received' in row:
                line+=f' · получено {row["received"]:.2f}; расходы {row["spent"]:.2f}; возвраты {row["returned"]:.2f}; карты {row["card_spent"]:.2f}; ожидает получения {row["pending"]:.2f}; остаток'
        if 'count' in row:line+=f' ({row["count"]} записей)'
        amount=row.get('amount')
        lines.append(f'{line}: {amount:.2f} {row["currency"]}' if amount is not None else line+' — сумма не распознана')
    if total_count>intent.limit:lines.append(f'Показано {min(intent.limit,len(rows))} из {total_count}; общие суммы посчитаны по всем найденным операциям.')
    if total_count>5000 and (intent.view=='list' or intent.report=='items'):lines.append('Детализация Excel ограничена 5000 строками; сузь период или фильтры. Итоги охватывают все строки.')
    if intent.compare_start:
        lines.append(f'Сравнение UTC: {intent.compare_start:%d.%m.%Y} — {intent.compare_end:%d.%m.%Y}')
        for currency in sorted(set(totals)|set(previous_totals)):
            current=totals.get(currency,Decimal(0));prior=previous_totals.get(currency,Decimal(0))
            lines.append(f'{currency}: сейчас {current:.2f}; сравнение {prior:.2f}; изменение {current-prior:+.2f}')
        if intent.view=='summary' and intent.report in SOURCES and intent.report!='items':
            current_groups={(r['label'],r['currency']):r['amount'] for r in rows}
            prior_groups={(r['label'],r['currency']):r['amount'] for r in previous_rows}
            changes=[(label,currency,current_groups.get((label,currency),Decimal(0))-prior_groups.get((label,currency),Decimal(0))) for label,currency in set(current_groups)|set(prior_groups)]
            changes.sort(key=lambda r:abs(r[2]),reverse=True)
            lines.append('Изменение по группам (по величине вклада):')
            lines.extend(f'{label}: {change:+.2f} {currency}' for label,currency,change in changes[:intent.limit])
    if intent.report in ('balance','cash','debt','overview','attention'):
        lines.append('Деньги — по датам получения/согласования. Остаток на конец периода; неподтверждённые выдачи в него не входят. Карты считаются отдельно.')
        if intent.group_by=='project' and intent.report in ('cash','debt'):lines.append('Общий итог учитывает взаиморасчёты сотрудника между проектами; сумма проектных остатков может отличаться.')
    else:
        lines.append('Статусы — на момент запроса. Документы/товары — по дате загрузки; расходы и возвраты — по дате решения, ожидающие — по дате подачи. Это не банковская выписка.')
    if intent.report=='items':lines.append('Количество и цены — как распознаны. Одинаковые названия могут означать разные единицы; количества разных строк автоматически не складываются.')
    return QuestionResult('\n'.join(lines),rows,totals,previous_rows,ctx['company_id'])
