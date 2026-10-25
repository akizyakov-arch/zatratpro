CREATE TABLE workspace_events (
 id BIGSERIAL PRIMARY KEY,
 actor_id BIGINT NOT NULL REFERENCES users(id),
 company_id BIGINT REFERENCES companies(id),
 entity_type TEXT NOT NULL,
 entity_id BIGINT,
 action TEXT NOT NULL,
 reason TEXT,
 details JSONB NOT NULL DEFAULT '{}',
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX workspace_events_company_created ON workspace_events(company_id,created_at DESC,id DESC);

-- These database guards also cover legacy Telegram entrypoints. Finance writes
-- take the company row lock, so an issue cannot race a removal or archival.
CREATE FUNCTION workspace_has_open_settlements(cid BIGINT, uid BIGINT DEFAULT NULL, pid BIGINT DEFAULT NULL)
RETURNS BOOLEAN LANGUAGE SQL AS $$
 WITH selected AS (
   SELECT * FROM advances WHERE company_id=cid AND canceled_at IS NULL
     AND (uid IS NULL OR employee_id=uid) AND (pid IS NULL OR project_id=pid)
 ), unsettled AS (
   SELECT employee_id,
     SUM(CASE WHEN received_at IS NOT NULL THEN amount ELSE 0 END)
       -COALESCE(SUM((SELECT SUM(amount) FROM advance_expenses e
                     WHERE e.advance_id=a.id AND e.approved_at IS NOT NULL)),0)
       -COALESCE(SUM((SELECT SUM(amount) FROM advance_returns r
                     WHERE r.advance_id=a.id AND r.approved_at IS NOT NULL)),0) AS balance
   FROM selected a GROUP BY employee_id
 )
 SELECT EXISTS(SELECT 1 FROM selected WHERE received_at IS NULL)
 OR EXISTS(SELECT 1 FROM advance_expenses e JOIN selected a ON a.id=e.advance_id
           WHERE e.approved_at IS NULL AND e.rejected_at IS NULL)
 OR EXISTS(SELECT 1 FROM advance_returns r JOIN selected a ON a.id=r.advance_id
           WHERE r.approved_at IS NULL AND r.rejected_at IS NULL)
 OR EXISTS(SELECT 1 FROM unsettled WHERE balance<>0)
 OR EXISTS(SELECT 1 FROM card_expenses e JOIN business_cards b ON b.id=e.card_id
           JOIN documents d ON d.id=e.document_id
           WHERE b.company_id=cid AND (uid IS NULL OR e.submitted_by=uid)
             AND (pid IS NULL OR d.project_id=pid)
             AND e.approved_at IS NULL AND e.rejected_at IS NULL)
$$;

CREATE FUNCTION workspace_settlement_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE cid BIGINT; uid BIGINT; pid BIGINT;
BEGIN
 IF TG_TABLE_NAME='company_members' THEN
   IF OLD.status<>'active' OR (NEW.status='active' AND NEW.role=OLD.role AND NEW.company_id=OLD.company_id) THEN RETURN NEW; END IF;
   cid:=OLD.company_id; uid:=OLD.user_id;
 ELSIF TG_TABLE_NAME='projects' THEN
   IF OLD.status<>'active' OR NEW.status<>'archived' THEN RETURN NEW; END IF;
   cid:=OLD.company_id; pid:=OLD.id;
 ELSE
   IF OLD.status<>'active' OR NEW.status<>'archived' THEN RETURN NEW; END IF;
   cid:=OLD.id;
 END IF;
 PERFORM id FROM companies WHERE id=cid FOR UPDATE;
 IF workspace_has_open_settlements(cid,uid,pid) THEN
   RAISE EXCEPTION 'Сначала завершите расчёты и проверьте ожидающие операции.' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER workspace_members_settlement BEFORE UPDATE ON company_members
 FOR EACH ROW EXECUTE FUNCTION workspace_settlement_guard();
CREATE TRIGGER workspace_projects_settlement BEFORE UPDATE ON projects
 FOR EACH ROW EXECUTE FUNCTION workspace_settlement_guard();
CREATE TRIGGER workspace_companies_settlement BEFORE UPDATE ON companies
 FOR EACH ROW EXECUTE FUNCTION workspace_settlement_guard();

CREATE FUNCTION workspace_finance_lock() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE cid BIGINT;
BEGIN
 IF TG_TABLE_NAME='advances' THEN
   cid:=NEW.company_id;
 ELSIF TG_TABLE_NAME IN ('advance_expenses','advance_returns') THEN
   SELECT company_id INTO cid FROM advances WHERE id=NEW.advance_id;
 ELSE
   SELECT company_id INTO cid FROM business_cards WHERE id=NEW.card_id;
 END IF;
 PERFORM id FROM companies WHERE id=cid FOR UPDATE;
 IF TG_TABLE_NAME='advances' AND TG_OP='INSERT' THEN
   IF NOT EXISTS(SELECT 1 FROM company_members cm JOIN users u ON u.id=cm.user_id
                 JOIN companies c ON c.id=cm.company_id
                 WHERE cm.company_id=cid AND cm.user_id=NEW.employee_id
                   AND cm.status='active' AND cm.role='employee' AND u.is_active AND c.status='active')
      OR NOT EXISTS(SELECT 1 FROM projects WHERE id=NEW.project_id AND company_id=cid AND status='active')
      OR NOT EXISTS(SELECT 1 FROM company_members cm JOIN users u ON u.id=cm.user_id
                    WHERE cm.company_id=cid AND cm.user_id=NEW.issued_by
                      AND cm.status='active' AND cm.role='manager' AND u.is_active) THEN
     RAISE EXCEPTION 'Сотрудник или проект больше недоступен для выдачи.' USING ERRCODE='23514';
   END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER workspace_advances_lock BEFORE INSERT OR UPDATE ON advances
 FOR EACH ROW EXECUTE FUNCTION workspace_finance_lock();
CREATE TRIGGER workspace_expenses_lock BEFORE INSERT OR UPDATE ON advance_expenses
 FOR EACH ROW EXECUTE FUNCTION workspace_finance_lock();
CREATE TRIGGER workspace_returns_lock BEFORE INSERT OR UPDATE ON advance_returns
 FOR EACH ROW EXECUTE FUNCTION workspace_finance_lock();
CREATE TRIGGER workspace_cards_lock BEFORE INSERT OR UPDATE ON card_expenses
 FOR EACH ROW EXECUTE FUNCTION workspace_finance_lock();
