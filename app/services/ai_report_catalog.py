"""Whitelisted report sources. Model output never becomes a SQL expression."""
REPORTS = {
 'projects':'Проекты',
 'advances':'Оформленные выдачи', 'received':'Подтверждённое получение',
 'expenses':'Расходы из выдач', 'returns':'Возвраты', 'cards':'Расходы по бизнес-картам',
 'documents':'Документы затрат', 'items':'Позиции документов',
 'balance':'Расчётный остаток', 'cash':'Деньги у сотрудников', 'debt':'Долг компании сотрудникам',
 'overview':'Финансовая сводка', 'attention':'Операции на проверке',
}
# Each source has the same columns; company is always filtered in the outer query.
SOURCES = {
'advances': """SELECT a.company_id,a.project_id,a.employee_id,a.amount,'RUB'::text currency,a.created_at at,
 CASE WHEN a.canceled_at IS NOT NULL THEN 'canceled' WHEN a.received_at IS NULL THEN 'pending' ELSE 'approved' END status,
 a.id::text label,NULL::text vendor,NULL::text card,NULL::text item,NULL::numeric quantity,NULL::numeric price,
 a.purpose note FROM advances a""",
'received': """SELECT a.company_id,a.project_id,a.employee_id,a.amount,'RUB'::text currency,a.received_at at,
 'approved'::text status,a.id::text label,NULL::text vendor,NULL::text card,NULL::text item,
 NULL::numeric quantity,NULL::numeric price,a.purpose note FROM advances a WHERE a.received_at IS NOT NULL AND a.canceled_at IS NULL""",
'expenses': """SELECT a.company_id,a.project_id,a.employee_id,e.amount,'RUB'::text currency,
 CASE WHEN e.approved_at IS NOT NULL THEN e.approved_at WHEN e.rejected_at IS NOT NULL THEN e.rejected_at ELSE e.created_at END at,
 CASE WHEN e.rejected_at IS NOT NULL THEN 'rejected' WHEN e.approved_at IS NOT NULL THEN 'approved' ELSE 'pending' END status,
 e.id::text label,d.vendor,NULL::text card,NULL::text item,NULL::numeric quantity,NULL::numeric price,e.rejection_reason note,e.document_id,e.created_at submitted_at
 FROM advance_expenses e JOIN advances a ON a.id=e.advance_id JOIN documents d ON d.id=e.document_id WHERE a.canceled_at IS NULL""",
'returns': """SELECT a.company_id,a.project_id,a.employee_id,r.amount,'RUB'::text currency,
 CASE WHEN r.approved_at IS NOT NULL THEN r.approved_at WHEN r.rejected_at IS NOT NULL THEN r.rejected_at ELSE r.created_at END at,
 CASE WHEN r.rejected_at IS NOT NULL THEN 'rejected' WHEN r.approved_at IS NOT NULL THEN 'approved' ELSE 'pending' END status,
 r.id::text label,NULL::text vendor,NULL::text card,NULL::text item,NULL::numeric quantity,NULL::numeric price,r.rejection_reason note
 FROM advance_returns r JOIN advances a ON a.id=r.advance_id WHERE a.canceled_at IS NULL""",
'cards': """SELECT b.company_id,d.project_id,e.submitted_by employee_id,e.amount,'RUB'::text currency,
 CASE WHEN e.approved_at IS NOT NULL THEN e.approved_at WHEN e.rejected_at IS NOT NULL THEN e.rejected_at ELSE e.created_at END at,
 CASE WHEN e.rejected_at IS NOT NULL THEN 'rejected' WHEN e.approved_at IS NOT NULL THEN 'approved' ELSE 'pending' END status,
 e.id::text label,d.vendor,b.name||' ····'||b.last4 card,NULL::text item,NULL::numeric quantity,NULL::numeric price,e.rejection_reason note,e.document_id,e.created_at submitted_at
 FROM card_expenses e JOIN business_cards b ON b.id=e.card_id JOIN documents d ON d.id=e.document_id AND d.company_id=b.company_id""",
'documents': """SELECT d.company_id,d.project_id,d.uploaded_by_user_id employee_id,d.total_amount amount,d.currency,d.created_at at,
 CASE WHEN d.duplicate_status IN ('exact','probable') THEN 'duplicates' ELSE 'all' END status,
 COALESCE(d.external_document_number,d.incoming_number,d.id::text) label,d.vendor,NULL::text card,NULL::text item,
 NULL::numeric quantity,NULL::numeric price,d.document_type note,d.id document_id,d.document_type doc_type FROM documents d""",
'items': """SELECT d.company_id,d.project_id,d.uploaded_by_user_id employee_id,i.line_total amount,d.currency,d.created_at at,
 'all'::text status,COALESCE(d.external_document_number,d.id::text) label,d.vendor,NULL::text card,i.name item,i.quantity,i.price,NULL::text note,d.id document_id,d.document_type doc_type
 FROM document_items i JOIN documents d ON d.id=i.document_id""",
}
GROUPS = {'project':'project_name','employee':"employee_name||' · №'||employee_id::text",'vendor':"COALESCE(vendor,'Не указан')",'card':"COALESCE(card,'Не указана')",'item':"COALESCE(item,'Не указана')",'day':"to_char(at AT TIME ZONE 'UTC','YYYY-MM-DD')",'week':"to_char(date_trunc('week',at AT TIME ZONE 'UTC'),'YYYY-MM-DD')",'month':"to_char(at AT TIME ZONE 'UTC','YYYY-MM')",'employee_day':"employee_name||' · №'||employee_id::text||' · '||to_char(at AT TIME ZONE 'UTC','YYYY-MM-DD')",'none':"COALESCE(NULL::text,'Всего')"}

# A single read-only queue across all current pending financial operations.
SOURCES['attention']=' UNION ALL '.join(
    "SELECT company_id,project_id,employee_id,amount,currency,at,status,'"+title+" #'||label label,vendor,card,item,quantity,price,note FROM ("+SOURCES[k]+") queued WHERE status='pending'"
    for k,title in [('advances','Выдача'),('returns','Возврат')]
)
