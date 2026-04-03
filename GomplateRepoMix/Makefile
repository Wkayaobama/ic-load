SCHEMA_CTX := schema_context.yaml
RUN_CTX := run_context.yaml
TMPL_DIR := templates
RENDER_DIR := rendered_sql

ENTITIES := Company Person Opportunity
CALL_TARGETS := company contact
NOTE_TARGETS := company contact deal
TASK_TARGETS := company contact

.PHONY: all validate render clean

all: validate render

validate:
	yq eval '.' $(SCHEMA_CTX) > /dev/null
	yq eval '.' $(RUN_CTX) > /dev/null

render: validate
	mkdir -p $(RENDER_DIR)
	GOMPLATE_ENTITY=Company gomplate -d schema=$(SCHEMA_CTX) -d run=$(RUN_CTX) -f $(TMPL_DIR)/upsert_entity.sql.tmpl -o $(RENDER_DIR)/upsert_company.sql
	GOMPLATE_ENTITY=Person gomplate -d schema=$(SCHEMA_CTX) -d run=$(RUN_CTX) -f $(TMPL_DIR)/upsert_entity.sql.tmpl -o $(RENDER_DIR)/upsert_person.sql
	GOMPLATE_ENTITY=Opportunity gomplate -d schema=$(SCHEMA_CTX) -d run=$(RUN_CTX) -f $(TMPL_DIR)/upsert_entity.sql.tmpl -o $(RENDER_DIR)/upsert_opportunity.sql
	GOMPLATE_COMM_TYPE=Calls GOMPLATE_ASSOC_TARGET=company gomplate -d schema=$(SCHEMA_CTX) -d run=$(RUN_CTX) -f $(TMPL_DIR)/association_bridge.sql.tmpl -o $(RENDER_DIR)/association_calls_company.sql
	GOMPLATE_COMM_TYPE=Calls GOMPLATE_ASSOC_TARGET=contact gomplate -d schema=$(SCHEMA_CTX) -d run=$(RUN_CTX) -f $(TMPL_DIR)/association_bridge.sql.tmpl -o $(RENDER_DIR)/association_calls_contact.sql
	GOMPLATE_COMM_TYPE=Notes GOMPLATE_ASSOC_TARGET=company gomplate -d schema=$(SCHEMA_CTX) -d run=$(RUN_CTX) -f $(TMPL_DIR)/association_bridge.sql.tmpl -o $(RENDER_DIR)/association_notes_company.sql
	GOMPLATE_COMM_TYPE=Notes GOMPLATE_ASSOC_TARGET=contact gomplate -d schema=$(SCHEMA_CTX) -d run=$(RUN_CTX) -f $(TMPL_DIR)/association_bridge.sql.tmpl -o $(RENDER_DIR)/association_notes_contact.sql
	GOMPLATE_COMM_TYPE=Notes GOMPLATE_ASSOC_TARGET=deal gomplate -d schema=$(SCHEMA_CTX) -d run=$(RUN_CTX) -f $(TMPL_DIR)/association_bridge.sql.tmpl -o $(RENDER_DIR)/association_notes_deal.sql
	GOMPLATE_COMM_TYPE=Tasks GOMPLATE_ASSOC_TARGET=company gomplate -d schema=$(SCHEMA_CTX) -d run=$(RUN_CTX) -f $(TMPL_DIR)/association_bridge.sql.tmpl -o $(RENDER_DIR)/association_tasks_company.sql
	GOMPLATE_COMM_TYPE=Tasks GOMPLATE_ASSOC_TARGET=contact gomplate -d schema=$(SCHEMA_CTX) -d run=$(RUN_CTX) -f $(TMPL_DIR)/association_bridge.sql.tmpl -o $(RENDER_DIR)/association_tasks_contact.sql

clean:
	rm -rf $(RENDER_DIR)
