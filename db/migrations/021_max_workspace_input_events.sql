ALTER TABLE max_workspace_flows ADD COLUMN IF NOT EXISTS input_event TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS max_workspace_flow_input ON max_workspace_flows(actor,input_event) WHERE input_event IS NOT NULL;
