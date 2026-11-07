"""Code-owned storage inventory for the explicit ingestion profile.

This provider is under implementation. Table fragments alone are not an operator
migration or a runnable ingestion profile. Default services and old providers do
not import or activate it. Full migration must install and verify the complete
function, policy and trigger inventory before granting any application access.
"""
from __future__ import annotations

import json
import re

from . import identity_schema as _identity

SCHEMA = "wl_ingestion"
REVISION = "0004_ingestion"
PREDECESSOR = "0003_source_lifecycle"

_TABLES = (
    '{"columns":[{"name":"tenant_id","nullable":false,"type":"uuid"},{"name":"portfolio_id","nullable":false,"type":"uuid"},{"name":"accepted_generation","nullable":false,"type":"bigint"},{"name":"mapping_generation","nullable":false,"type":"bigint"},{"name":"control_generation","nullable":false,"type":"bigint"}],"immutable":false,"name":"roots","policies":["runtime_scope","operator_scope"],"primary_key":["tenant_id","portfolio_id"],"purgeable_transient":false,"rls":"ENABLED_AND_FORCED","scope":"tenant"}',
    '{"columns":[{"name":"tenant_id","nullable":false,"type":"uuid"},{"name":"portfolio_id","nullable":false,"type":"uuid"},{"name":"id","nullable":false,"type":"uuid"},{"name":"actor_user_id","nullable":false,"type":"uuid"},{"name":"creation_operation_id","nullable":false,"type":"uuid"},{"name":"request_digest","nullable":false,"type":"text"},{"name":"incarnation","nullable":false,"type":"uuid"},{"name":"restore_epoch","nullable":false,"type":"bigint"},{"name":"realm_digest","nullable":false,"type":"text"},{"name":"state","nullable":false,"type":"text"},{"name":"revision","nullable":false,"type":"bigint"},{"name":"created_at","nullable":false,"type":"timestamptz"},{"name":"expires_at","nullable":false,"type":"timestamptz"},{"name":"member_count","nullable":false,"type":"integer"},{"name":"reserved_bytes","nullable":false,"type":"bigint"},{"name":"receipt_id","nullable":true,"type":"uuid"},{"name":"cleanup_state","nullable":false,"type":"text"}],"immutable":false,"name":"sets","policies":["runtime_scope","operator_scope"],"primary_key":["tenant_id","portfolio_id","id"],"purgeable_transient":false,"rls":"ENABLED_AND_FORCED","scope":"tenant"}',
    '{"columns":[{"name":"tenant_id","nullable":false,"type":"uuid"},{"name":"portfolio_id","nullable":false,"type":"uuid"},{"name":"set_id","nullable":false,"type":"uuid"},{"name":"id","nullable":false,"type":"uuid"},{"name":"ordinal","nullable":false,"type":"integer"},{"name":"connection_id","nullable":false,"type":"uuid"},{"name":"connection_version","nullable":false,"type":"text"},{"name":"installation_id","nullable":false,"type":"text"},{"name":"format_version","nullable":false,"type":"text"},{"name":"context_digest","nullable":false,"type":"text"},{"name":"context_bytes","nullable":true,"type":"bytea"},{"name":"raw_digest","nullable":true,"type":"text"},{"name":"raw_bytes","nullable":true,"type":"bigint"},{"name":"state","nullable":false,"type":"text"},{"name":"error_code","nullable":true,"type":"text"},{"name":"stage_digest","nullable":true,"type":"text"},{"name":"fence","nullable":false,"type":"bigint"},{"name":"connection_generation","nullable":false,"type":"bigint"},{"name":"enablement_generation","nullable":false,"type":"bigint"},{"name":"availability_generation","nullable":false,"type":"bigint"},{"name":"wrapper_profile_digest","nullable":false,"type":"text"},{"name":"raw_deadline","nullable":true,"type":"timestamptz"}],"immutable":false,"name":"members","policies":["runtime_scope","operator_scope"],"primary_key":["tenant_id","portfolio_id","set_id","id"],"purgeable_transient":false,"rls":"ENABLED_AND_FORCED","scope":"tenant"}',
    '{"columns":[{"name":"tenant_id","nullable":false,"type":"uuid"},{"name":"portfolio_id","nullable":false,"type":"uuid"},{"name":"id","nullable":false,"type":"uuid"},{"name":"set_id","nullable":false,"type":"uuid"},{"name":"member_id","nullable":true,"type":"uuid"},{"name":"work_kind","nullable":false,"type":"text"},{"name":"attempt","nullable":false,"type":"bigint"},{"name":"fence","nullable":false,"type":"bigint"},{"name":"worker_id","nullable":false,"type":"uuid"},{"name":"token_digest","nullable":true,"type":"text"},{"name":"session_digest","nullable":false,"type":"text"},{"name":"credential_version","nullable":false,"type":"bigint"},{"name":"incarnation","nullable":false,"type":"uuid"},{"name":"restore_epoch","nullable":false,"type":"bigint"},{"name":"created_at","nullable":false,"type":"timestamptz"},{"name":"expires_at","nullable":false,"type":"timestamptz"},{"name":"state","nullable":false,"type":"text"},{"name":"claim_request_id","nullable":true,"type":"uuid"},{"name":"claim_request_digest","nullable":true,"type":"text"},{"name":"last_request_id","nullable":true,"type":"uuid"},{"name":"last_request_digest","nullable":true,"type":"text"},{"name":"last_result_bytes","nullable":true,"type":"bytea"}],"immutable":false,"name":"leases","policies":["runtime_scope","operator_scope"],"primary_key":["tenant_id","portfolio_id","id"],"purgeable_transient":false,"rls":"ENABLED_AND_FORCED","scope":"tenant"}',
    '{"columns":[{"name":"tenant_id","nullable":false,"type":"uuid"},{"name":"portfolio_id","nullable":false,"type":"uuid"},{"name":"set_id","nullable":false,"type":"uuid"},{"name":"member_id","nullable":false,"type":"uuid"},{"name":"digest","nullable":false,"type":"text"},{"name":"codec","nullable":false,"type":"text"},{"name":"minimal_bytes","nullable":false,"type":"bytea"},{"name":"created_at","nullable":false,"type":"timestamptz"},{"name":"purge_at","nullable":false,"type":"timestamptz"}],"immutable":false,"name":"stages","policies":["runtime_scope","operator_scope"],"primary_key":["tenant_id","portfolio_id","set_id","member_id","digest"],"purgeable_transient":true,"rls":"ENABLED_AND_FORCED","scope":"tenant"}',
    '{"columns":[{"name":"tenant_id","nullable":false,"type":"uuid"},{"name":"portfolio_id","nullable":false,"type":"uuid"},{"name":"set_id","nullable":false,"type":"uuid"},{"name":"revision","nullable":false,"type":"bigint"},{"name":"request_digest","nullable":false,"type":"text"},{"name":"canonical_bytes","nullable":false,"type":"bytea"},{"name":"digest","nullable":false,"type":"text"},{"name":"created_at","nullable":false,"type":"timestamptz"},{"name":"purge_at","nullable":false,"type":"timestamptz"}],"immutable":false,"name":"decisions","policies":["runtime_scope","operator_scope"],"primary_key":["tenant_id","portfolio_id","set_id","revision"],"purgeable_transient":true,"rls":"ENABLED_AND_FORCED","scope":"tenant"}',
    '{"columns":[{"name":"tenant_id","nullable":false,"type":"uuid"},{"name":"portfolio_id","nullable":false,"type":"uuid"},{"name":"id","nullable":false,"type":"uuid"},{"name":"set_id","nullable":false,"type":"uuid"},{"name":"set_revision","nullable":false,"type":"bigint"},{"name":"decision_revision","nullable":false,"type":"bigint"},{"name":"plan_bytes","nullable":true,"type":"bytea"},{"name":"plan_digest","nullable":true,"type":"text"},{"name":"expected_accepted_generation","nullable":false,"type":"bigint"},{"name":"expected_mapping_generation","nullable":false,"type":"bigint"},{"name":"expected_control_generation","nullable":false,"type":"bigint"},{"name":"incarnation","nullable":false,"type":"uuid"},{"name":"restore_epoch","nullable":false,"type":"bigint"},{"name":"realm_digest","nullable":false,"type":"text"},{"name":"expires_at","nullable":false,"type":"timestamptz"},{"name":"created_at","nullable":false,"type":"timestamptz"},{"name":"purge_at","nullable":false,"type":"timestamptz"},{"name":"review_bytes","nullable":false,"type":"bytea"},{"name":"review_digest","nullable":false,"type":"text"}],"immutable":false,"name":"previews","policies":["runtime_scope","operator_scope"],"primary_key":["tenant_id","portfolio_id","id"],"purgeable_transient":true,"rls":"ENABLED_AND_FORCED","scope":"tenant"}',
    '{"columns":[{"name":"tenant_id","nullable":false,"type":"uuid"},{"name":"portfolio_id","nullable":false,"type":"uuid"},{"name":"id","nullable":false,"type":"uuid"},{"name":"codec","nullable":false,"type":"text"},{"name":"canonical_bytes","nullable":false,"type":"bytea"},{"name":"digest","nullable":false,"type":"text"},{"name":"raw_digest","nullable":false,"type":"text"},{"name":"discovery_digest","nullable":false,"type":"text"},{"name":"installation_id","nullable":false,"type":"text"},{"name":"created_at","nullable":false,"type":"timestamptz"}],"immutable":true,"name":"accepted_inputs","policies":["runtime_scope","operator_scope"],"primary_key":["tenant_id","portfolio_id","id"],"purgeable_transient":false,"rls":"ENABLED_AND_FORCED","scope":"tenant"}',
    '{"columns":[{"name":"tenant_id","nullable":false,"type":"uuid"},{"name":"portfolio_id","nullable":false,"type":"uuid"},{"name":"id","nullable":false,"type":"uuid"},{"name":"preview_id","nullable":false,"type":"uuid"},{"name":"codec","nullable":false,"type":"text"},{"name":"canonical_bytes","nullable":false,"type":"bytea"},{"name":"digest","nullable":false,"type":"text"},{"name":"receipt_id","nullable":false,"type":"uuid"},{"name":"created_at","nullable":false,"type":"timestamptz"}],"immutable":true,"name":"accepted_plans","policies":["runtime_scope","operator_scope"],"primary_key":["tenant_id","portfolio_id","id"],"purgeable_transient":false,"rls":"ENABLED_AND_FORCED","scope":"tenant"}',
    '{"columns":[{"name":"tenant_id","nullable":false,"type":"uuid"},{"name":"portfolio_id","nullable":false,"type":"uuid"},{"name":"id","nullable":false,"type":"uuid"},{"name":"source_key","nullable":false,"type":"text"},{"name":"source_revision","nullable":false,"type":"text"},{"name":"financial_digest","nullable":false,"type":"text"},{"name":"source_change","nullable":false,"type":"text"},{"name":"accepted_change","nullable":false,"type":"text"},{"name":"parent_id","nullable":true,"type":"uuid"},{"name":"input_id","nullable":false,"type":"uuid"},{"name":"collection","nullable":false,"type":"text"},{"name":"local_id","nullable":false,"type":"text"},{"name":"typed_bytes","nullable":false,"type":"bytea"},{"name":"typed_digest","nullable":false,"type":"text"},{"name":"created_at","nullable":false,"type":"timestamptz"}],"immutable":true,"name":"source_revisions","policies":["runtime_scope","operator_scope"],"primary_key":["tenant_id","portfolio_id","id"],"purgeable_transient":false,"rls":"ENABLED_AND_FORCED","scope":"tenant"}',
    '{"columns":[{"name":"tenant_id","nullable":false,"type":"uuid"},{"name":"portfolio_id","nullable":false,"type":"uuid"},{"name":"economic_group_id","nullable":false,"type":"uuid"},{"name":"revision_id","nullable":false,"type":"uuid"},{"name":"active","nullable":false,"type":"boolean"}],"immutable":false,"name":"activity_heads","policies":["runtime_scope","operator_scope"],"primary_key":["tenant_id","portfolio_id","economic_group_id"],"purgeable_transient":false,"rls":"ENABLED_AND_FORCED","scope":"tenant"}',
    '{"columns":[{"name":"tenant_id","nullable":false,"type":"uuid"},{"name":"portfolio_id","nullable":false,"type":"uuid"},{"name":"key_digest","nullable":false,"type":"text"},{"name":"account_id","nullable":false,"type":"uuid"},{"name":"account_version","nullable":false,"type":"text"},{"name":"fact_kind","nullable":false,"type":"text"},{"name":"scope_bytes","nullable":false,"type":"bytea"},{"name":"latest_revision_id","nullable":false,"type":"uuid"},{"name":"complete_base_revision_id","nullable":true,"type":"uuid"}],"immutable":false,"name":"snapshot_heads","policies":["runtime_scope","operator_scope"],"primary_key":["tenant_id","portfolio_id","key_digest"],"purgeable_transient":false,"rls":"ENABLED_AND_FORCED","scope":"tenant"}',
    '{"columns":[{"name":"tenant_id","nullable":false,"type":"uuid"},{"name":"portfolio_id","nullable":false,"type":"uuid"},{"name":"id","nullable":false,"type":"uuid"},{"name":"revision","nullable":false,"type":"bigint"},{"name":"connection_id","nullable":false,"type":"uuid"},{"name":"source_key","nullable":false,"type":"text"},{"name":"entity_kind","nullable":false,"type":"text"},{"name":"entity_id","nullable":false,"type":"uuid"},{"name":"entity_version","nullable":false,"type":"text"},{"name":"evidence_digest","nullable":false,"type":"text"},{"name":"plan_id","nullable":false,"type":"uuid"},{"name":"account_id","nullable":true,"type":"uuid"},{"name":"account_version","nullable":true,"type":"text"},{"name":"instrument_id","nullable":true,"type":"uuid"},{"name":"instrument_version","nullable":true,"type":"text"},{"name":"issuer_id","nullable":true,"type":"uuid"},{"name":"issuer_version","nullable":true,"type":"text"}],"generated_columns":{"entity_id":"coalesce(account_id,instrument_id,issuer_id)","entity_version":"coalesce(account_version,instrument_version,issuer_version)"},"immutable":true,"name":"mappings","policies":["runtime_scope","operator_scope"],"primary_key":["tenant_id","portfolio_id","id","revision"],"purgeable_transient":false,"rls":"ENABLED_AND_FORCED","scope":"tenant"}',
    '{"columns":[{"name":"tenant_id","nullable":false,"type":"uuid"},{"name":"portfolio_id","nullable":false,"type":"uuid"},{"name":"id","nullable":false,"type":"uuid"},{"name":"revision","nullable":false,"type":"bigint"},{"name":"left_revision_id","nullable":false,"type":"uuid"},{"name":"right_revision_id","nullable":true,"type":"uuid"},{"name":"decision_kind","nullable":false,"type":"text"},{"name":"evidence_reference","nullable":false,"type":"text"},{"name":"evidence_digest","nullable":false,"type":"text"},{"name":"plan_id","nullable":false,"type":"uuid"}],"immutable":true,"name":"authority_links","policies":["runtime_scope","operator_scope"],"primary_key":["tenant_id","portfolio_id","id","revision"],"purgeable_transient":false,"rls":"ENABLED_AND_FORCED","scope":"tenant"}',
    '{"columns":[{"name":"tenant_id","nullable":false,"type":"uuid"},{"name":"portfolio_id","nullable":false,"type":"uuid"},{"name":"source_revision_id","nullable":false,"type":"uuid"},{"name":"raw_digest","nullable":false,"type":"text"},{"name":"installation_id","nullable":false,"type":"text"},{"name":"evidence_digest","nullable":false,"type":"text"},{"name":"input_id","nullable":false,"type":"uuid"},{"name":"collection","nullable":false,"type":"text"},{"name":"local_id","nullable":false,"type":"text"},{"name":"source_claim_bytes","nullable":false,"type":"bytea"}],"immutable":true,"name":"lineage","policies":["runtime_scope","operator_scope"],"primary_key":["tenant_id","portfolio_id","source_revision_id","input_id","collection","local_id"],"purgeable_transient":false,"rls":"ENABLED_AND_FORCED","scope":"tenant"}',
    '{"columns":[{"name":"tenant_id","nullable":false,"type":"uuid"},{"name":"portfolio_id","nullable":false,"type":"uuid"},{"name":"id","nullable":false,"type":"uuid"},{"name":"incarnation","nullable":false,"type":"uuid"},{"name":"restore_epoch","nullable":false,"type":"bigint"},{"name":"operation_id","nullable":false,"type":"uuid"},{"name":"operation_kind","nullable":false,"type":"text"},{"name":"request_digest","nullable":false,"type":"text"},{"name":"preview_id","nullable":true,"type":"uuid"},{"name":"accepted_plan_id","nullable":true,"type":"uuid"},{"name":"plan_digest","nullable":true,"type":"text"},{"name":"result_bytes","nullable":false,"type":"bytea"},{"name":"created_at","nullable":false,"type":"timestamptz"}],"immutable":true,"name":"receipts","policies":["runtime_scope","operator_scope"],"primary_key":["tenant_id","portfolio_id","id"],"purgeable_transient":false,"rls":"ENABLED_AND_FORCED","scope":"tenant"}',
    '{"columns":[{"name":"tenant_id","nullable":false,"type":"uuid"},{"name":"portfolio_id","nullable":false,"type":"uuid"},{"name":"id","nullable":false,"type":"uuid"},{"name":"receipt_id","nullable":false,"type":"uuid"},{"name":"action","nullable":false,"type":"text"},{"name":"before_accepted_generation","nullable":false,"type":"bigint"},{"name":"after_accepted_generation","nullable":false,"type":"bigint"},{"name":"before_mapping_generation","nullable":false,"type":"bigint"},{"name":"after_mapping_generation","nullable":false,"type":"bigint"},{"name":"created_at","nullable":false,"type":"timestamptz"}],"immutable":true,"name":"audit","policies":["runtime_scope","operator_scope"],"primary_key":["tenant_id","portfolio_id","id"],"purgeable_transient":false,"rls":"ENABLED_AND_FORCED","scope":"tenant"}',
    '{"columns":[{"name":"tenant_id","nullable":false,"type":"uuid"},{"name":"portfolio_id","nullable":false,"type":"uuid"},{"name":"id","nullable":false,"type":"uuid"},{"name":"receipt_id","nullable":false,"type":"uuid"},{"name":"version","nullable":false,"type":"smallint"},{"name":"type","nullable":false,"type":"text"},{"name":"accepted_generation","nullable":false,"type":"bigint"},{"name":"plan_digest","nullable":false,"type":"text"},{"name":"payload_bytes","nullable":false,"type":"bytea"},{"name":"payload_digest","nullable":false,"type":"text"},{"name":"created_at","nullable":false,"type":"timestamptz"},{"name":"dispatched_at","nullable":true,"type":"timestamptz"}],"immutable":false,"name":"outbox","policies":["runtime_scope","operator_scope"],"primary_key":["tenant_id","portfolio_id","id"],"purgeable_transient":false,"rls":"ENABLED_AND_FORCED","scope":"tenant"}',
    '{"columns":[{"name":"tenant_id","nullable":false,"type":"uuid"},{"name":"portfolio_id","nullable":false,"type":"uuid"},{"name":"bucket","nullable":false,"type":"text"},{"name":"window_start","nullable":false,"type":"timestamptz"},{"name":"used_count","nullable":false,"type":"bigint"},{"name":"reserved_bytes","nullable":false,"type":"bigint"},{"name":"lease_count","nullable":false,"type":"bigint"},{"name":"outstanding_sets","nullable":false,"type":"bigint"}],"immutable":false,"name":"quotas","policies":["runtime_scope","operator_scope"],"primary_key":["tenant_id","portfolio_id","bucket"],"purgeable_transient":false,"rls":"ENABLED_AND_FORCED","scope":"tenant"}',
    '{"columns":[{"name":"id","nullable":false,"type":"smallint"},{"name":"wrapper_catalog_bytes","nullable":false,"type":"bytea"},{"name":"wrapper_catalog_digest","nullable":false,"type":"text"},{"name":"runtime_profile_digest","nullable":false,"type":"text"},{"name":"ready","nullable":false,"type":"boolean"}],"immutable":false,"name":"instance_state","policies":[],"primary_key":["id"],"purgeable_transient":false,"rls":"NO_APP_RAW_ACCESS","scope":"instance"}',
    '{"columns":[{"name":"bucket","nullable":false,"type":"text"},{"name":"window_start","nullable":false,"type":"timestamptz"},{"name":"used_count","nullable":false,"type":"bigint"},{"name":"reserved_bytes","nullable":false,"type":"bigint"},{"name":"lease_count","nullable":false,"type":"bigint"},{"name":"outstanding_sets","nullable":false,"type":"bigint"}],"immutable":false,"name":"instance_budgets","policies":[],"primary_key":["bucket"],"purgeable_transient":false,"rls":"NO_APP_RAW_ACCESS","scope":"instance"}',
    '{"columns":[{"name":"id","nullable":false,"type":"uuid"},{"name":"login_role","nullable":false,"type":"name"},{"name":"peer_identity","nullable":false,"type":"text"},{"name":"enabled","nullable":false,"type":"boolean"},{"name":"credential_epoch","nullable":false,"type":"bigint"}],"immutable":false,"name":"workers","policies":[],"primary_key":["id"],"purgeable_transient":false,"rls":"NO_APP_RAW_ACCESS","scope":"instance"}',
)

_FOREIGN_KEYS = (
    '{"columns":["tenant_id","portfolio_id"],"deferrable_initially_deferred":true,"name":"roots_portfolio_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"roots","target":"wl_pg.portfolios","target_columns":["tenant_id","portfolio_id"]}',
    '{"columns":["tenant_id","portfolio_id"],"deferrable_initially_deferred":true,"name":"sets_portfolio_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"sets","target":"wl_pg.portfolios","target_columns":["tenant_id","portfolio_id"]}',
    '{"columns":["tenant_id","portfolio_id"],"deferrable_initially_deferred":true,"name":"members_portfolio_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"members","target":"wl_pg.portfolios","target_columns":["tenant_id","portfolio_id"]}',
    '{"columns":["tenant_id","portfolio_id"],"deferrable_initially_deferred":true,"name":"leases_portfolio_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"leases","target":"wl_pg.portfolios","target_columns":["tenant_id","portfolio_id"]}',
    '{"columns":["tenant_id","portfolio_id"],"deferrable_initially_deferred":true,"name":"stages_portfolio_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"stages","target":"wl_pg.portfolios","target_columns":["tenant_id","portfolio_id"]}',
    '{"columns":["tenant_id","portfolio_id"],"deferrable_initially_deferred":true,"name":"decisions_portfolio_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"decisions","target":"wl_pg.portfolios","target_columns":["tenant_id","portfolio_id"]}',
    '{"columns":["tenant_id","portfolio_id"],"deferrable_initially_deferred":true,"name":"previews_portfolio_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"previews","target":"wl_pg.portfolios","target_columns":["tenant_id","portfolio_id"]}',
    '{"columns":["tenant_id","portfolio_id"],"deferrable_initially_deferred":true,"name":"accepted_inputs_portfolio_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"accepted_inputs","target":"wl_pg.portfolios","target_columns":["tenant_id","portfolio_id"]}',
    '{"columns":["tenant_id","portfolio_id"],"deferrable_initially_deferred":true,"name":"accepted_plans_portfolio_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"accepted_plans","target":"wl_pg.portfolios","target_columns":["tenant_id","portfolio_id"]}',
    '{"columns":["tenant_id","portfolio_id"],"deferrable_initially_deferred":true,"name":"source_revisions_portfolio_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"source_revisions","target":"wl_pg.portfolios","target_columns":["tenant_id","portfolio_id"]}',
    '{"columns":["tenant_id","portfolio_id"],"deferrable_initially_deferred":true,"name":"activity_heads_portfolio_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"activity_heads","target":"wl_pg.portfolios","target_columns":["tenant_id","portfolio_id"]}',
    '{"columns":["tenant_id","portfolio_id"],"deferrable_initially_deferred":true,"name":"snapshot_heads_portfolio_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"snapshot_heads","target":"wl_pg.portfolios","target_columns":["tenant_id","portfolio_id"]}',
    '{"columns":["tenant_id","portfolio_id"],"deferrable_initially_deferred":true,"name":"mappings_portfolio_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"mappings","target":"wl_pg.portfolios","target_columns":["tenant_id","portfolio_id"]}',
    '{"columns":["tenant_id","portfolio_id"],"deferrable_initially_deferred":true,"name":"authority_links_portfolio_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"authority_links","target":"wl_pg.portfolios","target_columns":["tenant_id","portfolio_id"]}',
    '{"columns":["tenant_id","portfolio_id"],"deferrable_initially_deferred":true,"name":"lineage_portfolio_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"lineage","target":"wl_pg.portfolios","target_columns":["tenant_id","portfolio_id"]}',
    '{"columns":["tenant_id","portfolio_id"],"deferrable_initially_deferred":true,"name":"receipts_portfolio_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"receipts","target":"wl_pg.portfolios","target_columns":["tenant_id","portfolio_id"]}',
    '{"columns":["tenant_id","portfolio_id"],"deferrable_initially_deferred":true,"name":"audit_portfolio_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"audit","target":"wl_pg.portfolios","target_columns":["tenant_id","portfolio_id"]}',
    '{"columns":["tenant_id","portfolio_id"],"deferrable_initially_deferred":true,"name":"outbox_portfolio_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"outbox","target":"wl_pg.portfolios","target_columns":["tenant_id","portfolio_id"]}',
    '{"columns":["tenant_id","portfolio_id"],"deferrable_initially_deferred":true,"name":"quotas_portfolio_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"quotas","target":"wl_pg.portfolios","target_columns":["tenant_id","portfolio_id"]}',
    '{"columns":["tenant_id","portfolio_id","set_id"],"deferrable_initially_deferred":true,"name":"members_set_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"members","target":"wl_ingestion.sets","target_columns":["tenant_id","portfolio_id","id"]}',
    '{"columns":["tenant_id","portfolio_id","set_id"],"deferrable_initially_deferred":true,"name":"leases_set_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"leases","target":"wl_ingestion.sets","target_columns":["tenant_id","portfolio_id","id"]}',
    '{"columns":["tenant_id","portfolio_id","set_id"],"deferrable_initially_deferred":true,"name":"stages_set_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"stages","target":"wl_ingestion.sets","target_columns":["tenant_id","portfolio_id","id"]}',
    '{"columns":["tenant_id","portfolio_id","set_id"],"deferrable_initially_deferred":true,"name":"decisions_set_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"decisions","target":"wl_ingestion.sets","target_columns":["tenant_id","portfolio_id","id"]}',
    '{"columns":["tenant_id","portfolio_id","set_id"],"deferrable_initially_deferred":true,"name":"previews_set_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"previews","target":"wl_ingestion.sets","target_columns":["tenant_id","portfolio_id","id"]}',
    '{"columns":["tenant_id","portfolio_id","set_id","member_id"],"deferrable_initially_deferred":true,"name":"stage_member_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"stages","target":"wl_ingestion.members","target_columns":["tenant_id","portfolio_id","set_id","id"]}',
    '{"columns":["tenant_id","portfolio_id","input_id"],"deferrable_initially_deferred":true,"name":"source_input_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"source_revisions","target":"wl_ingestion.accepted_inputs","target_columns":["tenant_id","portfolio_id","id"]}',
    '{"columns":["tenant_id","portfolio_id","parent_id"],"deferrable_initially_deferred":true,"name":"source_parent_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"source_revisions","target":"wl_ingestion.source_revisions","target_columns":["tenant_id","portfolio_id","id"]}',
    '{"columns":["tenant_id","portfolio_id","revision_id"],"deferrable_initially_deferred":true,"name":"activity_heads_revision_id_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"activity_heads","target":"wl_ingestion.source_revisions","target_columns":["tenant_id","portfolio_id","id"]}',
    '{"columns":["tenant_id","portfolio_id","latest_revision_id"],"deferrable_initially_deferred":true,"name":"snapshot_heads_latest_revision_id_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"snapshot_heads","target":"wl_ingestion.source_revisions","target_columns":["tenant_id","portfolio_id","id"]}',
    '{"columns":["tenant_id","portfolio_id","complete_base_revision_id"],"deferrable_initially_deferred":true,"name":"snapshot_heads_complete_base_revision_id_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"snapshot_heads","target":"wl_ingestion.source_revisions","target_columns":["tenant_id","portfolio_id","id"]}',
    '{"columns":["tenant_id","portfolio_id","left_revision_id"],"deferrable_initially_deferred":true,"name":"authority_links_left_revision_id_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"authority_links","target":"wl_ingestion.source_revisions","target_columns":["tenant_id","portfolio_id","id"]}',
    '{"columns":["tenant_id","portfolio_id","right_revision_id"],"deferrable_initially_deferred":true,"name":"authority_links_right_revision_id_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"authority_links","target":"wl_ingestion.source_revisions","target_columns":["tenant_id","portfolio_id","id"]}',
    '{"columns":["tenant_id","portfolio_id","source_revision_id"],"deferrable_initially_deferred":true,"name":"lineage_source_revision_id_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"lineage","target":"wl_ingestion.source_revisions","target_columns":["tenant_id","portfolio_id","id"]}',
    '{"columns":["tenant_id","portfolio_id","accepted_plan_id"],"deferrable_initially_deferred":true,"name":"receipt_plan_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"receipts","target":"wl_ingestion.accepted_plans","target_columns":["tenant_id","portfolio_id","id"]}',
    '{"columns":["tenant_id","portfolio_id","receipt_id"],"deferrable_initially_deferred":true,"name":"plan_receipt_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"accepted_plans","target":"wl_ingestion.receipts","target_columns":["tenant_id","portfolio_id","id"]}',
    '{"columns":["tenant_id","portfolio_id","receipt_id"],"deferrable_initially_deferred":true,"name":"audit_receipt_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"audit","target":"wl_ingestion.receipts","target_columns":["tenant_id","portfolio_id","id"]}',
    '{"columns":["tenant_id","portfolio_id","receipt_id"],"deferrable_initially_deferred":true,"name":"outbox_receipt_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"outbox","target":"wl_ingestion.receipts","target_columns":["tenant_id","portfolio_id","id"]}',
    '{"columns":["tenant_id","portfolio_id","plan_id"],"deferrable_initially_deferred":true,"name":"mappings_plan_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"mappings","target":"wl_ingestion.accepted_plans","target_columns":["tenant_id","portfolio_id","id"]}',
    '{"columns":["tenant_id","portfolio_id","plan_id"],"deferrable_initially_deferred":true,"name":"authority_links_plan_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"authority_links","target":"wl_ingestion.accepted_plans","target_columns":["tenant_id","portfolio_id","id"]}',
    '{"columns":["tenant_id","portfolio_id","account_id","account_version"],"deferrable_initially_deferred":true,"name":"snapshot_account_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"snapshot_heads","target":"wl_pg.accounts","target_columns":["tenant_id","portfolio_id","id","version"]}',
    '{"columns":["tenant_id","portfolio_id","connection_id","connection_version"],"deferrable_initially_deferred":true,"name":"member_connection_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"members","target":"wl_pg.connections","target_columns":["tenant_id","portfolio_id","id","version"]}',
    '{"columns":["tenant_id","portfolio_id","connection_id","connection_version"],"deferrable_initially_deferred":true,"name":"member_source_connection_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"members","target":"wl_sources.connection_lifecycle","target_columns":["tenant_id","portfolio_id","id","connection_version"]}',
    '{"columns":["tenant_id","portfolio_id","account_id","account_version"],"deferrable_initially_deferred":true,"name":"mapping_account_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"mappings","target":"wl_pg.accounts","target_columns":["tenant_id","portfolio_id","id","version"]}',
    '{"columns":["tenant_id","portfolio_id","instrument_id","instrument_version"],"deferrable_initially_deferred":true,"name":"mapping_instrument_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"mappings","target":"wl_pg.instruments","target_columns":["tenant_id","portfolio_id","id","version"]}',
    '{"columns":["tenant_id","portfolio_id","issuer_id","issuer_version"],"deferrable_initially_deferred":true,"name":"mapping_issuer_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"mappings","target":"wl_pg.issuers","target_columns":["tenant_id","portfolio_id","id","version"]}',
    '{"columns":["tenant_id","portfolio_id","set_id","member_id"],"deferrable_initially_deferred":true,"name":"lease_member_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"leases","target":"wl_ingestion.members","target_columns":["tenant_id","portfolio_id","set_id","id"]}',
    '{"columns":["worker_id"],"deferrable_initially_deferred":true,"name":"lease_worker_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"leases","target":"wl_ingestion.workers","target_columns":["id"]}',
    '{"columns":["id"],"deferrable_initially_deferred":true,"name":"instance_root_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"instance_state","target":"wl_pg.instance_state","target_columns":["id"]}',
    '{"columns":["installation_id"],"deferrable_initially_deferred":true,"name":"members_installation_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"members","target":"wl_sources.installations","target_columns":["id"]}',
    '{"columns":["installation_id"],"deferrable_initially_deferred":true,"name":"accepted_inputs_installation_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"accepted_inputs","target":"wl_sources.installations","target_columns":["id"]}',
    '{"columns":["actor_user_id"],"deferrable_initially_deferred":true,"name":"set_actor_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"sets","target":"wl_identity.users","target_columns":["id"]}',
    '{"columns":["tenant_id","portfolio_id","input_id"],"deferrable_initially_deferred":true,"name":"lineage_input_fk","on_delete":"NO ACTION","on_update":"NO ACTION","table":"lineage","target":"wl_ingestion.accepted_inputs","target_columns":["tenant_id","portfolio_id","id"]}',
)

_INDEXES = (
    '{"columns":["tenant_id","portfolio_id"],"kind":"PRIMARY_KEY","name":"roots_pk","table":"roots"}',
    '{"columns":["tenant_id","portfolio_id","id"],"kind":"PRIMARY_KEY","name":"sets_pk","table":"sets"}',
    '{"columns":["tenant_id","portfolio_id","set_id","id"],"kind":"PRIMARY_KEY","name":"members_pk","table":"members"}',
    '{"columns":["tenant_id","portfolio_id","id"],"kind":"PRIMARY_KEY","name":"leases_pk","table":"leases"}',
    '{"columns":["tenant_id","portfolio_id","set_id","member_id","digest"],"kind":"PRIMARY_KEY","name":"stages_pk","table":"stages"}',
    '{"columns":["tenant_id","portfolio_id","set_id","revision"],"kind":"PRIMARY_KEY","name":"decisions_pk","table":"decisions"}',
    '{"columns":["tenant_id","portfolio_id","id"],"kind":"PRIMARY_KEY","name":"previews_pk","table":"previews"}',
    '{"columns":["tenant_id","portfolio_id","id"],"kind":"PRIMARY_KEY","name":"accepted_inputs_pk","table":"accepted_inputs"}',
    '{"columns":["tenant_id","portfolio_id","id"],"kind":"PRIMARY_KEY","name":"accepted_plans_pk","table":"accepted_plans"}',
    '{"columns":["tenant_id","portfolio_id","id"],"kind":"PRIMARY_KEY","name":"source_revisions_pk","table":"source_revisions"}',
    '{"columns":["tenant_id","portfolio_id","economic_group_id"],"kind":"PRIMARY_KEY","name":"activity_heads_pk","table":"activity_heads"}',
    '{"columns":["tenant_id","portfolio_id","key_digest"],"kind":"PRIMARY_KEY","name":"snapshot_heads_pk","table":"snapshot_heads"}',
    '{"columns":["tenant_id","portfolio_id","id","revision"],"kind":"PRIMARY_KEY","name":"mappings_pk","table":"mappings"}',
    '{"columns":["tenant_id","portfolio_id","id","revision"],"kind":"PRIMARY_KEY","name":"authority_links_pk","table":"authority_links"}',
    '{"columns":["tenant_id","portfolio_id","source_revision_id","input_id","collection","local_id"],"kind":"PRIMARY_KEY","name":"lineage_pk","table":"lineage"}',
    '{"columns":["tenant_id","portfolio_id","id"],"kind":"PRIMARY_KEY","name":"receipts_pk","table":"receipts"}',
    '{"columns":["tenant_id","portfolio_id","id"],"kind":"PRIMARY_KEY","name":"audit_pk","table":"audit"}',
    '{"columns":["tenant_id","portfolio_id","id"],"kind":"PRIMARY_KEY","name":"outbox_pk","table":"outbox"}',
    '{"columns":["tenant_id","portfolio_id","bucket"],"kind":"PRIMARY_KEY","name":"quotas_pk","table":"quotas"}',
    '{"columns":["id"],"kind":"PRIMARY_KEY","name":"instance_state_pk","table":"instance_state"}',
    '{"columns":["bucket"],"kind":"PRIMARY_KEY","name":"instance_budgets_pk","table":"instance_budgets"}',
    '{"columns":["id"],"kind":"PRIMARY_KEY","name":"workers_pk","table":"workers"}',
    '{"columns":["tenant_id","portfolio_id","set_id","ordinal"],"kind":"UNIQUE","name":"members_ordinal_uq","table":"members"}',
    '{"columns":["tenant_id","portfolio_id","incarnation","restore_epoch","operation_id"],"kind":"UNIQUE","name":"receipts_operation_uq","table":"receipts"}',
    '{"columns":["tenant_id","portfolio_id","source_key","source_revision"],"kind":"UNIQUE","name":"source_revision_uq","table":"source_revisions"}',
    '{"columns":["tenant_id","portfolio_id","digest"],"kind":"UNIQUE","name":"input_digest_uq","table":"accepted_inputs"}',
    '{"columns":["tenant_id","portfolio_id","digest"],"kind":"UNIQUE","name":"plan_digest_uq","table":"accepted_plans"}',
    '{"columns":["tenant_id","portfolio_id","receipt_id","action"],"kind":"UNIQUE","name":"audit_action_uq","table":"audit"}',
    '{"columns":["tenant_id","portfolio_id","receipt_id","type"],"kind":"UNIQUE","name":"outbox_type_uq","table":"outbox"}',
    '{"columns":["tenant_id","portfolio_id","set_id","member_id"],"kind":"UNIQUE_PARTIAL_NORMALIZE_ACTIVE","name":"live_member_lease_uq","table":"leases"}',
    '{"columns":["tenant_id","portfolio_id","set_id"],"kind":"UNIQUE_PARTIAL_PREPARE_ACTIVE","name":"live_plan_lease_uq","table":"leases"}',
    '{"columns":["expires_at","state"],"kind":"INDEX","name":"sets_expiry_idx","table":"sets"}',
    '{"columns":["expires_at","state"],"kind":"INDEX","name":"lease_expiry_idx","table":"leases"}',
    '{"columns":["purge_at"],"kind":"INDEX","name":"stage_purge_idx","table":"stages"}',
    '{"columns":["purge_at"],"kind":"INDEX","name":"decision_purge_idx","table":"decisions"}',
    '{"columns":["purge_at"],"kind":"INDEX","name":"preview_purge_idx","table":"previews"}',
    '{"columns":["tenant_id","portfolio_id","parent_id"],"kind":"INDEX","name":"source_revision_parent_idx","table":"source_revisions"}',
    '{"columns":["tenant_id","portfolio_id","revision_id"],"kind":"INDEX","name":"activity_head_revision_idx","table":"activity_heads"}',
    '{"columns":["worker_id","claim_request_id"],"kind":"UNIQUE_PARTIAL_CLAIM_REQUEST_NOT_NULL","name":"worker_claim_request_uq","table":"leases"}',
)

_TRIGGERS = (
    '{"events":["INSERT","UPDATE","DELETE"],"function":"_transition_v1","name":"roots_guard","table":"roots","timing":"BEFORE","truncate_denied_by":"No app TRUNCATE grants; operator maintenance only"}',
    '{"events":["INSERT","UPDATE","DELETE"],"function":"_transition_v1","name":"sets_guard","table":"sets","timing":"BEFORE","truncate_denied_by":"No app TRUNCATE grants; operator maintenance only"}',
    '{"events":["INSERT","UPDATE","DELETE"],"function":"_transition_v1","name":"members_guard","table":"members","timing":"BEFORE","truncate_denied_by":"No app TRUNCATE grants; operator maintenance only"}',
    '{"events":["INSERT","UPDATE","DELETE"],"function":"_transition_v1","name":"leases_guard","table":"leases","timing":"BEFORE","truncate_denied_by":"No app TRUNCATE grants; operator maintenance only"}',
    '{"events":["INSERT","UPDATE","DELETE"],"function":"_transition_v1","name":"stages_guard","table":"stages","timing":"BEFORE","truncate_denied_by":"No app TRUNCATE grants; operator maintenance only"}',
    '{"events":["INSERT","UPDATE","DELETE"],"function":"_transition_v1","name":"decisions_guard","table":"decisions","timing":"BEFORE","truncate_denied_by":"No app TRUNCATE grants; operator maintenance only"}',
    '{"events":["INSERT","UPDATE","DELETE"],"function":"_transition_v1","name":"previews_guard","table":"previews","timing":"BEFORE","truncate_denied_by":"No app TRUNCATE grants; operator maintenance only"}',
    '{"events":["INSERT","UPDATE","DELETE"],"function":"_immutable_v1","name":"accepted_inputs_guard","table":"accepted_inputs","timing":"BEFORE","truncate_denied_by":"No app TRUNCATE grants; operator maintenance only"}',
    '{"events":["INSERT","UPDATE","DELETE"],"function":"_immutable_v1","name":"accepted_plans_guard","table":"accepted_plans","timing":"BEFORE","truncate_denied_by":"No app TRUNCATE grants; operator maintenance only"}',
    '{"events":["INSERT","UPDATE","DELETE"],"function":"_immutable_v1","name":"source_revisions_guard","table":"source_revisions","timing":"BEFORE","truncate_denied_by":"No app TRUNCATE grants; operator maintenance only"}',
    '{"events":["INSERT","UPDATE","DELETE"],"function":"_head_v1","name":"activity_heads_guard","table":"activity_heads","timing":"BEFORE","truncate_denied_by":"No app TRUNCATE grants; operator maintenance only"}',
    '{"events":["INSERT","UPDATE","DELETE"],"function":"_head_v1","name":"snapshot_heads_guard","table":"snapshot_heads","timing":"BEFORE","truncate_denied_by":"No app TRUNCATE grants; operator maintenance only"}',
    '{"events":["INSERT","UPDATE","DELETE"],"function":"_immutable_v1","name":"mappings_guard","table":"mappings","timing":"BEFORE","truncate_denied_by":"No app TRUNCATE grants; operator maintenance only"}',
    '{"events":["INSERT","UPDATE","DELETE"],"function":"_immutable_v1","name":"authority_links_guard","table":"authority_links","timing":"BEFORE","truncate_denied_by":"No app TRUNCATE grants; operator maintenance only"}',
    '{"events":["INSERT","UPDATE","DELETE"],"function":"_immutable_v1","name":"lineage_guard","table":"lineage","timing":"BEFORE","truncate_denied_by":"No app TRUNCATE grants; operator maintenance only"}',
    '{"events":["INSERT","UPDATE","DELETE"],"function":"_immutable_v1","name":"receipts_guard","table":"receipts","timing":"BEFORE","truncate_denied_by":"No app TRUNCATE grants; operator maintenance only"}',
    '{"events":["INSERT","UPDATE","DELETE"],"function":"_immutable_v1","name":"audit_guard","table":"audit","timing":"BEFORE","truncate_denied_by":"No app TRUNCATE grants; operator maintenance only"}',
    '{"events":["INSERT","UPDATE","DELETE"],"function":"_outbox_guard_v1","name":"outbox_guard","table":"outbox","timing":"BEFORE","truncate_denied_by":"No app TRUNCATE grants; operator maintenance only"}',
    '{"events":["INSERT","UPDATE","DELETE"],"function":"_transition_v1","name":"quotas_guard","table":"quotas","timing":"BEFORE","truncate_denied_by":"No app TRUNCATE grants; operator maintenance only"}',
    '{"events":["INSERT","UPDATE","DELETE"],"function":"_transition_v1","name":"instance_state_guard","table":"instance_state","timing":"BEFORE","truncate_denied_by":"No app TRUNCATE grants; operator maintenance only"}',
    '{"events":["INSERT","UPDATE","DELETE"],"function":"_transition_v1","name":"instance_budgets_guard","table":"instance_budgets","timing":"BEFORE","truncate_denied_by":"No app TRUNCATE grants; operator maintenance only"}',
    '{"events":["INSERT","UPDATE","DELETE"],"function":"_transition_v1","name":"workers_guard","table":"workers","timing":"BEFORE","truncate_denied_by":"No app TRUNCATE grants; operator maintenance only"}',
)

_FUNCTIONS = (
    '{"arguments":["text","uuid","bigint","jsonb","text","jsonb"],"execute":"identity_source_gateway","name":"create_set_v1","returns":"jsonb","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["text","uuid","bigint","jsonb","text","jsonb"],"execute":"identity_source_gateway","name":"read_sets_v1","returns":"jsonb","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["text","uuid","bigint","jsonb","text","jsonb"],"execute":"identity_source_gateway","name":"read_set_v1","returns":"jsonb","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["text","uuid","bigint","jsonb","text","jsonb"],"execute":"identity_source_gateway","name":"decide_set_v1","returns":"jsonb","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["text","uuid","bigint","jsonb","text","jsonb"],"execute":"identity_source_gateway","name":"read_preview_v1","returns":"jsonb","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["text","uuid","bigint","jsonb","text","jsonb"],"execute":"identity_source_gateway","name":"accept_preview_v1","returns":"jsonb","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["text","uuid","bigint","jsonb","text","jsonb"],"execute":"identity_source_gateway","name":"cancel_set_v1","returns":"jsonb","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["text","uuid","bigint","jsonb","text","jsonb"],"execute":"identity_source_gateway","name":"read_receipt_v1","returns":"jsonb","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["text","uuid","bigint","jsonb","text","jsonb"],"execute":"identity_source_gateway","name":"reserve_member_v1","returns":"jsonb","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["uuid","text","jsonb","bytea"],"execute":"ingestion_worker_only","name":"claim_member_v1","returns":"jsonb","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["uuid","text","jsonb","bytea"],"execute":"ingestion_worker_only","name":"renew_member_v1","returns":"jsonb","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["uuid","text","jsonb","bytea"],"execute":"ingestion_worker_only","name":"admit_stage_v1","returns":"jsonb","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["uuid","text","jsonb","bytea"],"execute":"ingestion_worker_only","name":"prepare_preview_v1","returns":"jsonb","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["uuid","text","jsonb","bytea"],"execute":"ingestion_worker_only","name":"finish_member_v1","returns":"jsonb","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["uuid","text","jsonb","bytea"],"execute":"ingestion_worker_only","name":"cleanup_set_v1","returns":"jsonb","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["uuid","text","jsonb","bytea"],"execute":"ingestion_worker_only","name":"claim_plan_v1","returns":"jsonb","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["uuid","text","jsonb","bytea"],"execute":"ingestion_worker_only","name":"read_plan_basis_v1","returns":"jsonb","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["text","uuid","bigint","jsonb","text"],"execute":"operator_owner_only","name":"_guard_user_v1","returns":"jsonb","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["uuid","text","jsonb"],"execute":"operator_owner_only","name":"_guard_worker_v1","returns":"jsonb","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["jsonb"],"execute":"operator_owner_only","name":"_canonical_v1","returns":"bytea","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["bytea"],"execute":"operator_owner_only","name":"_validate_minimal_v1","returns":"jsonb","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["uuid","uuid","uuid","bytea"],"execute":"operator_owner_only","name":"_validate_plan_v1","returns":"jsonb","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["uuid","uuid","text","bigint","bigint"],"execute":"operator_owner_only","name":"_quota_v1","returns":"void","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["uuid","uuid","uuid"],"execute":"operator_owner_only","name":"_references_v1","returns":"void","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["uuid","uuid","uuid","bigint","uuid","text","text"],"execute":"operator_owner_only","name":"_replay_v1","returns":"jsonb","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["uuid","uuid","uuid","uuid"],"execute":"operator_owner_only","name":"_effects_v1","returns":"jsonb","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":["uuid","uuid","uuid"],"execute":"operator_owner_only","name":"_purge_v1","returns":"void","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":[],"execute":"operator_owner_only","name":"_immutable_v1","returns":"trigger","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":[],"execute":"operator_owner_only","name":"_transition_v1","returns":"trigger","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":[],"execute":"operator_owner_only","name":"_head_v1","returns":"trigger","search_path":"pg_catalog,pg_temp","security_definer":true}',
    '{"arguments":[],"execute":"operator_owner_only","name":"_outbox_guard_v1","returns":"trigger","search_path":"pg_catalog,pg_temp","security_definer":true}',
)

def inventory():
    """Isolated copies of fixed catalog expectations, never sampled from a DB."""
    return {"tables": [json.loads(x) for x in _TABLES],
            "foreign_keys": [json.loads(x) for x in _FOREIGN_KEYS],
            "indexes_and_unique_constraints": [json.loads(x) for x in _INDEXES],
            "triggers": [json.loads(x) for x in _TRIGGERS],
            "functions": [json.loads(x) for x in _FUNCTIONS]}


TABLES = tuple(json.loads(x)["name"] for x in _TABLES)
TENANT_TABLES = tuple(json.loads(x)["name"] for x in _TABLES
                      if json.loads(x)["scope"] == "tenant")
READ_TABLES = ("roots", "accepted_inputs", "accepted_plans", "source_revisions",
               "activity_heads", "snapshot_heads", "mappings", "authority_links",
               "lineage", "receipts", "audit", "outbox")
GATEWAY = tuple(json.loads(x)["name"] for x in _FUNCTIONS
                if json.loads(x)["execute"] == "identity_source_gateway")
WORKER = tuple(json.loads(x)["name"] for x in _FUNCTIONS
               if json.loads(x)["execute"] == "ingestion_worker_only")


def signature(name):
    for row in _FUNCTIONS:
        value = json.loads(row)
        if value["name"] == name:
            return SCHEMA + "." + name + "(" + ",".join(value["arguments"]) + ")"
    raise ValueError("Unknown ingestion function")


# These expressions are generated only from code-owned closed schemas. They
# check shape/scalars, not local graph, current authority or acceptance effects.
# No SQL function is installed or granted by this renderer.
class _SchemaPredicate:
    def __init__(self):
        self.ordinal = 0

    @staticmethod
    def literal(value):
        return "E'" + value.replace("\\", "\\\\").replace("'", "''") + "'"

    def compile(self, value='payload', schema=None, namespace='core', trail=()):
        from ..ingestion.contracts import definition
        schema = definition('Minimal') if schema is None else schema
        allowed = {'$ref', 'additionalProperties', 'anyOf', 'enum', 'items', 'maxItems',
                   'maxLength', 'maximum', 'minimum', 'pattern', 'properties', 'required', 'type'}
        if schema.keys() - allowed:
            raise ValueError('Unknown schema keyword')
        if '$ref' in schema:
            prefix, name = schema['$ref'].split('#/$defs/', 1)
            namespace = namespace if not prefix else {'codec-schema.json': 'core',
                'wire-contracts.json': 'wire', 'frozen-shapes.json': 'frozen'}[prefix]
            if (name, namespace) in trail:
                raise ValueError('Recursive source schema')
            return self.compile(value, definition(name, namespace), namespace,
                                (*trail, (name, namespace)))
        if 'anyOf' in schema:
            return '(COALESCE((' + ' OR '.join(self.compile(value, x, namespace, trail)
                                              for x in schema['anyOf']) + '),false))'
        checks = []
        if 'enum' in schema:
            choices = []
            for item in schema['enum']:
                literal = self.literal(json.dumps(item, ensure_ascii=False, separators=(',', ':')))
                comparison = '(' + value + ')=' + literal + '::jsonb'
                # JSONB numeric equality ignores scale: 1.0 equals 1. Retain
                # the integer enum's canonical numeric representation here.
                # A byte entry point must also reject lost exponent spelling.
                if type(item) is int:
                    comparison += ' AND (' + value + ')::text=' + self.literal(str(item))
                choices.append('(' + comparison + ')')
            checks.append('(' + ' OR '.join(choices) + ')')
        kind = schema.get('type')
        if kind is None:
            if not checks:
                raise ValueError('Unconstrained schema')
            return '(COALESCE((' + ' AND '.join(checks) + '),false))'
        if kind == 'object':
            properties = schema['properties']
            names = 'ARRAY[' + ','.join(self.literal(x) for x in properties) + ']::text[]'
            required = 'ARRAY[' + ','.join(self.literal(x) for x in schema['required']) + ']::text[]'
            checks.append('(' + value + ') ?& ' + required)
            if schema['additionalProperties'] is not False:
                raise ValueError('Only closed objects supported')
            checks.append('(' + value + ')-' + names + "='{}'::jsonb")
            for name, child in properties.items():
                predicate = self.compile('(' + value + ')->' + self.literal(name), child, namespace, trail)
                if name not in schema['required']:
                    predicate = '(NOT ((' + value + ') ? ' + self.literal(name) + ') OR ' + predicate + ')'
                checks.append(predicate)
        elif kind == 'array':
            self.ordinal += 1
            alias = 'child_' + str(self.ordinal)
            checks.append('pg_catalog.jsonb_array_length(' + value + ')<=' + str(schema['maxItems']))
            predicate = self.compile(alias + '.value', schema['items'], namespace, trail)
            checks.append('NOT EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(' + value + ') '
                          + alias + '(value) WHERE NOT ' + predicate + ')')
        elif kind == 'string':
            text = '((' + value + ")#>>'{}')"
            checks.append('pg_catalog.length(' + text + ')<=' + str(schema.get('maxLength', 4096)))
            # JSONB already rejects U+0000. Check the remaining C0 code points
            # explicitly; regex control classes can also reject allowed C1 text.
            controls = '||'.join('pg_catalog.chr(' + str(code) + ')' for code in range(1, 32))
            checks.append('pg_catalog.translate(' + text + ',' + controls + ",E'')=" + text)
            if 'pattern' in schema:
                pattern = schema['pattern'].replace(r'\d', '[0-9]').replace(r'\w', '[A-Za-z0-9_]')
                checks.append(text + ' COLLATE "C" ~ ' + self.literal(pattern))
        elif kind == 'integer':
            text = '((' + value + ")#>>'{}')"
            checks.append(text + ' COLLATE "C" ~ \'^-?(0|[1-9][0-9]*)$\'')
            if 'minimum' in schema:
                checks.append(text + '::numeric>=' + str(schema['minimum']))
            if 'maximum' in schema:
                checks.append(text + '::numeric<=' + str(schema['maximum']))
        elif kind not in {'boolean', 'null'}:
            raise ValueError('Unknown structural type')
        actual_kind = 'number' if kind == 'integer' else kind
        inner = ' AND '.join('(' + x + ')' for x in checks) or 'true'
        return '(CASE WHEN pg_catalog.jsonb_typeof(' + value + ')=' + self.literal(actual_kind) + \
               ' THEN COALESCE((' + inner + '),false) ELSE false END)'




class _MinimalScalarPredicate(_SchemaPredicate):
    def compile(self, value='payload', schema=None, namespace='core', trail=()):
        result = super().compile(value, schema, namespace, trail)
        if schema is None or '$ref' not in schema:
            return result
        prefix, name = schema['$ref'].split('#/$defs/', 1)
        ns = namespace if not prefix else {'codec-schema.json': 'core',
            'wire-contracts.json': 'wire', 'frozen-shapes.json': 'frozen'}[prefix]
        extra = self.scalar(name, value) if ns == 'core' else None
        if extra is None:
            return result
        return '(CASE WHEN ' + result + ' THEN COALESCE((' + extra + '),false) ELSE false END)'

    @staticmethod
    def text(value):
        return '((' + value + ")#>>'{}')"

    def scalar(self, name, value):
        text = self.text(value)
        null = "'null'::jsonb"
        if name == 'Counter':
            return '(pg_catalog.length(' + text + ')<19 OR ' + text + ' COLLATE "C"<=\'9223372036854775807\')'
        if name == 'UUID':
            return text + "<>'00000000-0000-0000-0000-000000000000'"
        if name == 'Decimal':
            digits = 'pg_catalog.replace(pg_catalog.replace(' + text + ",'-',''),'.','')"
            return ('pg_catalog.length(pg_catalog.rtrim(pg_catalog.ltrim(' + digits + ",'0'),'0'))<=38 AND "
                'pg_catalog.length(pg_catalog.rtrim(pg_catalog.split_part(' + text + ",'.',2),'0'))<=24 AND "
                'pg_catalog.length(pg_catalog.ltrim(pg_catalog.split_part(pg_catalog.ltrim(' + text +
                ",'-'),'.',1),'0'))<=38")
        if name in {'Instant', 'Date', 'LegacyTime'}:
            return self.time(value, name)
        if name == 'Identity':
            return ("CASE WHEN (" + value + ")->>'change'='original' THEN (" + value + ")->'parent'=" + null +
                ' AND (' + value + ")->'revision_reason'=" + null + ' ELSE (' + value + ")->'parent'<>" + null +
                ' AND (' + value + ")->'revision_reason'<>" + null + ' AND (' + value + ")->>'revision_reason'<>'' END")
        if name in {'Claim', 'SourceKey'}:
            kind = '(' + value + ")->>'kind'"
            account = '(' + value + ")->'source_account_key'"
            record = '(' + value + ")->'record_kind'"
            result = ('CASE WHEN ' + kind + " IN ('holdings','cash_flows','crypto_transactions','activity') THEN " +
                account + '<>' + null + ' AND ' + record + '=' + null + ' WHEN ' + kind + "='coverage' THEN " +
                account + '<>' + null + ' AND ' + record + '<>' + null + ' ELSE ' + account + '=' + null +
                ' AND ' + record + '=' + null + ' AND (' + value + ")->>'observation_id'='' END")
            if name == 'SourceKey':
                result += (' AND (' + value + ")->>'collection'=CASE WHEN " + kind +
                    " IN ('holdings','cash_flows','crypto_transactions','activity') THEN 'records' WHEN " +
                    kind + "='snapshot' THEN 'snapshots' ELSE " + kind + ' END')
            return result
        if name in {'InstrumentScope', 'CanonicalInstrumentScope'}:
            key = 'asset_local_ids' if name == 'InstrumentScope' else 'instrument_ids'
            ids = '(' + value + ')->' + self.literal(key)
            return ('(SELECT pg_catalog.count(*)=pg_catalog.count(DISTINCT entry.value) AND COALESCE('
                "pg_catalog.jsonb_agg(entry.value ORDER BY entry.value#>>'{}' COLLATE \"C\"),'[]'::jsonb)=" + ids +
                ' FROM pg_catalog.jsonb_array_elements(' + ids + ') entry(value)) AND CASE (' + value +
                ")->>'tag' WHEN 'all' THEN " + ids + "='[]'::jsonb AND (" + value + ")->'category'=" + null +
                " WHEN 'category' THEN " + ids + "='[]'::jsonb AND (" + value + ")->'category'<>" + null +
                " ELSE " + ids + "<>'[]'::jsonb AND (" + value + ")->'category'=" + null + ' END')
        if name == 'Support':
            reasons = '(' + value + ")->'reasons'"
            return ('(SELECT pg_catalog.count(*)=pg_catalog.count(DISTINCT entry.value) '
                'FROM pg_catalog.jsonb_array_elements(' + reasons + ') entry(value)) AND '
                '(((' + value + ")->>'classification'='supported_shape')=(" + reasons + "='[]'::jsonb))")
        if name == 'Diagnostic':
            rows = '(' + value + ")->'row_count'"
            duplicates = '(' + value + ")->'duplicate_count'"
            return ('CASE WHEN (' + value + ")->>'code'='observed_order_rows' THEN " + rows + '<>' + null +
                ' AND ' + duplicates + '<>' + null + ' AND (' + value + ")->>'duplicate_count' IS NOT NULL AND "
                '((' + value + ")->>'duplicate_count')::numeric<=((" + value + ")->>'row_count')::numeric ELSE " +
                rows + '=' + null + ' AND ' + duplicates + '=' + null + ' END')
        return None

    def time(self, value, name):
        zone = '(' + value + ")->>'zone'"
        result = ('CASE WHEN (' + value + ")->'zone'='null'::jsonb THEN true ELSE " + zone +
            " COLLATE \"C\" ~ '^[A-Za-z0-9_+./-]+$' AND NOT pg_catalog.string_to_array(" + zone +
            ",'/') && ARRAY['.','..'] END")
        token = '(' + value + ")->>'token'"
        if name == 'LegacyTime':
            whitespace = [9, 10, 11, 12, 13, 28, 29, 30, 31, 32, 133, 160, 5760,
                          *range(8192, 8203), 8232, 8233, 8239, 8287, 12288]
            chars = '||'.join('pg_catalog.chr(' + str(x) + ')' for x in whitespace)
            return '(' + result + ') AND pg_catalog.btrim(' + token + ',' + chars + ")<>''"
        year = 'pg_catalog.substr(' + token + ',1,4)::integer'
        month = 'pg_catalog.substr(' + token + ',6,2)::integer'
        day = 'pg_catalog.substr(' + token + ',9,2)::integer'
        leap = '(' + year + '%4=0 AND (' + year + '%100<>0 OR ' + year + '%400=0))'
        result = ('(' + result + ') AND ' + year + '>=1 AND ' + month + ' BETWEEN 1 AND 12 AND ' +
            day + '>=1 AND ' + day + '<=CASE WHEN ' + month + ' IN (1,3,5,7,8,10,12) THEN 31 WHEN ' +
            month + ' IN (4,6,9,11) THEN 30 WHEN ' + leap + ' THEN 29 ELSE 28 END')
        if name == 'Instant':
            result += (' AND pg_catalog.substr(' + token + ',12,2)::integer<=23 AND pg_catalog.substr(' +
                token + ',15,2)::integer<=59 AND pg_catalog.substr(' + token + ',18,2)::integer<=59 AND (' +
                value + ")->'fractional_digits'=pg_catalog.to_jsonb(COALESCE(pg_catalog.length((" +
                'pg_catalog.regexp_match(' + token + ',' + self.literal(r'\.([0-9]+)') + '))[1]),0)) AND CASE WHEN ' +
                'pg_catalog.right(' + token + ",1)='Z' THEN true ELSE pg_catalog.right(" + token +
                ",6)<>'-00:00' AND pg_catalog.substr(pg_catalog.right(" + token + ',6),2,2)::integer<=23 AND ' +
                'pg_catalog.substr(pg_catalog.right(' + token + ',6),5,2)::integer<=59 END')
        return result


def _minimal_shape_predicate():
    """Render only structural/scalar checks for a fixed SQL payload variable.

    A checked Minimal entry point must additionally verify canonical input bytes,
    graph/reference/financial semantics and its operation's live authority. This
    expression cannot by itself admit a stage or enable an ingestion profile.
    """
    return _MinimalScalarPredicate().compile()




class _MinimalErrorPredicate(_MinimalScalarPredicate):

    def first_error(self, expressions):
        rows = ','.join((f'({i},{expression})' for i, expression in enumerate(expressions)))
        return '(COALESCE((SELECT e.status FROM (VALUES ' + rows + ') AS e(ordinal,status) WHERE e.status<>0 ORDER BY e.ordinal LIMIT 1),0))' if expressions else '0'

    def status(self, value='payload', schema=None, namespace='core', trail=()):
        from ..ingestion.contracts import definition
        schema = definition('Minimal') if schema is None else schema
        self.compile(value, schema, namespace, trail)
        if '$ref' in schema:
            prefix, name = schema['$ref'].split('#/$defs/', 1)
            namespace = namespace if not prefix else {'codec-schema.json': 'core', 'wire-contracts.json': 'wire', 'frozen-shapes.json': 'frozen'}[prefix]
            state = self.status(value, definition(name, namespace), namespace, (*trail, (name, namespace)))
            extra = self.scalar(name, value) if namespace == 'core' else None
            if extra is None:
                return state
            return '(SELECT CASE WHEN checked.status=0 THEN CASE WHEN COALESCE((' + extra + '),false) THEN 0 ELSE 1 END ELSE checked.status END FROM (SELECT ' + state + ') checked(status))'
        if 'anyOf' in schema:
            return '(CASE WHEN ' + ' OR '.join(('(' + self.status(value, item, namespace, trail) + ')=0' for item in schema['anyOf'])) + ' THEN 0 ELSE 1 END)'
        kind = schema.get('type')
        guard = []
        if 'enum' in schema:
            enum_schema = {'enum': schema['enum']}
            guard.append(self.compile(value, enum_schema, namespace, trail))
        if kind is not None:
            actual = 'number' if kind == 'integer' else kind
            guard.append('pg_catalog.jsonb_typeof(' + value + ')=' + self.literal(actual))
        guard = ' AND '.join(('(' + x + ')' for x in guard)) or 'true'
        if kind == 'object':
            props = schema['properties']
            required = 'ARRAY[' + ','.join((self.literal(x) for x in schema['required'])) + ']::text[]'
            names = 'ARRAY[' + ','.join((self.literal(x) for x in props)) + ']::text[]'
            content = self.first_error([self.status('(' + value + ')->' + self.literal(k), v, namespace, trail) if k in schema['required'] else '(CASE WHEN (' + value + ') ? ' + self.literal(k) + ' THEN ' + self.status('(' + value + ')->' + self.literal(k), v, namespace, trail) + ' ELSE 0 END)' for k, v in props.items()])
            inner = 'CASE WHEN (' + value + ') ?& ' + required + ' AND (' + value + ')-' + names + "='{}'::jsonb THEN " + content + ' ELSE 1 END'
        elif kind == 'array':
            self.ordinal += 1
            alias = 'error_child_' + str(self.ordinal)
            child = self.status(alias + '.value', schema['items'], namespace, trail)
            inner = 'CASE WHEN pg_catalog.jsonb_array_length(' + value + ')>' + str(schema['maxItems']) + ' THEN 2 ELSE COALESCE((SELECT x.status FROM (SELECT ' + child + ' AS status,' + alias + '.ordinal FROM pg_catalog.jsonb_array_elements(' + value + ') WITH ORDINALITY ' + alias + '(value,ordinal)) x WHERE x.status<>0 ORDER BY x.ordinal LIMIT 1),0) END'
        elif kind == 'string':
            text = self.text(value)
            inner = 'CASE WHEN pg_catalog.length(' + text + ')>' + str(schema.get('maxLength', 4096)) + ' THEN 2 WHEN ' + self.compile(value, schema, namespace, trail) + ' THEN 0 ELSE 1 END'
        else:
            inner = 'CASE WHEN ' + self.compile(value, schema, namespace, trail) + ' THEN 0 ELSE 1 END'
        return '(CASE WHEN COALESCE((' + guard + '),false) THEN ' + inner + ' ELSE 1 END)'

def _minimal_clock_sql(value):
    """Read explicit offsets for evidence comparison, never head authority.

    Frozen legacy ISO tokens may contain offset seconds and microseconds. Keep
    their unspecified precision and require the same canonical spelling as the
    existing Python evidence comparator; arbitrary legacy text stays unknown.
    """
    compiler = _MinimalScalarPredicate()
    token = '(' + value + ")->>'token'"
    instant_local = 'pg_catalog.regexp_replace(' + token + ", '(Z|[+-][0-9]{2}:[0-9]{2})$','')"
    instant_offset = '(CASE WHEN pg_catalog.right(' + token + ",1)='Z' THEN 0 ELSE (pg_catalog.substr(pg_catalog.right(" + token + ',6),2,2)::integer*60+pg_catalog.substr(pg_catalog.right(' + token + ",6),5,2)::integer)*CASE WHEN pg_catalog.substr(pg_catalog.right(" + token + ",6),1,1)='-' THEN -1 ELSE 1 END END)"
    instant = 'EXTRACT(EPOCH FROM (' + instant_local + ')::timestamp)-60*' + instant_offset
    offset_pattern = r'([+-])([0-9]{2}):([0-9]{2})(:([0-9]{2})(\.([0-9]{6}))?)?$'
    suffix_pattern = r'[+-][0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]{6})?)?$'
    whole_pattern = r'^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{6})?[+-][0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]{6})?)?$'
    local = 'pg_catalog.regexp_replace(' + token + ',' + compiler.literal(suffix_pattern) + ",'')"
    # Validate only local calendar/time with a neutral offset; a real negative
    # offset of -00:00:01 must not be mistaken for the forbidden -00:00 token.
    fake = "pg_catalog.jsonb_build_object('tag','instant','token',(" + local + ")||'+00:00','zone',(" + value + ")->'zone','fractional_digits',CASE WHEN " + local + " LIKE '%.%' THEN 6 ELSE 0 END)"
    parts = 'legacy_parts.parts'
    hours = '(' + parts + ')[2]::integer'
    minutes = '(' + parts + ')[3]::integer'
    seconds = 'COALESCE((' + parts + ')[5]::integer,0)'
    micros = 'COALESCE((' + parts + ')[7]::integer,0)'
    canonical = (hours + '<=23 AND ' + minutes + '<=59 AND ' + seconds + '<=59 AND ' +
        token + " NOT LIKE '%.000000%' AND CASE WHEN (" + parts + ')[4] IS NULL THEN NOT ((' +
        parts + ")[1]='-' AND " + hours + '=0 AND ' + minutes + '=0) ELSE (' + seconds + '>0 OR ' +
        micros + '>0) AND (' + hours + '+' + minutes + '+' + seconds + '>0) END')
    offset = ('(' + hours + '*3600+' + minutes + '*60+' + seconds + '+' + micros +
        "/1000000::numeric)*CASE WHEN (" + parts + ")[1]='-' THEN -1 ELSE 1 END")
    legacy = ('(SELECT CASE WHEN ' + token + ' COLLATE "C" ~ ' + compiler.literal(whole_pattern) +
        ' THEN CASE WHEN (' + compiler.time(fake, 'Instant') + ') AND (' + canonical + ') THEN '
        'EXTRACT(EPOCH FROM (' + local + ')::timestamp)-(' + offset + ') ELSE NULL END ELSE NULL END '
        'FROM (SELECT pg_catalog.regexp_match(' + token + ',' + compiler.literal(offset_pattern) +
        ') AS parts) legacy_parts)')
    return '(CASE WHEN (' + value + ")->>'tag'='instant' THEN " + instant + ' WHEN (' + value + ")->>'tag'='legacy_unspecified' THEN " + legacy + ' ELSE NULL END)'


def _minimal_order_sql(left, right):
    """Return -1/0/1, or SQL NULL when evidence cannot establish comparison."""
    return '(SELECT CASE WHEN lhs-\'legacy\'=rhs-\'legacy\' THEN 0 WHEN lhs->>\'tag\'=\'date_only\' AND rhs->>\'tag\'=\'date_only\' AND lhs->\'zone\'<>\'null\'::jsonb AND lhs->\'zone\'=rhs->\'zone\' THEN CASE WHEN (lhs->>\'token\') COLLATE "C"<(rhs->>\'token\') COLLATE "C" THEN -1 WHEN lhs->>\'token\'=rhs->>\'token\' THEN 0 ELSE 1 END ELSE pg_catalog.sign((' + _minimal_clock_sql('lhs') + ')-(' + _minimal_clock_sql('rhs') + '))::integer END FROM (SELECT (' + left + ') AS lhs,(' + right + ') AS rhs) times)'

def _minimal_contains_sql(selector, at):
    point = _minimal_order_sql(f"({selector})->'at'", at)
    start = _minimal_order_sql(f"({selector})->'start'", at)
    end = _minimal_order_sql(f"({selector})->'end'", at)
    return f"(CASE WHEN ({selector})->>'tag'='point' THEN {point}=0 ELSE ({start}<0 OR ({start}=0 AND (({selector})->>'start_inclusive')::boolean)) AND ({end}>0 OR ({end}=0 AND (({selector})->>'end_inclusive')::boolean)) END)"

def _minimal_unique_sql(array):
    return f'(SELECT count(*)=count(DISTINCT entry.value) FROM pg_catalog.jsonb_array_elements({array}) entry(value))'

def _minimal_ref_sql(table, key):
    return f"((payload->'{table}')->(({key})::integer)) IS NOT NULL"

def _minimal_scope_sql(scope, asset):
    return f"(({scope})->>'tag'='all' OR (({scope})->>'tag'='category' AND (payload->'assets'->(({asset})::integer))->'kind'=({scope})->'category') OR ({scope})->'asset_local_ids' ? ({asset}))"

def _minimal_covered_sql(at, asset=None, selected=False):
    condition = f"cv.value->'account_local_id'=r->'source_account_local_id' AND cv.value->'kind'=r->'source_kind' AND cv.value->'observation_id'=r->'identity'->'observation_id' AND {_minimal_contains_sql("cv.value->'time'", at)}"
    if asset is not None:
        condition += ' AND ' + _minimal_scope_sql("cv.value->'instrument_scope'", asset)
    if selected:
        condition += " AND s->'coverage_local_ids' ? (cv.value->>'local_id')"
    return "EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(payload->'coverage') AS cv(value) WHERE " + condition + ')'

def _minimal_graph_sql():
    statements = []

    def emit(sql):
        statements.append(sql)

    def check(predicate, code='import_invalid'):
        emit('IF (' + predicate + ") IS NOT TRUE THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='" + code + "'; END IF;")
    emit("FOREACH name IN ARRAY ARRAY['accounts','assets','issuers','records','coverage','snapshots'] LOOP")
    check("NOT EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(payload->name) WITH ORDINALITY AS t(v,n) WHERE v->>'local_id'<>(n-1)::text)")
    emit('END LOOP;')
    check("pg_catalog.jsonb_array_length(payload->'records')+pg_catalog.jsonb_array_length(payload->'coverage')+pg_catalog.jsonb_array_length(payload->'snapshots')+CASE WHEN payload->'membership'='null'::jsonb THEN 0 ELSE 1 END<=10000", 'import_limit')
    check("(SELECT count(*)=count(DISTINCT (v->'provider',v->'source_account_key')) FROM pg_catalog.jsonb_array_elements(payload->'accounts') t(v))")
    whitespace = [9, 10, 11, 12, 13, 28, 29, 30, 31, 32, 133, 160, 5760, *range(8192, 8203), 8232, 8233, 8239, 8287, 12288]
    chars = '||'.join(('pg_catalog.chr(' + str(x) + ')' for x in whitespace))
    emit("FOR a IN SELECT value FROM pg_catalog.jsonb_array_elements(payload->'accounts') LOOP")
    check("a->'provider'=payload->'provenance'->'provider_id' AND pg_catalog.btrim(a->>'source_account_key'," + chars + ")<>''")
    emit('END LOOP;')
    emit("FOR a IN SELECT value FROM pg_catalog.jsonb_array_elements(payload->'assets') LOOP")
    check("a->'issuer_local_id'='null'::jsonb OR " + _minimal_ref_sql('issuers', "a->>'issuer_local_id'"))
    check("(SELECT count(*)=count(DISTINCT (v->'scheme',v->'value')) FROM pg_catalog.jsonb_array_elements(a->'identifiers') t(v))")
    check("a->>'kind'<>'CASH' OR (a->'currency'<>'null'::jsonb AND (a->'symbol'='null'::jsonb OR a->'symbol'=a->'currency') AND a->'ticker'='null'::jsonb AND a->'mic'='null'::jsonb AND a->'network'='null'::jsonb AND a->'settlement_identity'='null'::jsonb)")
    check("a->>'kind'<>'SECURITY' OR (a->'currency'<>'null'::jsonb AND COALESCE(a->>'ticker','')<>'' AND COALESCE(a->>'mic','')<>'' AND a->'network'='null'::jsonb AND a->'settlement_identity'='null'::jsonb AND (a->'symbol'='null'::jsonb OR a->'symbol'=a->'ticker'))")
    check("a->>'kind'<>'CRYPTO' OR (COALESCE(a->>'symbol','')<>'' AND COALESCE(a->>'network','')<>'' AND a->'ticker'='null'::jsonb AND a->'mic'='null'::jsonb)")
    emit('END LOOP;')
    emit("IF payload->'membership'<>'null'::jsonb THEN")
    check(_minimal_unique_sql("payload->'membership'->'account_local_ids'"))
    emit("FOR id IN SELECT value FROM pg_catalog.jsonb_array_elements_text(payload->'membership'->'account_local_ids') LOOP")
    check(_minimal_ref_sql('accounts', 'id'))
    emit('END LOOP; END IF;')
    emit("FOR c IN SELECT value FROM pg_catalog.jsonb_array_elements(payload->'coverage') LOOP")
    check(_minimal_ref_sql('accounts', "c->>'account_local_id'"))
    emit("FOR id IN SELECT value FROM pg_catalog.jsonb_array_elements_text(c->'instrument_scope'->'asset_local_ids') LOOP")
    check(_minimal_ref_sql('assets', 'id'))
    emit('END LOOP;')
    emit("IF c->'time'->>'tag'='interval' THEN")
    emit('comparison:=' + _minimal_order_sql("c->'time'->'start'", "c->'time'->'end'") + ';')
    check('comparison IS NOT NULL', 'import_conflict')
    check('comparison<=0')
    emit('END IF; END LOOP;')
    emit("FOR r IN SELECT value FROM pg_catalog.jsonb_array_elements(payload->'records') LOOP")
    check(_minimal_ref_sql('accounts', "r->>'source_account_local_id'"))
    emit("at_value:=CASE WHEN r->>'record_type'='position' THEN r->'as_of' ELSE r->'event_time' END;")
    check(_minimal_covered_sql('at_value'))

    def amount(value):
        check(_minimal_ref_sql('assets', '(' + value + ")->>'asset_local_id'"))
        emit("a:=payload->'assets'->(((" + value + ")->>'asset_local_id')::integer);")
        check('NOT (a->>\'kind\' IN (\'CRYPTO\',\'UNSUPPORTED\') AND pg_catalog.upper(COALESCE(a->>\'symbol\',\'\') COLLATE "C") IN (\'BTC\',\'LBTC\')) OR pg_catalog.substr(pg_catalog.split_part((' + value + ')->>\'quantity\',\'.\',2),9) COLLATE "C" !~ \'[1-9]\'')
    emit("required:=ARRAY[]::text[];IF r->>'record_type'='position' THEN a:=payload->'assets'->((r->>'asset_local_id')::integer);")
    amount('r')
    emit("IF (r->>'quantity')::numeric<0 THEN required:=required||'signed_position'::text;END IF;")
    emit("IF a->>'kind'='UNSUPPORTED' THEN required:=required||'unsupported_instrument'::text;END IF;")
    check("r->'identity'->>'change'<>'void' AND r->'support'->'reasons' ?& required")
    check(_minimal_covered_sql('at_value', "r->>'asset_local_id'"))
    emit("FOREACH field IN ARRAY ARRAY['market_value','unit_price','cost_native','unrealized'] LOOP")
    check("r->field='null'::jsonb OR a->'currency'='null'::jsonb OR r->field->'currency'=a->'currency'")
    emit('END LOOP;')
    check("r->'cost_cad'='null'::jsonb OR r->'cost_cad'->>'currency'='CAD'")
    emit('CONTINUE; END IF;')
    check("pg_catalog.btrim(r->>'source_type'," + chars + ")<>'' AND pg_catalog.btrim(r->>'source_status'," + chars + ")<>''")
    check('r->>\'kind\'=CASE pg_catalog.lower((r->>\'source_type\') COLLATE "C") WHEN \'purchase\' THEN \'BUY\' WHEN \'buy\' THEN \'BUY\' WHEN \'sale\' THEN \'SELL\' WHEN \'sell\' THEN \'SELL\' WHEN \'transfer\' THEN \'TRANSFER\' WHEN \'fee\' THEN \'FEE\' WHEN \'income\' THEN \'INCOME\' WHEN \'deposit\' THEN \'FUNDING\' WHEN \'withdrawal\' THEN \'FUNDING\' WHEN \'funding\' THEN \'FUNDING\' WHEN \'corporate_action\' THEN \'CORPORATE_ACTION\' ELSE \'UNSUPPORTED\' END')
    check("(r->>'source_kind'='cash_flows' OR r->>'kind'='FUNDING')=(r->'cash_flow'<>'null'::jsonb)")
    emit("IF r->'cash_flow'<>'null'::jsonb THEN")
    check("(r->'cash_flow'->'cash_amount'->>'amount')::numeric>0 AND r->'legs'='[]'::jsonb")
    check('pg_catalog.lower((r->>\'source_type\') COLLATE "C") NOT IN (\'deposit\',\'income\') OR r->\'cash_flow\'->>\'direction\'=\'in\'')
    check('pg_catalog.lower((r->>\'source_type\') COLLATE "C") NOT IN (\'withdrawal\',\'fee\') OR r->\'cash_flow\'->>\'direction\'=\'out\'')
    check("r->'cash_flow'->'cash_leg_of'='null'::jsonb OR (r->'cash_flow'->'cash_leg_of'->>'kind'='crypto_transactions' AND r->'cash_flow'->>'boundary'='internal')")
    emit("ELSE IF r->'legs'='[]'::jsonb THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';END IF;END IF;")
    emit("FOR link IN SELECT value FROM pg_catalog.jsonb_array_elements(r->'economic_references'||CASE WHEN r->'cash_flow'='null'::jsonb THEN '[]'::jsonb ELSE pg_catalog.jsonb_build_array(r->'cash_flow'->'counterpart',r->'cash_flow'->'cash_leg_of') END) WHERE value<>'null'::jsonb LOOP")
    check("link->>'kind' IN ('cash_flows','crypto_transactions','activity') AND (link->'revision'<>'null'::jsonb OR r->'identity'->'legacy'<>'null'::jsonb)")
    emit('END LOOP;')
    emit("IF r->>'kind' IN ('UNSUPPORTED','CORPORATE_ACTION') THEN required:=required||'unsupported_activity'::text;END IF;IF r->>'status'='unsupported' THEN required:=required||'unsupported_status'::text;END IF;")
    emit("FOR item IN SELECT value FROM pg_catalog.jsonb_array_elements(r->'legs') LOOP")
    check(_minimal_ref_sql('accounts', "item->>'account_local_id'"))
    amount('item')
    check(_minimal_covered_sql('at_value', "item->>'asset_local_id'"))
    emit("IF payload->'assets'->((item->>'asset_local_id')::integer)->>'kind'='UNSUPPORTED' THEN required:=required||'unsupported_instrument'::text;END IF; END LOOP;")
    emit("IF r->>'kind'='BUY' THEN SELECT COALESCE(pg_catalog.jsonb_agg(value),'[]'::jsonb) INTO acquisitions FROM pg_catalog.jsonb_array_elements(r->'legs') WHERE value->>'role'='ACQUISITION'; SELECT COALESCE(pg_catalog.jsonb_agg(value),'[]'::jsonb) INTO payments FROM pg_catalog.jsonb_array_elements(r->'legs') WHERE value->>'role'='PAYMENT';")
    check("acquisitions<>'[]'::jsonb AND NOT EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(acquisitions) t(v) WHERE (v->>'quantity')::numeric<=0 OR payload->'assets'->((v->>'asset_local_id')::integer)->>'kind' NOT IN ('CRYPTO','SECURITY') OR payload->'accounts'->((v->>'account_local_id')::integer)->>'role'='funding')")
    check("NOT EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(payments) t(v) WHERE (v->>'quantity')::numeric>=0)")
    check("payload->'provenance'->'parser_api'<>'2'::jsonb OR (pg_catalog.jsonb_array_length(acquisitions)=1 AND payments<>'[]'::jsonb AND pg_catalog.jsonb_array_length(acquisitions)+pg_catalog.jsonb_array_length(payments)=pg_catalog.jsonb_array_length(r->'legs'))", 'import_evidence_unsupported')
    emit('END IF;')
    emit("FOR item IN SELECT value FROM pg_catalog.jsonb_array_elements(CASE WHEN r->'fees'='null'::jsonb THEN '[]'::jsonb ELSE r->'fees' END) LOOP")
    check(_minimal_ref_sql('accounts', "item->>'account_local_id'"))
    amount('item')
    check("(item->>'quantity')::numeric>=0")
    emit("IF payload->'assets'->((item->>'asset_local_id')::integer)->>'kind'='UNSUPPORTED' THEN required:=required||'unsupported_instrument'::text;END IF;END LOOP;")
    check("r->'support'->'reasons' ?& required")
    check("r->'identity'->>'change'<>'void' OR r->>'status'='cancelled'")
    check("CASE WHEN r->>'source_status' IN ('completed','pending','cancelled') THEN r->'status'=r->'source_status' ELSE r->>'status'='unsupported' END")
    check("r->'lifecycle_reference'='null'::jsonb OR r->'lifecycle'<>'null'::jsonb", 'import_evidence_unsupported')
    emit("life:=r->'lifecycle';IF life<>'null'::jsonb THEN")
    amount("life->'payin'")
    amount("life->'payout'")
    emit("FOREACH field IN ARRAY ARRAY['completed_at','sent_at'] LOOP IF life->field<>'null'::jsonb THEN")
    emit('comparison:=' + _minimal_order_sql('life->field', "life->'created_at'") + ';')
    check('comparison IS NOT NULL', 'import_conflict')
    check('comparison>=0')
    emit('END IF;END LOOP;')
    check("(life->'payin'->>'quantity')::numeric>=0 AND (life->'payout'->>'quantity')::numeric>=0")
    emit("IF r->>'status'='completed' THEN")
    check("life->'completed_at'<>'null'::jsonb AND " + _minimal_order_sql("r->'event_time'", "life->'completed_at'") + '=0')
    emit('END IF;')
    emit("IF r->>'kind'='BUY' AND payload->'provenance'->'parser_api'='2'::jsonb AND r->'support'->>'classification'='supported_shape' THEN")
    check("pg_catalog.jsonb_array_length(acquisitions)=1 AND pg_catalog.jsonb_array_length(payments)=1 AND pg_catalog.jsonb_array_length(r->'legs')=2", 'import_evidence_unsupported')
    check("acquisitions->0->'asset_local_id'=life->'payout'->'asset_local_id' AND payments->0->'asset_local_id'=life->'payin'->'asset_local_id' AND (acquisitions->0->>'quantity')::numeric=(life->'payout'->>'quantity')::numeric AND pg_catalog.abs((payments->0->>'quantity')::numeric)=(life->'payin'->>'quantity')::numeric")
    emit('END IF;END IF;')
    check("r->'acquisition_cost_cad'='null'::jsonb OR r->'acquisition_cost_cad'->>'currency'='CAD'")
    emit('END LOOP;')
    emit("FOR s IN SELECT value FROM pg_catalog.jsonb_array_elements(payload->'snapshots') LOOP")
    for field, table in [('account_local_ids', 'accounts'), ('coverage_local_ids', 'coverage'), ('position_local_ids', 'records')]:
        check(_minimal_unique_sql("s->'" + field + "'"))
        emit("FOR id IN SELECT value FROM pg_catalog.jsonb_array_elements_text(s->'" + field + "') LOOP")
        check(_minimal_ref_sql(table, 'id'))
        emit('END LOOP;')
    check("s->'account_local_ids'<>'[]'::jsonb")
    emit("FOR id IN SELECT value FROM pg_catalog.jsonb_array_elements_text(s->'coverage_local_ids') LOOP c:=payload->'coverage'->(id::integer);")
    check("c->>'kind'='holdings' AND s->'account_local_ids' ? (c->>'account_local_id') AND c->'observation_id'=s->'source_id'")
    check(_minimal_contains_sql("c->'time'", "s->'as_of'"))
    emit('END LOOP;')
    check("NOT EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements_text(s->'account_local_ids') t(id) WHERE NOT EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(payload->'coverage') q(value) WHERE s->'coverage_local_ids' ? (q.value->>'local_id') AND q.value->>'account_local_id'=t.id))")
    emit("FOR id IN SELECT value FROM pg_catalog.jsonb_array_elements_text(s->'position_local_ids') LOOP r:=payload->'records'->(id::integer);")
    check("r->>'record_type'='position' AND s->'account_local_ids' ? (r->>'source_account_local_id') AND r->'identity'->'observation_id'=s->'source_id' AND r->'identity'->'revision'=s->'revision'")
    check(_minimal_order_sql("r->'as_of'", "s->'as_of'") + '=0')
    check(_minimal_covered_sql("r->'as_of'", "r->>'asset_local_id'", selected=True))
    emit('seen:=pg_catalog.array_append(seen,id);END LOOP;END LOOP;')
    check("(SELECT count(*)=count(DISTINCT value) FROM pg_catalog.unnest(seen) t(value)) AND pg_catalog.cardinality(seen)=(SELECT count(*) FROM pg_catalog.jsonb_array_elements(payload->'records') t(value) WHERE t.value->>'record_type'='position')")
    emit("FOR item IN SELECT value FROM pg_catalog.jsonb_array_elements(payload->'provenance'->'diagnostics') LOOP FOR id IN SELECT value FROM pg_catalog.jsonb_array_elements_text(item->'record_local_ids') LOOP")
    check(_minimal_ref_sql('records', 'id'))
    emit('END LOOP;')
    check(_minimal_unique_sql("item->'record_local_ids'"))
    emit('END LOOP;')
    emit('RETURN payload;')
    return '\n'.join(statements)

def minimal_validator_ddl():
    """Render the declared local-evidence validator; installation stays explicit.

    This helper does not establish selected-profile, session, lease or accepted
    reference authority. New admission/preparation must enforce those live guards.
    """
    header = "\nCREATE FUNCTION wl_ingestion._validate_minimal_v1(p_bytes bytea) RETURNS jsonb\nLANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $minimal$\nDECLARE payload jsonb; shape_status integer; comparison integer; cursor integer;\n depth integer:=0; quoted boolean:=false; escaped boolean:=false; current_byte integer;\n name text; field text; id text; a jsonb; c jsonb; r jsonb; item jsonb; s jsonb;\n link jsonb; life jsonb; at_value jsonb; required text[]; seen text[]:=ARRAY[]::text[];\n acquisitions jsonb; payments jsonb; has_array_limit boolean; has_object_limit boolean;\nBEGIN\n IF p_bytes IS NULL OR pg_catalog.octet_length(p_bytes)=0 OR\n  pg_catalog.octet_length(p_bytes)>4194304 THEN\n  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_limit';\n END IF;\n -- Bound nesting before JSONB allocates a tree, including strings with escapes.\n FOR cursor IN 0..pg_catalog.octet_length(p_bytes)-1 LOOP\n  current_byte:=pg_catalog.get_byte(p_bytes,cursor);\n  IF quoted THEN\n   IF escaped THEN escaped:=false;\n   ELSIF current_byte=92 THEN escaped:=true;\n   ELSIF current_byte=34 THEN quoted:=false; END IF;\n  ELSIF current_byte=34 THEN quoted:=true;\n  ELSIF current_byte IN (91,123) THEN\n   depth:=depth+1;\n   IF depth>32 THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_limit'; END IF;\n  ELSIF current_byte IN (93,125) THEN depth:=depth-1; END IF;\n END LOOP;\n payload:=pg_catalog.convert_from(p_bytes,'UTF8')::jsonb;\n WITH RECURSIVE nodes(value) AS (\n  SELECT payload UNION ALL\n  SELECT child.value FROM nodes CROSS JOIN LATERAL (\n   SELECT value FROM pg_catalog.jsonb_each(CASE WHEN pg_catalog.jsonb_typeof(nodes.value)='object' THEN nodes.value ELSE '{}'::jsonb END)\n   UNION ALL\n   SELECT value FROM pg_catalog.jsonb_array_elements(CASE WHEN pg_catalog.jsonb_typeof(nodes.value)='array' THEN nodes.value ELSE '[]'::jsonb END)\n  ) child\n ) SELECT pg_catalog.bool_or(CASE WHEN pg_catalog.jsonb_typeof(value)='array'\n   THEN pg_catalog.jsonb_array_length(value)>131072 ELSE false END),\n  pg_catalog.bool_or(CASE WHEN pg_catalog.jsonb_typeof(value)='object'\n   THEN (SELECT count(*) FROM pg_catalog.jsonb_object_keys(value))>131072 ELSE false END)\n INTO has_array_limit,has_object_limit FROM nodes;\n IF has_array_limit THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_limit'; END IF;\n IF has_object_limit THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid'; END IF;\n IF p_bytes<>wl_ingestion._canonical_v1(payload) THEN\n  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';\n END IF;\n"
    checked = 'shape_status:=' + _MinimalErrorPredicate().status() + ';\n'
    checked += "IF shape_status<>0 THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE=CASE WHEN shape_status=2 THEN 'import_limit' ELSE 'import_invalid' END; END IF;\n"
    footer = "\nEXCEPTION WHEN SQLSTATE '22023' THEN\n IF SQLERRM IN ('import_invalid','import_limit','import_conflict','import_evidence_unsupported') THEN RAISE; END IF;\n RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';\nWHEN data_exception THEN\n RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';\nWHEN OTHERS THEN\n RAISE EXCEPTION USING ERRCODE='XX000',MESSAGE='internal_error';\nEND $minimal$;\nREVOKE ALL ON FUNCTION wl_ingestion._validate_minimal_v1(bytea) FROM PUBLIC;\n"
    return header + checked + _minimal_graph_sql() + footer


def _checked_bytes_sql(maximum):
    """Shared byte boundary for declared checked SQL entry points."""
    return r"""
 IF p_bytes IS NULL OR pg_catalog.octet_length(p_bytes)=0 OR
  pg_catalog.octet_length(p_bytes)>MAXIMUM THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_limit';
 END IF;
 FOR cursor IN 0..pg_catalog.octet_length(p_bytes)-1 LOOP
  current_byte:=pg_catalog.get_byte(p_bytes,cursor);
  IF quoted THEN
   IF escaped THEN escaped:=false;
   ELSIF current_byte=92 THEN escaped:=true;
   ELSIF current_byte=34 THEN quoted:=false; END IF;
  ELSIF current_byte=34 THEN quoted:=true;
  ELSIF current_byte IN (91,123) THEN
   depth:=depth+1;
   IF depth>32 THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_limit'; END IF;
  ELSIF current_byte IN (93,125) THEN depth:=depth-1; END IF;
 END LOOP;
 payload:=pg_catalog.convert_from(p_bytes,'UTF8')::jsonb;
 IF EXISTS(WITH RECURSIVE nodes(value) AS (
  SELECT payload UNION ALL SELECT child.value FROM nodes CROSS JOIN LATERAL (
   SELECT value FROM pg_catalog.jsonb_each(CASE WHEN pg_catalog.jsonb_typeof(nodes.value)='object' THEN nodes.value ELSE '{}'::jsonb END)
   UNION ALL SELECT value FROM pg_catalog.jsonb_array_elements(CASE WHEN pg_catalog.jsonb_typeof(nodes.value)='array' THEN nodes.value ELSE '[]'::jsonb END)
  ) child
 ) SELECT 1 FROM nodes WHERE CASE WHEN pg_catalog.jsonb_typeof(value)='array' THEN pg_catalog.jsonb_array_length(value)>131072 ELSE false END) THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_limit'; END IF;
 IF p_bytes<>wl_ingestion._canonical_v1(payload) THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
 END IF;
""".replace('MAXIMUM', str(maximum))


def _plan_material_sql():
    """Render the exact material preimages; never use a submitted digest as proof.

    Mirrors reconciliation.financial_projection with literal cross-language
    vectors. Only declared local reference keys and lineage locations change.
    """
    return r"""
 materials:='{}'::jsonb; source_keys:='{}'::jsonb;
 FOR collection IN SELECT unnest(ARRAY['records','coverage','snapshots','membership']) LOOP
  FOR source IN SELECT value FROM pg_catalog.jsonb_array_elements(CASE WHEN collection='membership'
   THEN CASE WHEN evidence->'membership'='null'::jsonb THEN '[]'::jsonb
    ELSE pg_catalog.jsonb_build_array(evidence->'membership') END ELSE evidence->collection END) LOOP
   local_id:=CASE WHEN collection='membership' THEN '0' ELSE source->>'local_id' END;
   source_key:=pg_catalog.jsonb_build_object('version',1,'tenant_id',p_tenant::text,
    'portfolio_id',p_portfolio::text,'connection_id',pin->>'connection_id','collection',collection,
    'provider',evidence->'provenance'->>'provider_id','source_account_key',null,
    'kind',CASE collection WHEN 'records' THEN source->>'source_kind'
     WHEN 'coverage' THEN 'coverage' WHEN 'snapshots' THEN 'snapshot' ELSE 'membership' END,
    'record_kind',CASE WHEN collection='coverage' THEN source->>'kind' ELSE null END,
    'source_id',CASE collection WHEN 'records' THEN source->'identity'->>'source_id'
     WHEN 'snapshots' THEN source->>'source_id' ELSE source->>'scope_id' END,
    'observation_id',CASE collection WHEN 'records' THEN source->'identity'->>'observation_id'
     WHEN 'coverage' THEN source->>'observation_id' ELSE '' END);
   IF collection IN ('records','coverage') THEN
    source_key:=source_key||pg_catalog.jsonb_build_object('source_account_key',
     evidence->'accounts'->((CASE WHEN collection='records' THEN source->>'source_account_local_id'
      ELSE source->>'account_local_id' END)::integer)->'source_account_key');
   END IF;
   source_keys:=pg_catalog.jsonb_set(source_keys,ARRAY[collection||':'||local_id],source_key);
   IF collection='records' THEN
    material:=source-ARRAY['local_id','lifecycle_reference'];
    material:=pg_catalog.jsonb_set(material,ARRAY['identity'],
     pg_catalog.jsonb_build_object('source_id',source->'identity'->'source_id','observation_id',source->'identity'->'observation_id'));
    -- Walk the closed record once; local source references are kind-specific.
    FOR edit IN WITH RECURSIVE nodes(value,path) AS (
     SELECT material,ARRAY[]::text[] UNION ALL
     SELECT child.value,nodes.path||child.key FROM nodes CROSS JOIN LATERAL (
      SELECT o.key,o.value FROM pg_catalog.jsonb_each(CASE WHEN pg_catalog.jsonb_typeof(nodes.value)='object'
       THEN nodes.value ELSE '{}'::jsonb END) o
      UNION ALL SELECT (ordinal-1)::text,value FROM pg_catalog.jsonb_array_elements(
       CASE WHEN pg_catalog.jsonb_typeof(nodes.value)='array' THEN nodes.value ELSE '[]'::jsonb END)
       WITH ORDINALITY a(value,ordinal)
     ) child
    ) SELECT nodes.value,nodes.path FROM nodes WHERE nodes.path[pg_catalog.cardinality(nodes.path)] IN
     ('account_local_id','source_account_local_id','asset_local_id') LOOP
     field:=edit.path[pg_catalog.cardinality(edit.path)];
     kind:=CASE WHEN field='asset_local_id' THEN 'instrument' ELSE 'account' END;
     ref:=CASE WHEN edit.value='null'::jsonb THEN 'null'::jsonb
      ELSE refs->(kind||':'||(edit.value#>>'{}')) END;
     IF ref IS NULL THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_mapping_required'; END IF;
     path:=edit.path[1:pg_catalog.cardinality(edit.path)-1];
     replacement:=(material#>path)-field||pg_catalog.jsonb_build_object(
      CASE field WHEN 'asset_local_id' THEN 'instrument' WHEN 'source_account_local_id'
       THEN 'source_account' ELSE 'account' END,ref);
     IF pg_catalog.cardinality(path)=0 THEN material:=replacement;
     ELSE material:=pg_catalog.jsonb_set(material,path,replacement); END IF;
    END LOOP;
    field:=CASE WHEN source->>'record_type'='position' THEN 'as_of' ELSE 'event_time' END;
    IF material->field->>'tag'='legacy_unspecified' THEN
     material:=pg_catalog.jsonb_set(material,ARRAY[field],(material->field)-'legacy');
    END IF;
    IF material->'lifecycle'<>'null'::jsonb THEN
     FOREACH field IN ARRAY ARRAY['created_at','completed_at','sent_at'] LOOP
      IF material->'lifecycle'->field->>'tag'='legacy_unspecified' THEN
       material:=pg_catalog.jsonb_set(material,ARRAY['lifecycle',field],
        (material->'lifecycle'->field)-'legacy');
      END IF;
     END LOOP;
    END IF;
   ELSIF collection='coverage' THEN
    selector:=source->'time';
    FOREACH field IN ARRAY ARRAY['at','start','end'] LOOP
     IF selector->field->>'tag'='legacy_unspecified' THEN
      selector:=pg_catalog.jsonb_set(selector,ARRAY[field],(selector->field)-'legacy');
     END IF;
    END LOOP;
    SELECT COALESCE(pg_catalog.jsonb_agg(refs->('instrument:'||(value#>>'{}'))
     ORDER BY wl_ingestion._canonical_v1(refs->('instrument:'||(value#>>'{}')))),'[]'::jsonb)
     INTO children FROM pg_catalog.jsonb_array_elements(source->'instrument_scope'->'asset_local_ids');
    material:=source-ARRAY['local_id','revision','account_local_id','time','instrument_scope','legacy','parent']||
     pg_catalog.jsonb_build_object('account',refs->('account:'||(source->>'account_local_id')),
      'time',selector,'instrument_scope',(source->'instrument_scope')-'asset_local_ids'||
       pg_catalog.jsonb_build_object('instruments',children));
   ELSIF collection='membership' THEN
    SELECT COALESCE(pg_catalog.jsonb_agg(refs->('account:'||(value#>>'{}'))
     ORDER BY wl_ingestion._canonical_v1(refs->('account:'||(value#>>'{}')))),'[]'::jsonb)
     INTO children FROM pg_catalog.jsonb_array_elements(source->'account_local_ids');
    material:=source-ARRAY['revision','account_local_ids','parent']||pg_catalog.jsonb_build_object('accounts',children);
   ELSE
    SELECT COALESCE(pg_catalog.jsonb_agg(refs->('account:'||(value#>>'{}'))
     ORDER BY wl_ingestion._canonical_v1(refs->('account:'||(value#>>'{}')))),'[]'::jsonb)
     INTO children FROM pg_catalog.jsonb_array_elements(source->'account_local_ids');
    material:=pg_catalog.jsonb_build_object('source_id',source->'source_id','as_of',
     CASE WHEN source->'as_of'->>'tag'='legacy_unspecified' THEN (source->'as_of')-'legacy'
      ELSE source->'as_of' END,'accounts',children);
    FOREACH field IN ARRAY ARRAY['coverage','positions'] LOOP
     name:=CASE WHEN field='positions' THEN 'records' ELSE 'coverage' END;
     SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
      'source_key',source_keys->(name||':'||(value#>>'{}')),
      'financial_digest',pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(
       materials->(name||':'||(value#>>'{}')))),'hex'))
      ORDER BY wl_ingestion._canonical_v1(source_keys->(name||':'||(value#>>'{}')))),'[]'::jsonb)
      INTO children FROM pg_catalog.jsonb_array_elements(source->CASE WHEN field='positions'
       THEN 'position_local_ids' ELSE 'coverage_local_ids' END);
     material:=material||pg_catalog.jsonb_build_object(field,children);
    END LOOP;
   END IF;
   materials:=pg_catalog.jsonb_set(materials,ARRAY[collection||':'||local_id],material);
  END LOOP;
 END LOOP;
"""


def _plan_local_relations_sql():
    """Check Plan-local edges without claiming current accepted-chain authority."""
    return r"""
 seen:=ARRAY[]::text[];
 FOR effect IN SELECT value FROM pg_catalog.jsonb_array_elements(payload->'facts') LOOP
  key:=(effect->>'member_id')||':'||(effect->>'collection')||':'||(effect->>'local_id');
  IF effect->>'action'<>'duplicate' THEN
   IF (effect->>'accepted_revision_id')=ANY(seen) THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
   seen:=seen||(effect->>'accepted_revision_id');
  END IF;
  evidence:=staged->(effect->>'member_id');
  source:=CASE WHEN effect->>'collection'='membership' THEN evidence->'membership'
   ELSE evidence->(effect->>'collection')->((effect->>'local_id')::integer) END;
  IF ((source->>'record_type'='activity') IS TRUE)<>(effect->'economic_group_id'<>'null'::jsonb) OR
   effect->'accepted_revision_id'=effect->'parent_revision_id' THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  SELECT value INTO proposal FROM pg_catalog.jsonb_array_elements(payload->'parents') WHERE
   value->'member_id'=effect->'member_id' AND value->'collection'=effect->'collection' AND value->'local_id'=effect->'local_id';
  IF effect->>'action' IN ('correction','void') THEN
   IF effect->'parent_revision_id'='null'::jsonb OR
    ((effect->>'action'='void') IS DISTINCT FROM (COALESCE(source->'identity'->>'change','original')='void')) OR
    (proposal IS NULL AND COALESCE(source->'identity'->'parent',source->'parent','null'::jsonb)='null'::jsonb) THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  ELSIF effect->>'action'='append' AND (effect->'parent_revision_id'<>'null'::jsonb OR
   COALESCE(source->'identity'->'parent',source->'parent','null'::jsonb)<>'null'::jsonb) THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict';
  END IF;
  IF proposal IS NOT NULL AND (proposal->'parent_revision_id'<>effect->'parent_revision_id' OR
   effect->>'action' NOT IN ('correction','void') OR proposal->>'reason'='') THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
 END LOOP;
 seen:=ARRAY[]::text[];
 FOR proposal IN SELECT value FROM pg_catalog.jsonb_array_elements(payload->'parents') LOOP
  key:=(proposal->>'member_id')||':'||(proposal->>'collection')||':'||(proposal->>'local_id');
  IF key=ANY(seen) OR NOT key=ANY(all_facts) THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid'; END IF;
  seen:=seen||key;
 END LOOP;
 seen:=ARRAY[]::text[];
 FOR proposal IN SELECT value FROM pg_catalog.jsonb_array_elements(payload->'authorities') LOOP
  IF (proposal->>'kind'='historical_only')<>(proposal->'right'='null'::jsonb) OR
   proposal->'left'=proposal->'right' OR proposal->>'evidence_reference'='' THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  key:=pg_catalog.encode(wl_ingestion._canonical_v1(proposal),'hex');
  IF key=ANY(seen) THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid'; END IF;
  seen:=seen||key;
  FOREACH field IN ARRAY ARRAY['left','right'] LOOP
   ref:=proposal->field;
   IF ref<>'null'::jsonb AND ref->>'form'='incoming' THEN
    key:=(ref->>'member_id')||':'||(ref->>'collection')||':'||(ref->>'local_id');
    IF NOT key=ANY(all_facts) THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid'; END IF;
   END IF;
  END LOOP;
 END LOOP;
 seen:=ARRAY[]::text[];
 FOR proposal IN SELECT value FROM pg_catalog.jsonb_array_elements(payload->'heads') LOOP
  key:=(proposal->>'kind')||':'||(proposal->>'key_digest');
  IF key=ANY(seen) OR proposal->'next_revision_id'=proposal->'prior_revision_id' THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  seen:=seen||key;
  SELECT value INTO effect FROM pg_catalog.jsonb_array_elements(payload->'facts') WHERE
   value->'accepted_revision_id'=proposal->'next_revision_id' AND value->>'action'<>'duplicate';
  IF effect IS NULL OR effect->>'action' IN ('historical','mirror') THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  evidence:=staged->(effect->>'member_id');
  source:=CASE WHEN effect->>'collection'='membership' THEN evidence->'membership'
   ELSE evidence->(effect->>'collection')->((effect->>'local_id')::integer) END;
  IF proposal->>'kind'='activity' THEN
   IF source->>'record_type' IS DISTINCT FROM 'activity' OR proposal->'complete_base_id'<>'null'::jsonb OR
    (proposal->>'active')::boolean<>(effect->>'action'<>'void') OR
    proposal->>'key_digest'<>pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(
     pg_catalog.jsonb_build_object('version',1,'tenant_id',p_tenant::text,'portfolio_id',p_portfolio::text,
      'economic_group_id',effect->'economic_group_id'))),'hex') THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  ELSE
   IF effect->>'collection'<>'snapshots' OR proposal->>'active'<>'true' THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
   -- A snapshot can update only its explicitly covered canonical domain.
   expected:=ARRAY[]::text[];
   FOR selector IN SELECT evidence->'coverage'->((value#>>'{}')::integer)
    FROM pg_catalog.jsonb_array_elements(source->'coverage_local_ids') LOOP
    IF selector->>'kind'<>'holdings' THEN CONTINUE; END IF;
    SELECT value->'target'->>'id' INTO name FROM pg_catalog.jsonb_array_elements(payload->'mappings')
     WHERE value->'member_id'=effect->'member_id' AND value->>'entity_kind'='account' AND value->'local_id'=selector->'account_local_id';
    SELECT COALESCE(pg_catalog.jsonb_agg(m.value->'target'->'id' ORDER BY m.value->'target'->>'id' COLLATE "C"),'[]'::jsonb)
     INTO children FROM pg_catalog.jsonb_array_elements(payload->'mappings') m(value)
     WHERE m.value->'member_id'=effect->'member_id' AND m.value->>'entity_kind'='instrument'
      AND selector->'instrument_scope'->'asset_local_ids' ? (m.value->>'local_id');
    replacement:=pg_catalog.jsonb_build_object('version',1,'tenant_id',p_tenant::text,'portfolio_id',p_portfolio::text,
     'account_id',name,'record_kind','holdings','instrument_scope',
     (selector->'instrument_scope')-'asset_local_ids'||pg_catalog.jsonb_build_object('instrument_ids',children));
    key:=pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(replacement)),'hex');
    expected:=expected||key;
    IF key=proposal->>'key_digest' AND ((selector->>'status'='complete')<>(proposal->'complete_base_id'=proposal->'next_revision_id')) THEN
     RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
   END LOOP;
   IF NOT (proposal->>'key_digest')=ANY(expected) THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  END IF;
 END LOOP;
"""


# Exact proposed entity body from stored evidence, shared by Plan validation
# and acceptance so both check and insert the same canonical body.
_ENTITY_BODY_SQL = r"""
   identity:=pg_catalog.jsonb_build_object('tenant_id',p_tenant::text,'portfolio_id',p_portfolio::text,'kind',kind,'value',target->>'id');
   issuer:='null'::jsonb;
   IF kind='instrument' AND source->'issuer_local_id'<>'null'::jsonb THEN
    issuer:=pg_catalog.jsonb_build_object('tenant_id',p_tenant::text,'portfolio_id',p_portfolio::text,
     'kind','issuer','value',refs->('issuer:'||(source->>'issuer_local_id'))->>'id');
   END IF;
   IF kind='account' THEN body:=pg_catalog.jsonb_build_object('id',identity,'category',source->'category','role',source->'role','label',source->'label');
   ELSIF kind='issuer' THEN body:=pg_catalog.jsonb_build_object('id',identity,'label',source->'label');
   ELSE
    body:=source-ARRAY['local_id','identifier','issuer_local_id'];
    IF source->>'kind' IN ('CASH','SECURITY') THEN body:=body||pg_catalog.jsonb_build_object('symbol',null); END IF;
    IF source->>'kind'='CRYPTO' AND source->'settlement_identity'='null'::jsonb THEN
     body:=body||pg_catalog.jsonb_build_object('settlement_identity',source->'network'); END IF;
    body:=body||pg_catalog.jsonb_build_object('id',identity,'issuer',issuer,'evidence_reference',evidence->'provenance'->'evidence_reference');
    IF source->'identifier'<>'null'::jsonb AND NOT EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(body->'identifiers') WHERE value->'value'=source->'identifier') THEN
     RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_evidence_unsupported';
    END IF;
   END IF;
""".lstrip('\n')


def plan_validator_ddl():
    """Render Plan checks against stored stages, member pins and entity bodies.

    Call only under the operation's authenticated locks. This read-only helper
    does not authorize a session/lease, change a head or perform acceptance.
    """
    from ..ingestion.contracts import definition
    header = r"""
CREATE FUNCTION wl_ingestion._validate_plan_v1(p_tenant uuid,p_portfolio uuid,p_set uuid,p_bytes bytea)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $plan$
DECLARE payload jsonb;shape_status integer;cursor integer;depth integer:=0;
 quoted boolean:=false;escaped boolean:=false;current_byte integer;
 selected wl_ingestion.sets%ROWTYPE;root wl_ingestion.roots%ROWTYPE;
 member wl_ingestion.members%ROWTYPE;stage wl_ingestion.stages%ROWTYPE;
 decision wl_ingestion.decisions%ROWTYPE;
 input jsonb;pin jsonb;evidence jsonb;mapping jsonb;target jsonb;source jsonb;body jsonb;
 identity jsonb;issuer jsonb;proposal jsonb;effect jsonb;ref jsonb;replacement jsonb;
 material jsonb;materials jsonb;source_key jsonb;source_keys jsonb;selector jsonb;children jsonb;
 refs jsonb;seen text[];declared text[]:=ARRAY[]::text[];expected text[];
 staged jsonb:='{}'::jsonb;proposed jsonb:='{}'::jsonb;entity_bodies jsonb:='{}'::jsonb;all_facts text[]:=ARRAY[]::text[];
 all_members text[];field text;kind text;name text;key text;local_id text;collection text;path text[];
 edit record;
BEGIN
"""
    checked = 'shape_status:=' + _MinimalErrorPredicate().status(schema=definition('Plan')) + ';\n'
    checked += "IF shape_status<>0 THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE=CASE WHEN shape_status=2 THEN 'import_limit' ELSE 'import_invalid' END; END IF;\n"
    body = r"""
 IF p_tenant IS NULL OR p_portfolio IS NULL OR p_set IS NULL OR
  payload->>'tenant_id' IS DISTINCT FROM p_tenant::text OR
  payload->>'portfolio_id' IS DISTINCT FROM p_portfolio::text OR
  payload->>'set_id' IS DISTINCT FROM p_set::text THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
 END IF;
 SELECT * INTO selected FROM wl_ingestion.sets WHERE tenant_id=p_tenant AND portfolio_id=p_portfolio AND id=p_set;
 SELECT * INTO root FROM wl_ingestion.roots WHERE tenant_id=p_tenant AND portfolio_id=p_portfolio;
 IF selected.id IS NULL OR root.tenant_id IS NULL OR
  NOT ((selected.state='READY' AND payload->>'expected_set_revision'=selected.revision::text) OR
   (selected.state='RECONCILING' AND selected.revision<9223372036854775807 AND
    (payload->>'expected_set_revision')::numeric=selected.revision::numeric+1)) OR
  payload->>'expected_accepted_generation' IS DISTINCT FROM root.accepted_generation::text OR
  payload->>'expected_mapping_generation' IS DISTINCT FROM root.mapping_generation::text OR
  payload->>'expected_control_generation' IS DISTINCT FROM root.control_generation::text OR
  payload->>'incarnation' IS DISTINCT FROM selected.incarnation::text OR
  payload->>'restore_epoch' IS DISTINCT FROM selected.restore_epoch::text OR
  payload->>'realm_digest' IS DISTINCT FROM selected.realm_digest OR
  (payload->'expires_at'->>'token')::timestamptz IS DISTINCT FROM selected.expires_at THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale';
 END IF;
 SELECT * INTO decision FROM wl_ingestion.decisions WHERE tenant_id=p_tenant AND portfolio_id=p_portfolio
  AND set_id=p_set ORDER BY revision DESC LIMIT 1;
 IF decision.set_id IS NULL OR payload->>'decision_digest' IS DISTINCT FROM decision.digest OR
  pg_catalog.encode(pg_catalog.sha256(decision.canonical_bytes),'hex')<>decision.digest OR
  decision.canonical_bytes<>wl_ingestion._canonical_v1(pg_catalog.convert_from(decision.canonical_bytes,'UTF8')::jsonb) THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale';
 END IF;
 -- The complete reviewed decision arrays, not browser-derived facts, bind a Plan.
 evidence:=pg_catalog.convert_from(decision.canonical_bytes,'UTF8')::jsonb;
 FOREACH name IN ARRAY ARRAY['mappings','new_entities','authorities','parents'] LOOP
  IF payload->name IS DISTINCT FROM evidence->name THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict';
  END IF;
 END LOOP;
 SELECT array_agg(id::text ORDER BY id::text COLLATE "C") INTO all_members FROM wl_ingestion.members
  WHERE tenant_id=p_tenant AND portfolio_id=p_portfolio AND set_id=p_set;
 IF COALESCE(pg_catalog.cardinality(all_members),0)<>selected.member_count OR
  pg_catalog.jsonb_array_length(payload->'inputs')<>selected.member_count OR
  pg_catalog.jsonb_array_length(payload->'pinned_sources')<>selected.member_count OR
  (SELECT count(DISTINCT value->>'member_id') FROM pg_catalog.jsonb_array_elements(payload->'inputs'))<>selected.member_count OR
  (SELECT count(DISTINCT value->>'member_id') FROM pg_catalog.jsonb_array_elements(payload->'pinned_sources'))<>selected.member_count THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
 END IF;
 FOR input IN SELECT value FROM pg_catalog.jsonb_array_elements(payload->'inputs') LOOP
  SELECT * INTO member FROM wl_ingestion.members WHERE tenant_id=p_tenant AND portfolio_id=p_portfolio
   AND set_id=p_set AND id=(input->>'member_id')::uuid;
  SELECT value INTO pin FROM pg_catalog.jsonb_array_elements(payload->'pinned_sources') WHERE value->>'member_id'=input->>'member_id';
  IF member.id IS NULL OR pin IS NULL THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid'; END IF;
  IF member.state<>'admitted' OR pin-'member_id' IS DISTINCT FROM pg_catalog.jsonb_build_object(
   'connection_id',member.connection_id::text,'connection_version',member.connection_version,
   'connection_generation',member.connection_generation::text,'enablement_generation',member.enablement_generation::text,
   'availability_generation',member.availability_generation::text,'installation_id',member.installation_id,
   'wrapper_profile_digest',member.wrapper_profile_digest,'format_version',member.format_version,
   'context_digest',member.context_digest) OR input->>'raw_digest' IS DISTINCT FROM member.raw_digest OR
   input->>'stage_digest' IS DISTINCT FROM member.stage_digest THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale';
  END IF;
  SELECT * INTO stage FROM wl_ingestion.stages WHERE tenant_id=p_tenant AND portfolio_id=p_portfolio
   AND set_id=p_set AND member_id=member.id AND digest=member.stage_digest;
  IF stage.member_id IS NULL OR stage.codec<>'minimal-evidence-v1' OR
   pg_catalog.encode(pg_catalog.sha256(stage.minimal_bytes),'hex') IS DISTINCT FROM stage.digest THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale';
  END IF;
  evidence:=wl_ingestion._validate_minimal_v1(stage.minimal_bytes);
  staged:=pg_catalog.jsonb_set(staged,ARRAY[member.id::text],evidence);
  IF evidence->'provenance'->>'raw_sha256' IS DISTINCT FROM input->>'raw_digest' OR
   evidence->'provenance'->>'discovery_sha256' IS DISTINCT FROM input->>'discovery_digest' OR
   evidence->'provenance'->>'installation_id' IS DISTINCT FROM pin->>'installation_id' OR
   evidence->'provenance'->>'wrapper_profile_digest' IS DISTINCT FROM pin->>'wrapper_profile_digest' OR
   evidence->'provenance'->>'format_selection' IS DISTINCT FROM pin->>'format_version' THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale';
  END IF;
  refs:='{}'::jsonb;seen:=ARRAY[]::text[];expected:=ARRAY[]::text[];
  FOREACH kind IN ARRAY ARRAY['account','instrument','issuer'] LOOP
   name:=CASE kind WHEN 'account' THEN 'accounts' WHEN 'instrument' THEN 'assets' ELSE 'issuers' END;
   FOR source IN SELECT value FROM pg_catalog.jsonb_array_elements(evidence->name) LOOP
    expected:=expected||(kind||':'||(source->>'local_id'));
   END LOOP;
  END LOOP;
  FOR mapping IN SELECT value FROM pg_catalog.jsonb_array_elements(payload->'mappings') WHERE value->>'member_id'=member.id::text LOOP
   key:=(mapping->>'entity_kind')||':'||(mapping->>'local_id');
   IF key=ANY(seen) OR NOT key=ANY(expected) THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid'; END IF;
   seen:=seen||key;
   refs:=pg_catalog.jsonb_set(refs,ARRAY[key],(mapping->'target')-'mode');
  END LOOP;
  IF NOT expected<@seen THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_mapping_required'; END IF;
  FOR mapping IN SELECT value FROM pg_catalog.jsonb_array_elements(payload->'mappings') WHERE value->>'member_id'=member.id::text LOOP
   kind:=mapping->>'entity_kind';local_id:=mapping->>'local_id';target:=mapping->'target';
   source:=evidence->CASE kind WHEN 'account' THEN 'accounts' WHEN 'instrument' THEN 'assets' ELSE 'issuers' END->(local_id::integer);
""" + _ENTITY_BODY_SQL + r"""   key:=kind||':'||(target->>'id');
   IF target->>'mode'='proposed' THEN
    IF pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(body)),'hex')<>target->>'version' OR
     (entity_bodies ? key AND entity_bodies->key<>body) THEN
     RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
    entity_bodies:=pg_catalog.jsonb_set(entity_bodies,ARRAY[key],body);
    proposed:=pg_catalog.jsonb_set(proposed,ARRAY[member.id::text||':'||kind||':'||local_id],target);
   ELSE
    replacement:=NULL;
    IF kind='account' THEN SELECT e.body INTO replacement FROM wl_pg.accounts e WHERE e.tenant_id=p_tenant AND e.portfolio_id=p_portfolio AND e.id=(target->>'id')::uuid AND e.version=target->>'version';
    ELSIF kind='issuer' THEN SELECT e.body INTO replacement FROM wl_pg.issuers e WHERE e.tenant_id=p_tenant AND e.portfolio_id=p_portfolio AND e.id=(target->>'id')::uuid AND e.version=target->>'version';
    ELSE SELECT e.body INTO replacement FROM wl_pg.instruments e WHERE e.tenant_id=p_tenant AND e.portfolio_id=p_portfolio AND e.id=(target->>'id')::uuid AND e.version=target->>'version'; END IF;
    IF replacement IS NULL OR pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(replacement)),'hex')<>target->>'version' OR replacement->'id'<>identity THEN
     RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale'; END IF;
    IF kind='account' THEN
     IF replacement->'category'<>source->'category' OR replacement->'role'<>source->'role' THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
    ELSIF kind='issuer' THEN
     IF replacement->'label'<>source->'label' THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
    ELSE
     FOREACH field IN ARRAY ARRAY['kind','currency','ticker','mic','symbol','network','settlement_identity','issuer'] LOOP
      IF replacement->field IS DISTINCT FROM body->field THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
     END LOOP;
     IF source->'identifier'<>'null'::jsonb THEN
      IF NOT EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(replacement->'identifiers') WHERE value->'value'=source->'identifier') THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
     ELSIF (SELECT pg_catalog.jsonb_agg(value ORDER BY value->>'scheme' COLLATE "C",value->>'value' COLLATE "C") FROM pg_catalog.jsonb_array_elements(source->'identifiers')) IS DISTINCT FROM
      (SELECT pg_catalog.jsonb_agg(value ORDER BY value->>'scheme' COLLATE "C",value->>'value' COLLATE "C") FROM pg_catalog.jsonb_array_elements(replacement->'identifiers')) THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
    END IF;
   END IF;
  END LOOP;
"""
    tail = r"""
  FOR key IN SELECT pg_catalog.jsonb_object_keys(materials) LOOP
   all_facts:=all_facts||(member.id::text||':'||key);
  END LOOP;
  seen:=ARRAY[]::text[];
  FOR effect IN SELECT value FROM pg_catalog.jsonb_array_elements(payload->'facts') WHERE value->>'member_id'=member.id::text LOOP
   key:=(effect->>'collection')||':'||(effect->>'local_id');
   IF key=ANY(seen) OR NOT materials ? key THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid'; END IF;
   seen:=seen||key;
   IF pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(materials->key)),'hex')<>effect->>'financial_digest' THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  END LOOP;
 END LOOP;
 IF pg_catalog.jsonb_array_length(payload->'facts')<>pg_catalog.cardinality(all_facts) OR
  EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(payload->'facts') WHERE NOT
   (value->>'member_id'||':'||(value->>'collection')||':'||(value->>'local_id'))=ANY(all_facts)) OR
  EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(payload->'mappings') WHERE NOT (value->>'member_id')=ANY(all_members)) THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid'; END IF;
 FOR proposal IN SELECT value FROM pg_catalog.jsonb_array_elements(payload->'new_entities') LOOP
  key:=(proposal->>'kind')||':'||(proposal->>'id');
  target:=proposed->(proposal->>'member_id'||':'||(proposal->>'kind')||':'||(proposal->>'local_id'));
  IF key=ANY(declared) OR target IS NULL OR target->>'id'<>proposal->>'id' OR target->>'version'<>proposal->>'version' THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid'; END IF;
  declared:=declared||key;
 END LOOP;
 IF pg_catalog.cardinality(declared)<>(SELECT count(*) FROM pg_catalog.jsonb_object_keys(entity_bodies)) THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid'; END IF;
 RETURN payload;
EXCEPTION WHEN SQLSTATE '22023' THEN
 IF SQLERRM IN ('import_invalid','import_limit','import_conflict','import_stale','import_mapping_required','import_evidence_unsupported') THEN RAISE; END IF;
 RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
WHEN data_exception THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
WHEN OTHERS THEN RAISE EXCEPTION USING ERRCODE='XX000',MESSAGE='internal_error';
END $plan$;
REVOKE ALL ON FUNCTION wl_ingestion._validate_plan_v1(uuid,uuid,uuid,bytea) FROM PUBLIC;
"""
    tail = tail.replace(' RETURN payload;', _plan_local_relations_sql() + '\n RETURN payload;')
    return header + _checked_bytes_sql(16777216) + checked + body + _plan_material_sql() + tail


def _stream_authority_sql():
    """Require an explicit choice for overlapping mapped activity streams."""
    sql = r"""
 FOR input IN SELECT i.value FROM pg_catalog.jsonb_each(incoming) i WHERE i.value->'typed'->>'record_type'='activity'
  AND i.value->>'change'<>'historical' AND NOT EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(payload->'facts') c(value)
   WHERE c.value->'parent_revision_id'=i.value->'accepted_revision_id' AND c.value->>'action'<>'duplicate') LOOP
  item:=input.value;
  FOR candidate IN SELECT i.value FROM pg_catalog.jsonb_each(incoming) i
   UNION ALL SELECT a.value FROM pg_catalog.jsonb_each(accepted_basis) a WHERE EXISTS(
    SELECT 1 FROM wl_ingestion.activity_heads h WHERE h.tenant_id=p_tenant AND h.portfolio_id=p_portfolio
     AND h.active AND h.revision_id::text=a.key) LOOP
   entry:=candidate.value;
   IF entry->'typed'->>'record_type' IS DISTINCT FROM 'activity' OR entry->>'change'='historical' OR
    item->'source'->'connection_id'=entry->'source'->'connection_id' OR
    item->'material'->'source_account'->'id' IS DISTINCT FROM entry->'material'->'source_account'->'id' OR
    item->'material'->'kind' IS DISTINCT FROM entry->'material'->'kind' THEN CONTINUE; END IF;
   stream_overlap:=false;
   FOR lhs_window IN SELECT w.value FROM pg_catalog.jsonb_array_elements(item->'windows') w(value)
    WHERE w.value->'account'->'id'=item->'material'->'source_account'->'id' AND w.value->'kind'=item->'source'->'kind' LOOP
    FOR rhs_window IN SELECT w.value FROM pg_catalog.jsonb_array_elements(entry->'windows') w(value)
     WHERE w.value->'account'->'id'=entry->'material'->'source_account'->'id' AND w.value->'kind'=entry->'source'->'kind' LOOP
     left_item:=lhs_window->'instrument_scope';right_item:=rhs_window->'instrument_scope';
     IF left_item->>'tag'='category' AND right_item->>'tag'='category' AND left_item->'category'<>right_item->'category' THEN CONTINUE; END IF;
     IF left_item->>'tag'='instruments' AND right_item->>'tag'='instruments' AND NOT EXISTS(
      SELECT 1 FROM pg_catalog.jsonb_array_elements(left_item->'instruments') l(value)
       JOIN pg_catalog.jsonb_array_elements(right_item->'instruments') r(value) ON l.value->'id'=r.value->'id') THEN CONTINUE; END IF;
     lhs_start:=CASE WHEN lhs_window->'time'->>'tag'='point' THEN lhs_window->'time'->'at' ELSE lhs_window->'time'->'start' END;
     lhs_end:=CASE WHEN lhs_window->'time'->>'tag'='point' THEN lhs_window->'time'->'at' ELSE lhs_window->'time'->'end' END;
     rhs_start:=CASE WHEN rhs_window->'time'->>'tag'='point' THEN rhs_window->'time'->'at' ELSE rhs_window->'time'->'start' END;
     rhs_end:=CASE WHEN rhs_window->'time'->>'tag'='point' THEN rhs_window->'time'->'at' ELSE rhs_window->'time'->'end' END;
     order_value:=LEFT_END_RIGHT_START;
     IF order_value<0 OR (order_value=0 AND NOT (
      COALESCE((lhs_window->'time'->>'end_inclusive')::boolean,true) AND
      COALESCE((rhs_window->'time'->>'start_inclusive')::boolean,true))) THEN CONTINUE; END IF;
     order_value:=RIGHT_END_LEFT_START;
     IF order_value<0 OR (order_value=0 AND NOT (
      COALESCE((rhs_window->'time'->>'end_inclusive')::boolean,true) AND
      COALESCE((lhs_window->'time'->>'start_inclusive')::boolean,true))) THEN CONTINUE; END IF;
     -- Unknown comparison cannot prove disjoint streams.
     stream_overlap:=true;EXIT;
    END LOOP;
    EXIT WHEN stream_overlap;
   END LOOP;
   IF stream_overlap AND NOT EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(authority_edges) a(value) WHERE
    ((a.value->'left'=item->'accepted_revision_id' AND a.value->'right'=entry->'accepted_revision_id') OR
     (a.value->'right'=item->'accepted_revision_id' AND a.value->'left'=entry->'accepted_revision_id'))
     AND a.value->>'kind' IN ('mirror','independent','authority')) AND NOT EXISTS(
    SELECT 1 FROM (SELECT DISTINCT ON(a.id) a.* FROM wl_ingestion.authority_links a
     WHERE a.tenant_id=p_tenant AND a.portfolio_id=p_portfolio ORDER BY a.id,a.revision DESC) latest
    WHERE latest.decision_kind IN ('mirror','independent','authority') AND
     ((latest.left_revision_id::text=item->>'accepted_revision_id' AND latest.right_revision_id::text=entry->>'accepted_revision_id') OR
      (latest.right_revision_id::text=item->>'accepted_revision_id' AND latest.left_revision_id::text=entry->>'accepted_revision_id')) AND NOT EXISTS(
      SELECT 1 FROM pg_catalog.jsonb_array_elements(authority_edges) n(value) WHERE
       LEAST(n.value->>'left',n.value->>'right')=LEAST(latest.left_revision_id::text,latest.right_revision_id::text) AND
       GREATEST(n.value->>'left',n.value->>'right')=GREATEST(latest.left_revision_id::text,latest.right_revision_id::text))) THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  END LOOP;
 END LOOP;
"""
    return sql.replace('LEFT_END_RIGHT_START', _minimal_order_sql('lhs_end', 'rhs_start')).replace(
        'RIGHT_END_LEFT_START', _minimal_order_sql('rhs_end', 'lhs_start'))


def reference_validator_ddl():
    """Render scoped reference checks for a stored preview under caller locks.

    The operator must install the whole checked profile before granting access.
    This helper grants no session, source, lease or mutation authority.
    """
    header = r"""
CREATE FUNCTION wl_ingestion._references_v1(p_tenant uuid,p_portfolio uuid,p_preview uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $references$
DECLARE preview wl_ingestion.previews%ROWTYPE;accepted wl_ingestion.source_revisions%ROWTYPE;
 old_input wl_ingestion.accepted_inputs%ROWTYPE;old_plan wl_ingestion.accepted_plans%ROWTYPE;
 payload jsonb;evidence jsonb;pin jsonb;refs jsonb;mapping jsonb;target jsonb;
 material jsonb;materials jsonb;source_key jsonb;source_keys jsonb;source jsonb;
 selector jsonb;children jsonb;ref jsonb;replacement jsonb;effect jsonb;proposal jsonb;
 old_payload jsonb;old_effect jsonb;item jsonb;entry jsonb;parent jsonb;claim jsonb;
 authority_edges jsonb:='[]'::jsonb;left_id text;right_id text;left_item jsonb;right_item jsonb;claims jsonb:='[]'::jsonb;incoming jsonb:='{}'::jsonb;accepted_basis jsonb:='{}'::jsonb;identities jsonb:='{}'::jsonb;
 expected_prior_id uuid;wanted_id uuid;needed uuid[];scope_keys text[]:=ARRAY[]::text[];
 key text;local_id text;collection text;kind text;name text;field text;path text[];
 candidate record;stream_overlap boolean;lhs_window jsonb;rhs_window jsonb;lhs_start jsonb;lhs_end jsonb;rhs_start jsonb;rhs_end jsonb;
 edit record;input record;prior_id uuid;complete_id uuid;active boolean;order_value integer;
BEGIN
 SELECT * INTO preview FROM wl_ingestion.previews WHERE tenant_id=p_tenant AND portfolio_id=p_portfolio AND id=p_preview;
 IF preview.id IS NULL OR preview.plan_bytes IS NULL OR
  pg_catalog.encode(pg_catalog.sha256(preview.plan_bytes),'hex') IS DISTINCT FROM preview.plan_digest THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale'; END IF;
 payload:=wl_ingestion._validate_plan_v1(p_tenant,p_portfolio,preview.set_id,preview.plan_bytes);
 IF payload->>'preview_id'<>preview.id::text THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale'; END IF;
 FOR input IN SELECT s.member_id,s.minimal_bytes FROM wl_ingestion.stages s
  JOIN pg_catalog.jsonb_array_elements(payload->'inputs') i(value)
   ON s.member_id=(i.value->>'member_id')::uuid AND s.digest=i.value->>'stage_digest'
  WHERE s.tenant_id=p_tenant AND s.portfolio_id=p_portfolio AND s.set_id=preview.set_id LOOP
  evidence:=wl_ingestion._validate_minimal_v1(input.minimal_bytes);
  SELECT value INTO pin FROM pg_catalog.jsonb_array_elements(payload->'pinned_sources') WHERE value->>'member_id'=input.member_id::text;
  SELECT COALESCE(pg_catalog.jsonb_object_agg((value->>'entity_kind')||':'||(value->>'local_id'),(value->'target')-'mode'),'{}'::jsonb)
   INTO refs FROM pg_catalog.jsonb_array_elements(payload->'mappings') WHERE value->>'member_id'=input.member_id::text;
"""
    middle = r"""
  FOR key IN SELECT pg_catalog.jsonb_object_keys(materials) LOOP
   collection:=pg_catalog.split_part(key,':',1);local_id:=pg_catalog.split_part(key,':',2);
   source:=CASE WHEN collection='membership' THEN evidence->'membership' ELSE evidence->collection->(local_id::integer) END;
   SELECT f.value INTO target FROM pg_catalog.jsonb_array_elements(payload->'facts') f(value)
    WHERE f.value->>'member_id'=input.member_id::text AND f.value->>'collection'=collection AND f.value->>'local_id'=local_id;
   item:=pg_catalog.jsonb_build_object('economic_group_id',target->'economic_group_id','accepted_revision_id',target->'accepted_revision_id',
    'change',target->'action','windows',(SELECT COALESCE(pg_catalog.jsonb_agg(cv.value),'[]'::jsonb) FROM pg_catalog.jsonb_each(materials) cv
     WHERE cv.key LIKE 'coverage:%'),'source',source_keys->key,'material',materials->key,'typed',source,
    'revision',CASE WHEN collection='records' THEN source->'identity'->'revision' ELSE source->'revision' END);
   incoming:=pg_catalog.jsonb_set(incoming,ARRAY[input.member_id::text||':'||key],item);
   IF source->>'record_type'='activity' THEN
    claims:=claims||(source->'economic_references')||CASE WHEN source->'cash_flow'='null'::jsonb THEN '[]'::jsonb
     ELSE (SELECT COALESCE(pg_catalog.jsonb_agg(x.value),'[]'::jsonb) FROM (VALUES(source->'cash_flow'->'counterpart'),(source->'cash_flow'->'cash_leg_of')) x(value) WHERE x.value<>'null'::jsonb) END;
   END IF;
   scope_keys:=scope_keys||pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(source_keys->key)),'hex');
  END LOOP;
 END LOOP;
 -- Include active activity heads for same-account competing-stream checks.
 SELECT COALESCE(array_agg(DISTINCT wanted.id),ARRAY[]::uuid[]) INTO needed FROM (
  SELECT (f.value->>'accepted_revision_id')::uuid AS id FROM pg_catalog.jsonb_array_elements(payload->'facts') f(value) WHERE f.value->>'action'='duplicate'
   AND NOT EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(payload->'facts') n(value) WHERE n.value->'accepted_revision_id'=f.value->'accepted_revision_id' AND n.value->>'action'<>'duplicate')
  UNION ALL SELECT (f.value->>'parent_revision_id')::uuid FROM pg_catalog.jsonb_array_elements(payload->'facts') f(value) WHERE f.value->'parent_revision_id'<>'null'::jsonb
   AND NOT EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(payload->'facts') n(value) WHERE n.value->'accepted_revision_id'=f.value->'parent_revision_id' AND n.value->>'action'<>'duplicate')
  UNION ALL SELECT (edge.value->>'accepted_revision_id')::uuid FROM pg_catalog.jsonb_array_elements(payload->'authorities') a(value)
   CROSS JOIN LATERAL (VALUES(a.value->'left'),(a.value->'right')) edge(value) WHERE edge.value->>'form'='accepted'
  UNION ALL SELECT (value->>'prior_revision_id')::uuid FROM pg_catalog.jsonb_array_elements(payload->'heads') WHERE value->'prior_revision_id'<>'null'::jsonb
  UNION ALL SELECT (h.value->>'complete_base_id')::uuid FROM pg_catalog.jsonb_array_elements(payload->'heads') h(value) WHERE h.value->'complete_base_id'<>'null'::jsonb
   AND NOT EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(payload->'facts') f(value) WHERE f.value->'accepted_revision_id'=h.value->'complete_base_id' AND f.value->>'action'<>'duplicate')
  UNION ALL SELECT l.source_revision_id FROM wl_ingestion.lineage l WHERE l.tenant_id=p_tenant AND l.portfolio_id=p_portfolio
   AND EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(claims) c(value) WHERE
    (pg_catalog.convert_from(l.source_claim_bytes,'UTF8')::jsonb->'source')-ARRAY['version','tenant_id','portfolio_id','connection_id','collection']=c.value-'revision'
    AND (c.value->'revision'='null'::jsonb OR c.value->'revision'=pg_catalog.convert_from(l.source_claim_bytes,'UTF8')::jsonb->'revision'))
  UNION ALL SELECT h.revision_id FROM wl_ingestion.activity_heads h WHERE h.tenant_id=p_tenant AND h.portfolio_id=p_portfolio AND h.active
  UNION ALL SELECT s.id FROM wl_ingestion.source_revisions s WHERE s.tenant_id=p_tenant AND s.portfolio_id=p_portfolio AND s.source_key=ANY(scope_keys)
 ) wanted;
 FOREACH wanted_id IN ARRAY needed LOOP
  SELECT * INTO accepted FROM wl_ingestion.source_revisions s WHERE s.tenant_id=p_tenant AND s.portfolio_id=p_portfolio AND s.id=wanted_id;
  IF accepted.id IS NULL THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  SELECT * INTO old_input FROM wl_ingestion.accepted_inputs a WHERE a.tenant_id=p_tenant AND a.portfolio_id=p_portfolio AND a.id=accepted.input_id;
  IF old_input.id IS NULL OR pg_catalog.encode(pg_catalog.sha256(old_input.canonical_bytes),'hex')<>old_input.digest THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  SELECT p.* INTO old_plan FROM wl_ingestion.accepted_plans p WHERE p.tenant_id=p_tenant AND p.portfolio_id=p_portfolio
   AND EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(pg_catalog.convert_from(p.canonical_bytes,'UTF8')::jsonb->'facts') f(value)
    WHERE f.value->>'accepted_revision_id'=wanted_id::text AND f.value->>'action'<>'duplicate')
   AND EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(pg_catalog.convert_from(p.canonical_bytes,'UTF8')::jsonb->'inputs') i(value)
    WHERE i.value->>'stage_digest'=old_input.digest)
   ORDER BY p.created_at,p.id LIMIT 1;
  IF old_plan.id IS NULL OR pg_catalog.encode(pg_catalog.sha256(old_plan.canonical_bytes),'hex')<>old_plan.digest THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  old_payload:=pg_catalog.convert_from(old_plan.canonical_bytes,'UTF8')::jsonb;
  IF old_plan.canonical_bytes<>wl_ingestion._canonical_v1(old_payload) OR
   old_payload->>'tenant_id'<>p_tenant::text OR old_payload->>'portfolio_id'<>p_portfolio::text THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  SELECT value INTO old_effect FROM pg_catalog.jsonb_array_elements(old_payload->'facts') WHERE value->>'accepted_revision_id'=wanted_id::text AND value->>'action'<>'duplicate';
  SELECT value INTO pin FROM pg_catalog.jsonb_array_elements(old_payload->'pinned_sources') WHERE value->'member_id'=old_effect->'member_id';
  IF NOT EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(old_payload->'inputs') WHERE value->'member_id'=old_effect->'member_id' AND value->>'stage_digest'=old_input.digest) THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  evidence:=wl_ingestion._validate_minimal_v1(old_input.canonical_bytes);
  SELECT COALESCE(pg_catalog.jsonb_object_agg((value->>'entity_kind')||':'||(value->>'local_id'),(value->'target')-'mode'),'{}'::jsonb)
   INTO refs FROM pg_catalog.jsonb_array_elements(old_payload->'mappings') WHERE value->'member_id'=old_effect->'member_id';
"""
    tail = r"""
  key:=accepted.collection||':'||accepted.local_id;
  source:=CASE WHEN accepted.collection='membership' THEN evidence->'membership' ELSE evidence->accepted.collection->(accepted.local_id::integer) END;
  IF source IS NULL OR source='null'::jsonb OR accepted.typed_bytes<>wl_ingestion._canonical_v1(source) OR
   accepted.typed_digest<>pg_catalog.encode(pg_catalog.sha256(accepted.typed_bytes),'hex') OR
   accepted.source_key<>pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(source_keys->key)),'hex') OR
   accepted.financial_digest<>pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(materials->key)),'hex') OR
   accepted.source_revision IS DISTINCT FROM (CASE WHEN accepted.collection='records' THEN source->'identity'->>'revision' ELSE source->>'revision' END) THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  item:=pg_catalog.jsonb_build_object('source',source_keys->key,'material',materials->key,'typed',source,
   'revision',accepted.source_revision,'parent',accepted.parent_id,'change',accepted.accepted_change,
   'economic_group_id',old_effect->'economic_group_id','accepted_revision_id',accepted.id::text,
   'windows',(SELECT COALESCE(pg_catalog.jsonb_agg(cv.value),'[]'::jsonb) FROM pg_catalog.jsonb_each(materials) cv WHERE cv.key LIKE 'coverage:%'));
  accepted_basis:=pg_catalog.jsonb_set(accepted_basis,ARRAY[wanted_id::text],item);
 END LOOP;
 FOR effect IN SELECT value FROM pg_catalog.jsonb_array_elements(payload->'facts') LOOP
  key:=(effect->>'member_id')||':'||(effect->>'collection')||':'||(effect->>'local_id');
  item:=incoming->key;source_key:=item->'source';material:=item->'material';
  IF effect->>'action'='duplicate' THEN
   entry:=accepted_basis->(effect->>'accepted_revision_id');
   IF entry IS NULL THEN
    SELECT incoming->((f.value->>'member_id')||':'||(f.value->>'collection')||':'||(f.value->>'local_id')) INTO entry
     FROM pg_catalog.jsonb_array_elements(payload->'facts') f(value) WHERE f.value->'accepted_revision_id'=effect->'accepted_revision_id' AND f.value->>'action'<>'duplicate';
   END IF;
   IF entry IS NULL OR entry->'source'<>source_key OR entry->'material'<>material OR
    entry->'economic_group_id' IS DISTINCT FROM effect->'economic_group_id' THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  ELSE
   IF EXISTS(SELECT 1 FROM wl_ingestion.source_revisions s WHERE s.tenant_id=p_tenant AND s.portfolio_id=p_portfolio AND s.id=(effect->>'accepted_revision_id')::uuid) THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  END IF;
  key:=pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(pg_catalog.jsonb_build_object('source',source_key,'revision',item->'revision'))),'hex');
  IF identities ? key AND (identities->key->'source'<>source_key OR identities->key->'material'<>material OR
   identities->key->'accepted_revision_id'<>effect->'accepted_revision_id') THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  identities:=pg_catalog.jsonb_set(identities,ARRAY[key],item||pg_catalog.jsonb_build_object('accepted_revision_id',effect->'accepted_revision_id'));
  FOR edit IN SELECT l.source_revision_id,l.source_claim_bytes FROM wl_ingestion.lineage l WHERE l.tenant_id=p_tenant AND l.portfolio_id=p_portfolio AND
   pg_catalog.convert_from(l.source_claim_bytes,'UTF8')::jsonb->'source'=source_key AND pg_catalog.convert_from(l.source_claim_bytes,'UTF8')::jsonb->'revision'=item->'revision' LOOP
   IF edit.source_claim_bytes<>wl_ingestion._canonical_v1(pg_catalog.convert_from(edit.source_claim_bytes,'UTF8')::jsonb) OR
    (accepted_basis->(edit.source_revision_id::text)->'material') IS DISTINCT FROM material OR effect->>'action'<>'duplicate' OR edit.source_revision_id::text<>effect->>'accepted_revision_id' THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  END LOOP;
  -- Full selector bytes accompany the index hash, and exact revisions cannot change meaning.
  FOR edit IN SELECT * FROM pg_catalog.jsonb_each(accepted_basis) LOOP
   entry:=edit.value;
   IF pg_catalog.sha256(wl_ingestion._canonical_v1(entry->'source'))=pg_catalog.sha256(wl_ingestion._canonical_v1(source_key)) THEN
    IF entry->'source'<>source_key OR (entry->'revision'=item->'revision' AND
     (entry->'material'<>material OR effect->>'action'<>'duplicate' OR edit.key<>effect->>'accepted_revision_id')) THEN
     RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
   END IF;
  END LOOP;
  IF effect->>'action' IN ('append','mirror') AND effect->>'collection'<>'snapshots' AND
   EXISTS(SELECT 1 FROM pg_catalog.jsonb_each(accepted_basis) a WHERE a.value->'source'=source_key) THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  IF effect->'parent_revision_id'<>'null'::jsonb THEN
   parent:=accepted_basis->(effect->>'parent_revision_id');
   IF parent IS NULL THEN
    SELECT incoming->((value->>'member_id')||':'||(value->>'collection')||':'||(value->>'local_id')) INTO parent
     FROM pg_catalog.jsonb_array_elements(payload->'facts') WHERE value->'accepted_revision_id'=effect->'parent_revision_id' AND value->>'action'<>'duplicate';
   END IF;
   IF parent IS NULL OR parent->'source'<>source_key OR parent->'revision'=item->'revision' OR
    parent->'economic_group_id' IS DISTINCT FROM effect->'economic_group_id' OR parent->>'change'='void' THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
   IF effect->>'action'<>'duplicate' AND EXISTS(SELECT 1 FROM wl_ingestion.source_revisions s
    WHERE s.tenant_id=p_tenant AND s.portfolio_id=p_portfolio AND s.parent_id=(effect->>'parent_revision_id')::uuid) THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale'; END IF;
   claim:=COALESCE(item->'typed'->'identity'->'parent',item->'typed'->'parent','null'::jsonb);
   IF claim<>'null'::jsonb AND (claim-'revision' IS DISTINCT FROM
    (parent->'source')-ARRAY['version','tenant_id','portfolio_id','connection_id','collection'] OR
    claim->'revision' IS DISTINCT FROM parent->'revision') THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  END IF;
  IF effect->>'collection'='snapshots' AND effect->>'action' IN ('append','correction') THEN
   source:=item->'typed';
   SELECT count(DISTINCT pg_catalog.jsonb_build_object('account',a.value->'target'->'id',
    'scope', (c.value->'instrument_scope')-'asset_local_ids'||pg_catalog.jsonb_build_object('instrument_ids',
     (SELECT COALESCE(pg_catalog.jsonb_agg(m.value->'target'->'id' ORDER BY m.value->'target'->>'id' COLLATE "C"),'[]'::jsonb)
      FROM pg_catalog.jsonb_array_elements(payload->'mappings') m(value) WHERE m.value->'member_id'=effect->'member_id' AND m.value->>'entity_kind'='instrument'
       AND c.value->'instrument_scope'->'asset_local_ids' ? (m.value->>'local_id'))))) INTO order_value
    FROM pg_catalog.jsonb_array_elements(source->'coverage_local_ids') cv(value)
    JOIN pg_catalog.jsonb_each(incoming) i ON i.key=(effect->>'member_id')||':coverage:'||(cv.value#>>'{}')
    CROSS JOIN LATERAL (SELECT i.value->'typed' AS value) c
    JOIN pg_catalog.jsonb_array_elements(payload->'mappings') a(value) ON a.value->'member_id'=effect->'member_id' AND a.value->>'entity_kind'='account' AND a.value->'local_id'=c.value->'account_local_id'
    WHERE c.value->>'kind'='holdings';
   IF order_value<>(SELECT count(*) FROM pg_catalog.jsonb_array_elements(payload->'heads') h(value) WHERE h.value->>'kind'='snapshot' AND h.value->'next_revision_id'=effect->'accepted_revision_id') THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  END IF;
  IF item->'typed'->>'record_type'='activity' AND effect->>'action' IN ('append','correction','void') AND
   NOT EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(payload->'facts') child(value) WHERE child.value->'parent_revision_id'=effect->'accepted_revision_id' AND child.value->>'action'<>'duplicate') AND
   NOT EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(payload->'heads') h(value) WHERE h.value->>'kind'='activity' AND h.value->'next_revision_id'=effect->'accepted_revision_id') THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  IF effect->>'action'='historical' AND NOT EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(payload->'authorities') a(value)
   WHERE a.value->>'kind'='historical_only' AND a.value->'left'=pg_catalog.jsonb_build_object('form','incoming',
    'member_id',effect->'member_id','collection',effect->'collection','local_id',effect->'local_id')) AND NOT EXISTS(
    SELECT 1 FROM pg_catalog.jsonb_array_elements(payload->'authorities') a(value)
    JOIN pg_catalog.jsonb_array_elements(payload->'facts') sf(value) ON sf.value->'member_id'=a.value->'left'->'member_id'
     AND sf.value->'collection'=a.value->'left'->'collection' AND sf.value->'local_id'=a.value->'left'->'local_id'
    JOIN pg_catalog.jsonb_each(incoming) si ON si.key=(sf.value->>'member_id')||':snapshots:'||(sf.value->>'local_id')
    WHERE a.value->>'kind'='historical_only' AND a.value->'left'->>'form'='incoming'
     AND a.value->'left'->>'collection'='snapshots' AND sf.value->>'action'='historical'
     AND sf.value->'member_id'=effect->'member_id' AND
      ((effect->>'collection'='records' AND si.value->'typed'->'position_local_ids' ? (effect->>'local_id')) OR
       (effect->>'collection'='coverage' AND si.value->'typed'->'coverage_local_ids' ? (effect->>'local_id')))) THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
 END LOOP;
 FOR proposal IN SELECT value FROM pg_catalog.jsonb_array_elements(payload->'authorities') LOOP
  left_id:=NULL;right_id:=NULL;left_item:=NULL;right_item:=NULL;
  FOREACH field IN ARRAY ARRAY['left','right'] LOOP
   ref:=proposal->field;
   IF ref='null'::jsonb THEN CONTINUE; END IF;
   IF ref->>'form'='accepted' THEN key:=ref->>'accepted_revision_id';
   ELSE SELECT f.value->>'accepted_revision_id' INTO key FROM pg_catalog.jsonb_array_elements(payload->'facts') f(value)
    WHERE f.value->'member_id'=ref->'member_id' AND f.value->'collection'=ref->'collection' AND f.value->'local_id'=ref->'local_id'; END IF;
   IF key IS NULL THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
   item:=CASE WHEN ref->>'form'='accepted' THEN accepted_basis->key ELSE
    incoming->((ref->>'member_id')||':'||(ref->>'collection')||':'||(ref->>'local_id')) END;
   IF item IS NULL THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
   IF field='left' THEN left_id:=key;left_item:=item; ELSE right_id:=key;right_item:=item; END IF;
  END LOOP;
  IF right_item IS NOT NULL AND (left_item->'source'->'collection'<>right_item->'source'->'collection' OR
   left_item->'typed'->'record_type' IS DISTINCT FROM right_item->'typed'->'record_type' OR
   left_item->'material'->'source_account'->'id' IS DISTINCT FROM right_item->'material'->'source_account'->'id' OR
   left_item->'material'->'account'->'id' IS DISTINCT FROM right_item->'material'->'account'->'id' OR
   (left_item->'source'->>'collection'='coverage' AND left_item->'typed'->'kind'<>right_item->'typed'->'kind')) THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  IF left_id=right_id THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  authority_edges:=authority_edges||pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object('left',left_id,'right',right_id,'kind',proposal->'kind'));
 END LOOP;
 IF EXISTS(WITH RECURSIVE latest AS (
  SELECT DISTINCT ON(a.id) a.id,a.left_revision_id::text AS lhs,a.right_revision_id::text AS rhs,a.decision_kind
   FROM wl_ingestion.authority_links a WHERE a.tenant_id=p_tenant AND a.portfolio_id=p_portfolio ORDER BY a.id,a.revision DESC
 ), edges(lhs,rhs) AS (
  SELECT a.lhs,a.rhs FROM latest a WHERE a.decision_kind='mirror' AND NOT EXISTS(
   SELECT 1 FROM pg_catalog.jsonb_array_elements(authority_edges) n(value) WHERE
    LEAST(n.value->>'left',n.value->>'right')=LEAST(a.lhs,a.rhs) AND GREATEST(n.value->>'left',n.value->>'right')=GREATEST(a.lhs,a.rhs))
  UNION SELECT n.value->>'left',n.value->>'right' FROM pg_catalog.jsonb_array_elements(authority_edges) n(value) WHERE n.value->>'kind'='mirror'
 ), walk(lhs,rhs,path,cycle) AS (
  SELECT e.lhs,e.rhs,ARRAY[e.lhs],e.lhs=e.rhs FROM edges e UNION ALL
  SELECT w.lhs,e.rhs,w.path||e.lhs,e.rhs=ANY(w.path) FROM walk w JOIN edges e ON e.lhs=w.rhs WHERE NOT w.cycle
 ) SELECT 1 FROM walk w WHERE w.cycle) THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
 FOR effect IN SELECT value FROM pg_catalog.jsonb_array_elements(payload->'facts') WHERE value->>'action'='mirror' LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(authority_edges) e(value) WHERE e.value->>'kind'='mirror' AND e.value->'left'=effect->'accepted_revision_id') THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
 END LOOP;
 FOR claim IN SELECT value FROM pg_catalog.jsonb_array_elements(claims) LOOP
  IF (SELECT count(DISTINCT matches.id) FROM (
   SELECT f.value->>'accepted_revision_id' AS id FROM pg_catalog.jsonb_array_elements(payload->'facts') f(value)
    JOIN pg_catalog.jsonb_each(incoming) i ON i.key=(f.value->>'member_id')||':'||(f.value->>'collection')||':'||(f.value->>'local_id')
    WHERE (i.value->'source')-ARRAY['version','tenant_id','portfolio_id','connection_id','collection']=claim-'revision'
     AND (claim->'revision'='null'::jsonb OR claim->'revision'=i.value->'revision')
   UNION ALL SELECT a.key FROM pg_catalog.jsonb_each(accepted_basis) a WHERE
    (a.value->'source')-ARRAY['version','tenant_id','portfolio_id','connection_id','collection']=claim-'revision'
     AND (claim->'revision'='null'::jsonb OR claim->'revision'=a.value->'revision')
  ) matches)<>1 THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
 END LOOP;
 -- A single new parent cannot fork; no cycle can be introduced by incoming edges.
 IF EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(payload->'facts') f(value) WHERE f.value->'parent_revision_id'<>'null'::jsonb
  AND f.value->>'action'<>'duplicate' GROUP BY f.value->'parent_revision_id' HAVING count(*)>1) OR
  EXISTS(WITH RECURSIVE edges(id,parent) AS (SELECT value->>'accepted_revision_id',value->>'parent_revision_id'
   FROM pg_catalog.jsonb_array_elements(payload->'facts') WHERE value->>'action'<>'duplicate'),
   walk(id,parent,path,cycle) AS (SELECT e.id,e.parent,ARRAY[e.id],false FROM edges e UNION ALL
    SELECT w.id,e.parent,w.path||e.id,e.id=ANY(w.path) FROM walk w JOIN edges e ON e.id=w.parent WHERE NOT w.cycle)
   SELECT 1 FROM walk WHERE cycle) THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
 FOR proposal IN SELECT value FROM pg_catalog.jsonb_array_elements(payload->'heads') LOOP
  SELECT value INTO effect FROM pg_catalog.jsonb_array_elements(payload->'facts') WHERE value->'accepted_revision_id'=proposal->'next_revision_id' AND value->>'action'<>'duplicate';
  IF proposal->>'kind'='activity' THEN
   SELECT h.revision_id,h.active INTO prior_id,active FROM wl_ingestion.activity_heads h
    WHERE h.tenant_id=p_tenant AND h.portfolio_id=p_portfolio AND h.economic_group_id=(effect->>'economic_group_id')::uuid;
   expected_prior_id:=(effect->>'parent_revision_id')::uuid;
   FOR order_value IN 1..pg_catalog.jsonb_array_length(payload->'facts')+1 LOOP
    EXIT WHEN expected_prior_id IS NULL;
    SELECT f.value INTO parent FROM pg_catalog.jsonb_array_elements(payload->'facts') f(value)
     WHERE f.value->>'accepted_revision_id'=expected_prior_id::text AND f.value->>'action'<>'duplicate';
    EXIT WHEN parent IS NULL;
    IF parent->'economic_group_id' IS DISTINCT FROM effect->'economic_group_id' OR parent->>'action'='void' THEN
     RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
    expected_prior_id:=(parent->>'parent_revision_id')::uuid;
   END LOOP;
   IF prior_id IS DISTINCT FROM (proposal->>'prior_revision_id')::uuid OR
    expected_prior_id IS DISTINCT FROM prior_id OR (prior_id IS NOT NULL AND NOT active) THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale'; END IF;
  ELSE
   SELECT h.latest_revision_id,h.complete_base_revision_id INTO prior_id,complete_id FROM wl_ingestion.snapshot_heads h
    WHERE h.tenant_id=p_tenant AND h.portfolio_id=p_portfolio AND h.key_digest=proposal->>'key_digest';
   IF prior_id IS DISTINCT FROM (proposal->>'prior_revision_id')::uuid THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale'; END IF;
   item:=incoming->((effect->>'member_id')||':'||(effect->>'collection')||':'||(effect->>'local_id'));
   ref:=item->'material'->'as_of';
   IF ref->>'tag'='legacy_unspecified' OR (ref->>'tag'='date_only' AND ref->'zone'='null'::jsonb) THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
   IF prior_id IS NOT NULL THEN
    replacement:=accepted_basis->(prior_id::text)->'material'->'as_of';
    IF replacement IS NULL OR replacement->>'tag'='legacy_unspecified' THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
    order_value:=ORDER_EXPRESSION;
    IF order_value IS NULL OR order_value<0 OR (order_value=0 AND effect->'parent_revision_id' IS DISTINCT FROM proposal->'prior_revision_id') THEN
     RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
   END IF;
   IF proposal->'complete_base_id'<>proposal->'next_revision_id' AND (proposal->>'complete_base_id')::uuid IS DISTINCT FROM complete_id THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale'; END IF;
  END IF;
 END LOOP;
EXCEPTION WHEN SQLSTATE '22023' THEN
 IF SQLERRM IN ('import_invalid','import_limit','import_conflict','import_stale','import_mapping_required','import_evidence_unsupported') THEN RAISE; END IF;
 RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
WHEN data_exception THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
WHEN OTHERS THEN RAISE EXCEPTION USING ERRCODE='XX000',MESSAGE='internal_error';
END $references$;
REVOKE ALL ON FUNCTION wl_ingestion._references_v1(uuid,uuid,uuid) FROM PUBLIC;
""".replace('ORDER_EXPRESSION', _minimal_order_sql('ref', 'replacement'))
    tail = tail.replace(" FOR claim IN SELECT value FROM pg_catalog.jsonb_array_elements(claims) LOOP", _stream_authority_sql() + "\n FOR claim IN SELECT value FROM pg_catalog.jsonb_array_elements(claims) LOOP")
    return header + _plan_material_sql() + middle + _plan_material_sql() + tail


def effects_ddl():
    """Render the sole accepted mutation for a checked READY preview.

    The caller authenticates, takes the declared locks, recovers an exact
    receipt first and runs _references_v1 in the same transaction. It then
    inserts the receipt with the returned result; set and member state are
    control changes outside this function.
    """
    header = r"""
CREATE FUNCTION wl_ingestion._effects_v1(p_tenant uuid,p_portfolio uuid,p_preview uuid,p_receipt uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $effects$
DECLARE preview wl_ingestion.previews%ROWTYPE;root wl_ingestion.roots%ROWTYPE;
 payload jsonb;evidence jsonb;pin jsonb;refs jsonb;mapping jsonb;target jsonb;source jsonb;body jsonb;
 identity jsonb;issuer jsonb;material jsonb;materials jsonb;source_key jsonb;source_keys jsonb;
 selector jsonb;children jsonb;ref jsonb;replacement jsonb;effect jsonb;proposal jsonb;item jsonb;event jsonb;
 staged jsonb:='{}'::jsonb;member_refs jsonb:='{}'::jsonb;inputs jsonb:='{}'::jsonb;inserted jsonb:='{}'::jsonb;
 mapped jsonb:='{}'::jsonb;
 key text;local_id text;collection text;kind text;name text;field text;path text[];token text;revision text;
 edit record;input record;n timestamptz;plan_id uuid;input_id uuid;
 prior_id uuid;prior_revision bigint;prior_entity uuid;prior_version text;prior_kind text;prior_reference text;
 prior_left uuid;prior_right uuid;
 left_id uuid;right_id uuid;head_account uuid;head_version text;
 new_ids text[]:=ARRAY[]::text[];head_keys text[]:=ARRAY[]::text[];
 new_facts bigint:=0;historical_facts bigint:=0;duplicates bigint:=0;
 accepted_changed boolean:=false;mapping_changed boolean:=false;after_accepted bigint;after_mapping bigint;
BEGIN
 -- Accepted times are whole seconds so the event token keeps exact precision.
 n:=pg_catalog.date_trunc('second',wl_identity._clock_timestamp_v1());
 IF p_tenant IS NULL OR p_portfolio IS NULL OR p_preview IS NULL OR p_receipt IS NULL OR NOT pg_catalog.isfinite(n) THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid'; END IF;
 SELECT * INTO preview FROM wl_ingestion.previews WHERE tenant_id=p_tenant AND portfolio_id=p_portfolio AND id=p_preview;
 IF preview.id IS NULL OR preview.plan_bytes IS NULL OR
  pg_catalog.encode(pg_catalog.sha256(preview.plan_bytes),'hex') IS DISTINCT FROM preview.plan_digest THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale'; END IF;
 payload:=wl_ingestion._validate_plan_v1(p_tenant,p_portfolio,preview.set_id,preview.plan_bytes);
 SELECT * INTO root FROM wl_ingestion.roots WHERE tenant_id=p_tenant AND portfolio_id=p_portfolio FOR UPDATE;
 -- _validate_plan_v1 also admits a RECONCILING basis; only a READY set is accepted.
 IF NOT EXISTS(SELECT 1 FROM wl_ingestion.sets s WHERE s.tenant_id=p_tenant AND s.portfolio_id=p_portfolio
   AND s.id=preview.set_id AND s.state='READY' AND s.revision=preview.set_revision) THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale'; END IF;
 IF payload->>'preview_id'<>preview.id::text OR root.tenant_id IS NULL OR
  payload->>'expected_accepted_generation'<>root.accepted_generation::text OR
  payload->>'expected_mapping_generation'<>root.mapping_generation::text THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale'; END IF;
 -- An accepted Plan or receipt is recovered by the caller, never applied twice.
 IF EXISTS(SELECT 1 FROM wl_ingestion.accepted_plans a WHERE a.tenant_id=p_tenant AND a.portfolio_id=p_portfolio
   AND (a.digest=preview.plan_digest OR a.receipt_id=p_receipt)) OR
  EXISTS(SELECT 1 FROM wl_ingestion.receipts r WHERE r.tenant_id=p_tenant AND r.portfolio_id=p_portfolio AND r.id=p_receipt) THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
 plan_id:=pg_catalog.gen_random_uuid();
 INSERT INTO wl_ingestion.accepted_plans(tenant_id,portfolio_id,id,preview_id,codec,canonical_bytes,digest,receipt_id,created_at)
  VALUES(p_tenant,p_portfolio,plan_id,preview.id,'acceptance-plan-v1',preview.plan_bytes,preview.plan_digest,p_receipt,n);
 FOR input IN SELECT s.member_id,s.minimal_bytes,s.digest,i.value AS planned FROM wl_ingestion.stages s
  JOIN pg_catalog.jsonb_array_elements(payload->'inputs') i(value)
   ON s.member_id=(i.value->>'member_id')::uuid AND s.digest=i.value->>'stage_digest'
  WHERE s.tenant_id=p_tenant AND s.portfolio_id=p_portfolio AND s.set_id=preview.set_id ORDER BY s.member_id LOOP
  evidence:=wl_ingestion._validate_minimal_v1(input.minimal_bytes);
  staged:=pg_catalog.jsonb_set(staged,ARRAY[input.member_id::text],evidence);
  SELECT value INTO pin FROM pg_catalog.jsonb_array_elements(payload->'pinned_sources') WHERE value->>'member_id'=input.member_id::text;
  SELECT COALESCE(pg_catalog.jsonb_object_agg((value->>'entity_kind')||':'||(value->>'local_id'),(value->'target')-'mode'),'{}'::jsonb)
   INTO refs FROM pg_catalog.jsonb_array_elements(payload->'mappings') WHERE value->>'member_id'=input.member_id::text;
  member_refs:=pg_catalog.jsonb_set(member_refs,ARRAY[input.member_id::text],refs);
  -- Identical canonical input bytes are retained once per scope.
  input_id:=NULL;
  SELECT a.id INTO input_id FROM wl_ingestion.accepted_inputs a WHERE a.tenant_id=p_tenant AND a.portfolio_id=p_portfolio AND a.digest=input.digest;
  IF input_id IS NULL THEN
   input_id:=pg_catalog.gen_random_uuid();
   INSERT INTO wl_ingestion.accepted_inputs(tenant_id,portfolio_id,id,codec,canonical_bytes,digest,raw_digest,
    discovery_digest,installation_id,created_at) VALUES(p_tenant,p_portfolio,input_id,'minimal-evidence-v1',
    input.minimal_bytes,input.digest,input.planned->>'raw_digest',input.planned->>'discovery_digest',pin->>'installation_id',n);
  END IF;
  inputs:=pg_catalog.jsonb_set(inputs,ARRAY[input.member_id::text],pg_catalog.to_jsonb(input_id::text));
  FOR mapping IN SELECT value FROM pg_catalog.jsonb_array_elements(payload->'mappings') WHERE value->>'member_id'=input.member_id::text
   ORDER BY value->>'entity_kind',(value->>'local_id')::integer LOOP
   kind:=mapping->>'entity_kind';local_id:=mapping->>'local_id';target:=mapping->'target';
   source:=evidence->CASE kind WHEN 'account' THEN 'accounts' WHEN 'instrument' THEN 'assets' ELSE 'issuers' END->(local_id::integer);
""" + _ENTITY_BODY_SQL + r"""   key:=kind||':'||(target->>'id');
   -- Proposed bodies are the exact bodies _validate_plan_v1 hashed.
   IF target->>'mode'='proposed' AND NOT inserted ? key THEN
    inserted:=pg_catalog.jsonb_set(inserted,ARRAY[key],body);
    IF kind='account' THEN
     INSERT INTO wl_pg.accounts(tenant_id,portfolio_id,id,version,body,category,role,label)
      VALUES(p_tenant,p_portfolio,(target->>'id')::uuid,target->>'version',body,body->>'category',body->>'role',body->>'label');
    ELSIF kind='issuer' THEN
     INSERT INTO wl_pg.issuers(tenant_id,portfolio_id,id,version,body,label)
      VALUES(p_tenant,p_portfolio,(target->>'id')::uuid,target->>'version',body,body->>'label');
    ELSE
     INSERT INTO wl_pg.instruments(tenant_id,portfolio_id,id,version,body,kind,currency,ticker,mic,symbol,network,
      settlement_identity,issuer_id,issuer_version,identifiers) VALUES(p_tenant,p_portfolio,(target->>'id')::uuid,
      target->>'version',body,body->>'kind',body->>'currency',body->>'ticker',body->>'mic',body->>'symbol',
      body->>'network',body->>'settlement_identity',(body->'issuer'->>'value')::uuid,
      CASE WHEN body->'issuer'='null'::jsonb THEN NULL ELSE refs->('issuer:'||(source->>'issuer_local_id'))->>'version' END,
      body->'identifiers');
    END IF;
   END IF;
   -- A mapping is identified by its connection and closed source identity; a
   -- free-text instrument descriptor is evidence, not identity (owner decision).
   -- An unchanged target appends nothing; a changed target appends a revision.
   source_key:=pg_catalog.jsonb_build_object('version',1,'tenant_id',p_tenant::text,'portfolio_id',p_portfolio::text,
    'connection_id',pin->>'connection_id','entity_kind',kind,'source_identity',CASE WHEN kind='account'
     THEN pg_catalog.jsonb_build_object('source_account_key',source->'source_account_key')
     ELSE source-ARRAY['local_id','identifier','issuer_local_id','source_descriptor'] END);
   token:=pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(source_key)),'hex');
   -- Sources sharing one mapping identity must share one target in a Plan;
   -- otherwise the mapping history would flip between them.
   IF mapped ? token AND mapped->token<>(target-'mode') THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
   mapped:=pg_catalog.jsonb_set(mapped,ARRAY[token],target-'mode');
   prior_id:=NULL;prior_revision:=0;prior_entity:=NULL;prior_version:=NULL;
   SELECT m.id,m.revision,m.entity_id,m.entity_version INTO prior_id,prior_revision,prior_entity,prior_version
    FROM wl_ingestion.mappings m WHERE m.tenant_id=p_tenant AND m.portfolio_id=p_portfolio AND
     m.connection_id=(pin->>'connection_id')::uuid AND m.entity_kind=kind AND m.source_key=token
    ORDER BY m.revision DESC LIMIT 1;
   IF prior_id IS NULL OR prior_entity<>(target->>'id')::uuid OR prior_version<>target->>'version' THEN
    INSERT INTO wl_ingestion.mappings(tenant_id,portfolio_id,id,revision,connection_id,source_key,entity_kind,
     evidence_digest,plan_id,account_id,account_version,instrument_id,instrument_version,issuer_id,issuer_version)
     VALUES(p_tenant,p_portfolio,COALESCE(prior_id,pg_catalog.gen_random_uuid()),COALESCE(prior_revision,0)+1,
      (pin->>'connection_id')::uuid,token,kind,
      pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(source)),'hex'),plan_id,
      CASE WHEN kind='account' THEN (target->>'id')::uuid END,CASE WHEN kind='account' THEN target->>'version' END,
      CASE WHEN kind='instrument' THEN (target->>'id')::uuid END,CASE WHEN kind='instrument' THEN target->>'version' END,
      CASE WHEN kind='issuer' THEN (target->>'id')::uuid END,CASE WHEN kind='issuer' THEN target->>'version' END);
    mapping_changed:=true;
   END IF;
  END LOOP;
"""
    facts = r"""
  FOR effect IN SELECT value FROM pg_catalog.jsonb_array_elements(payload->'facts') WHERE value->>'member_id'=input.member_id::text
   ORDER BY value->>'collection',(value->>'local_id')::integer LOOP
   collection:=effect->>'collection';local_id:=effect->>'local_id';key:=collection||':'||local_id;
   source:=CASE WHEN collection='membership' THEN evidence->'membership' ELSE evidence->collection->(local_id::integer) END;
   source_key:=source_keys->key;material:=materials->key;
   revision:=CASE WHEN collection='records' THEN source->'identity'->>'revision' ELSE source->>'revision' END;
   IF source IS NULL OR source='null'::jsonb OR source_key IS NULL OR
    pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(material)),'hex')<>effect->>'financial_digest' THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
   IF effect->>'action'='duplicate' THEN
    duplicates:=duplicates+1;
   ELSE
    -- Source metadata keeps the reported change; accepted_change records lineage.
    INSERT INTO wl_ingestion.source_revisions(tenant_id,portfolio_id,id,source_key,source_revision,financial_digest,
     source_change,accepted_change,parent_id,input_id,collection,local_id,typed_bytes,typed_digest,created_at)
     VALUES(p_tenant,p_portfolio,(effect->>'accepted_revision_id')::uuid,
      pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(source_key)),'hex'),revision,effect->>'financial_digest',
      CASE WHEN collection='records' THEN source->'identity'->>'change'
       WHEN source->'parent'<>'null'::jsonb THEN 'correction' ELSE 'original' END,
      CASE WHEN effect->>'action'='append' THEN 'original' ELSE effect->>'action' END,
      (effect->>'parent_revision_id')::uuid,(inputs->>input.member_id::text)::uuid,collection,local_id,
      wl_ingestion._canonical_v1(source),pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(source)),'hex'),n);
    new_facts:=new_facts+1;new_ids:=new_ids||(effect->>'accepted_revision_id');accepted_changed:=true;
    IF effect->>'action'='historical' THEN historical_facts:=historical_facts+1; END IF;
   END IF;
   -- Every planned fact keeps its exact source claim against its target revision.
   INSERT INTO wl_ingestion.lineage(tenant_id,portfolio_id,source_revision_id,raw_digest,installation_id,
    evidence_digest,input_id,collection,local_id,source_claim_bytes) VALUES(p_tenant,p_portfolio,
    (effect->>'accepted_revision_id')::uuid,input.planned->>'raw_digest',pin->>'installation_id',
    pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(source)),'hex'),(inputs->>input.member_id::text)::uuid,
    collection,local_id,wl_ingestion._canonical_v1(pg_catalog.jsonb_build_object('version',1,'source',source_key,
     'revision',revision))) ON CONFLICT DO NOTHING;
  END LOOP;
 END LOOP;
 IF (SELECT count(*) FROM pg_catalog.jsonb_object_keys(inputs))<>pg_catalog.jsonb_array_length(payload->'inputs') THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale'; END IF;
 -- Head writes are compare-and-set against the prior target named in the Plan.
 FOR proposal IN SELECT value FROM pg_catalog.jsonb_array_elements(payload->'heads') LOOP
  SELECT value INTO effect FROM pg_catalog.jsonb_array_elements(payload->'facts')
   WHERE value->'accepted_revision_id'=proposal->'next_revision_id' AND value->>'action'<>'duplicate';
  IF proposal->>'kind'='activity' THEN
   IF proposal->'prior_revision_id'='null'::jsonb THEN
    INSERT INTO wl_ingestion.activity_heads(tenant_id,portfolio_id,economic_group_id,revision_id,active)
     VALUES(p_tenant,p_portfolio,(effect->>'economic_group_id')::uuid,(proposal->>'next_revision_id')::uuid,(proposal->>'active')::boolean);
   ELSE
    UPDATE wl_ingestion.activity_heads SET revision_id=(proposal->>'next_revision_id')::uuid,active=(proposal->>'active')::boolean
     WHERE tenant_id=p_tenant AND portfolio_id=p_portfolio AND economic_group_id=(effect->>'economic_group_id')::uuid
      AND revision_id=(proposal->>'prior_revision_id')::uuid;
    IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale'; END IF;
   END IF;
  ELSE
   -- Recover the covered account and canonical scope whose key the Plan names.
   evidence:=staged->(effect->>'member_id');refs:=member_refs->(effect->>'member_id');
   source:=evidence->'snapshots'->((effect->>'local_id')::integer);
   head_account:=NULL;replacement:=NULL;
   FOR selector IN SELECT evidence->'coverage'->((value#>>'{}')::integer)
    FROM pg_catalog.jsonb_array_elements(source->'coverage_local_ids') LOOP
    IF selector->>'kind'<>'holdings' THEN CONTINUE; END IF;
    SELECT COALESCE(pg_catalog.jsonb_agg(refs->('instrument:'||(value#>>'{}'))->'id' ORDER BY
     refs->('instrument:'||(value#>>'{}'))->>'id' COLLATE "C"),'[]'::jsonb) INTO children
     FROM pg_catalog.jsonb_array_elements(selector->'instrument_scope'->'asset_local_ids');
    item:=(selector->'instrument_scope')-'asset_local_ids'||pg_catalog.jsonb_build_object('instrument_ids',children);
    IF pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(pg_catalog.jsonb_build_object('version',1,
      'tenant_id',p_tenant::text,'portfolio_id',p_portfolio::text,'account_id',refs->('account:'||(selector->>'account_local_id'))->'id',
      'record_kind','holdings','instrument_scope',item))),'hex')=proposal->>'key_digest' THEN
     head_account:=(refs->('account:'||(selector->>'account_local_id'))->>'id')::uuid;
     head_version:=refs->('account:'||(selector->>'account_local_id'))->>'version';replacement:=item;
    END IF;
   END LOOP;
   IF head_account IS NULL THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
   IF proposal->'prior_revision_id'='null'::jsonb THEN
    INSERT INTO wl_ingestion.snapshot_heads(tenant_id,portfolio_id,key_digest,account_id,account_version,fact_kind,
     scope_bytes,latest_revision_id,complete_base_revision_id) VALUES(p_tenant,p_portfolio,proposal->>'key_digest',
     head_account,head_version,'holdings',wl_ingestion._canonical_v1(replacement),
     (proposal->>'next_revision_id')::uuid,(proposal->>'complete_base_id')::uuid);
   ELSE
    UPDATE wl_ingestion.snapshot_heads SET latest_revision_id=(proposal->>'next_revision_id')::uuid,
     complete_base_revision_id=(proposal->>'complete_base_id')::uuid,account_version=head_version
     WHERE tenant_id=p_tenant AND portfolio_id=p_portfolio AND key_digest=proposal->>'key_digest'
      AND latest_revision_id=(proposal->>'prior_revision_id')::uuid;
    IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale'; END IF;
   END IF;
  END IF;
  head_keys:=head_keys||(proposal->>'key_digest');accepted_changed:=true;
 END LOOP;
 -- Authority links append a revision to the latest link for the same pair.
 FOR proposal IN SELECT value FROM pg_catalog.jsonb_array_elements(payload->'authorities') LOOP
  left_id:=NULL;right_id:=NULL;
  FOREACH field IN ARRAY ARRAY['left','right'] LOOP
   ref:=proposal->field;token:=NULL;
   IF ref='null'::jsonb THEN CONTINUE; END IF;
   IF ref->>'form'='accepted' THEN token:=ref->>'accepted_revision_id';
   ELSE SELECT f.value->>'accepted_revision_id' INTO token FROM pg_catalog.jsonb_array_elements(payload->'facts') f(value)
    WHERE f.value->'member_id'=ref->'member_id' AND f.value->'collection'=ref->'collection' AND f.value->'local_id'=ref->'local_id'; END IF;
   IF token IS NULL THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
   IF field='left' THEN left_id:=token::uuid; ELSE right_id:=token::uuid; END IF;
  END LOOP;
  prior_id:=NULL;prior_revision:=0;prior_kind:=NULL;prior_reference:=NULL;prior_left:=NULL;prior_right:=NULL;
  SELECT a.id,a.revision,a.decision_kind,a.evidence_reference,a.left_revision_id,a.right_revision_id
   INTO prior_id,prior_revision,prior_kind,prior_reference,prior_left,prior_right
   FROM wl_ingestion.authority_links a WHERE a.tenant_id=p_tenant AND a.portfolio_id=p_portfolio AND
    ((a.left_revision_id=left_id AND a.right_revision_id IS NOT DISTINCT FROM right_id) OR
     (right_id IS NOT NULL AND a.left_revision_id=right_id AND a.right_revision_id=left_id))
   ORDER BY a.revision DESC LIMIT 1;
  IF prior_id IS NULL OR prior_kind<>proposal->>'kind' OR prior_reference<>proposal->>'evidence_reference' OR
   prior_left<>left_id OR prior_right IS DISTINCT FROM right_id THEN
   INSERT INTO wl_ingestion.authority_links(tenant_id,portfolio_id,id,revision,left_revision_id,right_revision_id,
    decision_kind,evidence_reference,evidence_digest,plan_id) VALUES(p_tenant,p_portfolio,
    COALESCE(prior_id,pg_catalog.gen_random_uuid()),COALESCE(prior_revision,0)+1,left_id,right_id,proposal->>'kind',
    proposal->>'evidence_reference',pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(proposal)),'hex'),plan_id);
   mapping_changed:=true;
  END IF;
 END LOOP;
 -- Generations advance once per accepted set, never once per member or row.
 after_accepted:=root.accepted_generation+CASE WHEN accepted_changed THEN 1 ELSE 0 END;
 after_mapping:=root.mapping_generation+CASE WHEN mapping_changed THEN 1 ELSE 0 END;
 UPDATE wl_ingestion.roots SET accepted_generation=after_accepted,mapping_generation=after_mapping
  WHERE tenant_id=p_tenant AND portfolio_id=p_portfolio;
 INSERT INTO wl_ingestion.audit(tenant_id,portfolio_id,id,receipt_id,action,before_accepted_generation,
  after_accepted_generation,before_mapping_generation,after_mapping_generation,created_at)
  VALUES(p_tenant,p_portfolio,pg_catalog.gen_random_uuid(),p_receipt,
   CASE WHEN accepted_changed OR mapping_changed THEN 'ACCEPTED' ELSE 'NO_CHANGE' END,
   root.accepted_generation,after_accepted,root.mapping_generation,after_mapping,n);
 IF accepted_changed OR mapping_changed THEN
  event:=pg_catalog.jsonb_build_object('version',1,'type','facts.accepted.v1','tenant_id',p_tenant::text,
   'portfolio_id',p_portfolio::text,'receipt_id',p_receipt::text,'accepted_generation',after_accepted::text,
   'mapping_generation',after_mapping::text,'plan_digest',preview.plan_digest,
   'changed_revision_ids',(SELECT COALESCE(pg_catalog.jsonb_agg(x ORDER BY x COLLATE "C"),'[]'::jsonb) FROM pg_catalog.unnest(new_ids) x),
   'changed_head_keys',(SELECT COALESCE(pg_catalog.jsonb_agg(x ORDER BY x COLLATE "C"),'[]'::jsonb)
    FROM (SELECT DISTINCT x FROM pg_catalog.unnest(head_keys) x) keys),
   'accepted_at',pg_catalog.jsonb_build_object('tag','instant','token',
    pg_catalog.to_char(n AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS')||'+00:00','zone',null,'fractional_digits',0));
  INSERT INTO wl_ingestion.outbox(tenant_id,portfolio_id,id,receipt_id,version,type,accepted_generation,plan_digest,
   payload_bytes,payload_digest,created_at,dispatched_at) VALUES(p_tenant,p_portfolio,pg_catalog.gen_random_uuid(),
   p_receipt,1,'facts.accepted.v1',after_accepted,preview.plan_digest,wl_ingestion._canonical_v1(event),
   pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(event)),'hex'),n,NULL);
 END IF;
 RETURN pg_catalog.jsonb_build_object('accepted_generation',after_accepted::text,'mapping_generation',after_mapping::text,
  'new_facts',new_facts::text,'historical_facts',historical_facts::text,'duplicates',duplicates::text,
  'no_change',NOT (accepted_changed OR mapping_changed),'plan_digest',preview.plan_digest,'preview_id',preview.id::text);
EXCEPTION WHEN SQLSTATE '22023' THEN
 IF SQLERRM IN ('import_invalid','import_limit','import_conflict','import_stale','import_mapping_required','import_evidence_unsupported') THEN RAISE; END IF;
 RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
WHEN unique_violation OR foreign_key_violation THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict';
WHEN data_exception THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
WHEN serialization_failure OR deadlock_detected OR lock_not_available OR query_canceled THEN RAISE;
WHEN OTHERS THEN RAISE EXCEPTION USING ERRCODE='XX000',MESSAGE='internal_error';
END $effects$;
REVOKE ALL ON FUNCTION wl_ingestion._effects_v1(uuid,uuid,uuid,uuid) FROM PUBLIC;
"""
    return header + _plan_material_sql() + facts


ACCEPT_DDL = r'''
CREATE FUNCTION wl_ingestion.accept_preview_v1(p_digest text,p_user uuid,p_version bigint,p_realm jsonb,
 p_catalog_digest text,p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $accept$
DECLARE guard jsonb;st wl_pg.instance_state%ROWTYPE;cs wl_sources.catalog_state%ROWTYPE;
 ingestion_state wl_ingestion.instance_state%ROWTYPE;preview wl_ingestion.previews%ROWTYPE;
 selected wl_ingestion.sets%ROWTYPE;member wl_ingestion.members%ROWTYPE;
 cl wl_sources.connection_lifecycle%ROWTYPE;em wl_sources.enablements%ROWTYPE;
 tenant uuid;portfolio uuid;receipt uuid;plan_id uuid;preview_id uuid;n timestamptz;
 ss wl_identity.sessions%ROWTYPE;
 request_digest text;code text;result jsonb;catalog jsonb;wrappers jsonb;generation bigint;
BEGIN
 -- The browser sends only these three opaque fields; finance comes from stored bytes.
 IF pg_catalog.jsonb_typeof(p_payload) IS DISTINCT FROM 'object' OR
  ARRAY(SELECT pg_catalog.jsonb_object_keys(p_payload) ORDER BY 1)<>ARRAY['operation_id','preview_digest','preview_id']::text[] OR
  pg_catalog.jsonb_typeof(p_payload->'operation_id')<>'string' OR pg_catalog.jsonb_typeof(p_payload->'preview_id')<>'string' OR
  pg_catalog.jsonb_typeof(p_payload->'preview_digest')<>'string' OR
  (p_payload->>'operation_id') COLLATE "C" !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' OR
  (p_payload->>'preview_id') COLLATE "C" !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' OR
  p_payload->>'operation_id'='00000000-0000-0000-0000-000000000000' OR
  p_payload->>'preview_id'='00000000-0000-0000-0000-000000000000' OR
  (p_payload->>'preview_digest') COLLATE "C" !~ '^[0-9a-f]{64}$' THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid');
 END IF;
 guard:=wl_ingestion._guard_user_v1(p_digest,p_user,p_version,p_realm,p_catalog_digest);
 IF guard->>'ok' IS DISTINCT FROM 'true' THEN RETURN guard; END IF;
 tenant:=(guard#>>'{value,tenant_id}')::uuid;portfolio:=(guard#>>'{value,portfolio_id}')::uuid;
 preview_id:=(p_payload->>'preview_id')::uuid;
 SELECT * INTO st FROM wl_pg.instance_state WHERE id=1;
 request_digest:=pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(p_payload)),'hex');
 -- An exact receipt is recovered before any mutable preview, source or expiry check.
 BEGIN
  result:=wl_ingestion._replay_v1(tenant,portfolio,st.incarnation,st.restore_epoch,
   (p_payload->>'operation_id')::uuid,'ACCEPT',request_digest);
 EXCEPTION WHEN SQLSTATE '22023' THEN
  -- The same operation ID with a different request is never a new acceptance.
  IF SQLERRM='import_conflict' THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_operation_conflict'); END IF;
  RAISE;
 END;
 IF result IS NOT NULL THEN RETURN pg_catalog.jsonb_build_object('ok',true,'value',result); END IF;
 -- Source lifecycle rows, then ingestion root, set and preview, in the declared order.
 PERFORM 1 FROM wl_sources.lifecycle_roots WHERE tenant_id=tenant AND portfolio_id=portfolio FOR SHARE;
 PERFORM 1 FROM wl_sources.enablements WHERE tenant_id=tenant AND portfolio_id=portfolio ORDER BY plugin_id,capability FOR SHARE;
 PERFORM 1 FROM wl_pg.connections WHERE tenant_id=tenant AND portfolio_id=portfolio ORDER BY id,version FOR SHARE;
 PERFORM 1 FROM wl_sources.connection_lifecycle WHERE tenant_id=tenant AND portfolio_id=portfolio ORDER BY id FOR SHARE;
 SELECT * INTO preview FROM wl_ingestion.previews WHERE tenant_id=tenant AND portfolio_id=portfolio AND id=preview_id;
 IF preview.id IS NULL THEN
  -- After cleanup purges a committed preview, its permanent receipt still answers.
  SELECT pg_catalog.convert_from(r.result_bytes,'UTF8')::jsonb INTO result FROM wl_ingestion.receipts r
   WHERE r.tenant_id=tenant AND r.portfolio_id=portfolio AND r.preview_id=(p_payload->>'preview_id')::uuid AND r.operation_kind='ACCEPT'
    AND r.plan_digest=p_payload->>'preview_digest';
  IF result IS NOT NULL THEN RETURN pg_catalog.jsonb_build_object('ok',true,'value',result); END IF;
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','not_found');
 END IF;
 PERFORM 1 FROM wl_ingestion.roots WHERE tenant_id=tenant AND portfolio_id=portfolio FOR UPDATE;
 SELECT * INTO selected FROM wl_ingestion.sets WHERE tenant_id=tenant AND portfolio_id=portfolio AND id=preview.set_id FOR UPDATE;
 -- Members, then leases and the preview by ID, before any source, entity or head row.
 PERFORM 1 FROM wl_ingestion.members WHERE tenant_id=tenant AND portfolio_id=portfolio AND set_id=preview.set_id ORDER BY id FOR UPDATE;
 PERFORM 1 FROM wl_ingestion.leases WHERE tenant_id=tenant AND portfolio_id=portfolio AND set_id=preview.set_id ORDER BY id FOR UPDATE;
 SELECT * INTO preview FROM wl_ingestion.previews WHERE tenant_id=tenant AND portfolio_id=portfolio AND id=preview_id FOR SHARE;
 -- A concurrent attempt may have committed this operation while we waited, even
 -- if cleanup purged its preview meanwhile; recover that receipt first.
 BEGIN
  result:=wl_ingestion._replay_v1(tenant,portfolio,st.incarnation,st.restore_epoch,
   (p_payload->>'operation_id')::uuid,'ACCEPT',request_digest);
 EXCEPTION WHEN SQLSTATE '22023' THEN
  IF SQLERRM='import_conflict' THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_operation_conflict'); END IF;
  RAISE;
 END;
 IF result IS NOT NULL THEN RETURN pg_catalog.jsonb_build_object('ok',true,'value',result); END IF;
 IF preview.id IS NULL OR selected.id IS NULL THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','not_found'); END IF;
 n:=wl_identity._clock_timestamp_v1();
 -- The session must still be live at the DB clock after every lock wait.
 SELECT * INTO ss FROM wl_identity.sessions WHERE token_digest=p_digest;
SESSION_RECHECK
 -- A committed set is never accepted again; any confirmation reads its original
 -- receipt (owner decision on the COMMITTED transition).
 IF selected.state='COMMITTED' THEN
  SELECT pg_catalog.convert_from(r.result_bytes,'UTF8')::jsonb INTO result FROM wl_ingestion.receipts r
   WHERE r.tenant_id=tenant AND r.portfolio_id=portfolio AND r.id=selected.receipt_id AND r.operation_kind='ACCEPT';
  IF result IS NULL THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_conflict'); END IF;
  -- Only a confirmation of the committed Plan reads its receipt.
  IF result->>'plan_digest' IS DISTINCT FROM p_payload->>'preview_digest' THEN
   RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_stale'); END IF;
  RETURN pg_catalog.jsonb_build_object('ok',true,'value',result);
 END IF;
 IF selected.state IN ('RECEIVING','NORMALIZING','RECONCILING','NEEDS_MAPPING','CONFLICT','READY') AND
  (n>=selected.expires_at OR n>=preview.expires_at) THEN
  -- Expiry wins under the set lock; it fences work and accepts nothing.
  IF n>=selected.expires_at THEN
   UPDATE wl_ingestion.sets SET state='EXPIRED',cleanup_state='pending' WHERE tenant_id=tenant AND portfolio_id=portfolio AND id=selected.id;
   UPDATE wl_ingestion.members SET state='expired',fence=fence+1 WHERE tenant_id=tenant AND portfolio_id=portfolio
    AND set_id=selected.id AND state NOT IN ('rejected','cancelled','expired','committed');
   UPDATE wl_ingestion.leases SET state='cancelled' WHERE tenant_id=tenant AND portfolio_id=portfolio
    AND set_id=selected.id AND state IN ('offered','active');
  END IF;
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_expired');
 END IF;
 IF selected.state='EXPIRED' THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_expired'); END IF;
 IF selected.state='NEEDS_MAPPING' THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_mapping_required'); END IF;
 IF selected.state='CONFLICT' THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_conflict'); END IF;
 IF selected.state<>'READY' OR preview.plan_bytes IS NULL OR preview.set_revision<>selected.revision OR
  preview.plan_digest<>p_payload->>'preview_digest' THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_stale'); END IF;
 -- Every member's pinned connection, enablement, availability and wrapper must still be current.
 SELECT * INTO cs FROM wl_sources.catalog_state WHERE id=1;
 SELECT * INTO ingestion_state FROM wl_ingestion.instance_state WHERE id=1;
 catalog:=pg_catalog.convert_from(cs.bundle_bytes,'UTF8')::jsonb;
 wrappers:=pg_catalog.convert_from(ingestion_state.wrapper_catalog_bytes,'UTF8')::jsonb;
 FOR member IN SELECT * FROM wl_ingestion.members WHERE tenant_id=tenant AND portfolio_id=portfolio AND set_id=selected.id ORDER BY id LOOP
  SELECT * INTO cl FROM wl_sources.connection_lifecycle WHERE tenant_id=tenant AND portfolio_id=portfolio AND id=member.connection_id;
  em:=NULL;
  IF cl.id IS NOT NULL THEN
   SELECT * INTO em FROM wl_sources.enablements WHERE tenant_id=tenant AND portfolio_id=portfolio
    AND plugin_id=cl.plugin_id AND capability=cl.capability;
  END IF;
  IF cl.id IS NULL OR NOT cl.enabled OR em.plugin_id IS NULL OR NOT em.enabled OR NOT EXISTS(
    SELECT 1 FROM pg_catalog.jsonb_array_elements(CASE WHEN pg_catalog.jsonb_typeof(catalog->'availability')='array'
     THEN catalog->'availability' ELSE '[]'::jsonb END) a(value)
    WHERE a.value->>'installation_id'=member.installation_id AND a.value->>'status'='ACTIVE') OR
   -- The wrapper catalog is a top-level array of active profiles (owner decision);
   -- a profile anywhere else, such as a revoked list, does not count.
   NOT EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(CASE WHEN pg_catalog.jsonb_typeof(wrappers)='array'
     THEN wrappers ELSE '[]'::jsonb END) w(value) WHERE pg_catalog.jsonb_typeof(w.value)='object' AND
    w.value->>'profile_digest'=member.wrapper_profile_digest AND w.value->>'installation_id'=member.installation_id) THEN
   RETURN pg_catalog.jsonb_build_object('ok',false,'code','source_unavailable'); END IF;
  SELECT c.generation INTO generation FROM wl_pg.connections c WHERE c.tenant_id=tenant AND c.portfolio_id=portfolio
   AND c.id=member.connection_id AND c.version=member.connection_version;
  IF cl.connection_version<>member.connection_version OR cl.installation_id<>member.installation_id OR
   em.installation_id<>member.installation_id OR em.generation<>member.enablement_generation OR
   generation IS DISTINCT FROM member.connection_generation OR NOT EXISTS(
    SELECT 1 FROM pg_catalog.jsonb_array_elements(catalog->'availability') a(value)
    WHERE a.value->>'installation_id'=member.installation_id AND a.value->>'status'='ACTIVE' AND
     a.value->>'availability_generation'=member.availability_generation::text) THEN
   RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_stale'); END IF;
 END LOOP;
 PERFORM wl_ingestion._references_v1(tenant,portfolio,preview.id);
 receipt:=pg_catalog.gen_random_uuid();
 result:=wl_ingestion._effects_v1(tenant,portfolio,preview.id,receipt);
 SELECT a.id INTO plan_id FROM wl_ingestion.accepted_plans a WHERE a.tenant_id=tenant AND a.portfolio_id=portfolio AND a.receipt_id=receipt;
 SELECT a.created_at INTO n FROM wl_ingestion.audit a WHERE a.tenant_id=tenant AND a.portfolio_id=portfolio AND a.receipt_id=receipt;
 result:=result||pg_catalog.jsonb_build_object('id',receipt::text,'kind','ACCEPT','operation_id',p_payload->>'operation_id',
  'origin_incarnation',st.incarnation::text,'origin_restore_epoch',st.restore_epoch::text,
  'created_at',pg_catalog.jsonb_build_object('tag','instant','token',
   pg_catalog.to_char(n AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS')||'+00:00','zone',null,'fractional_digits',0));
 INSERT INTO wl_ingestion.receipts(tenant_id,portfolio_id,id,incarnation,restore_epoch,operation_id,operation_kind,
  request_digest,preview_id,accepted_plan_id,plan_digest,result_bytes,created_at) VALUES(tenant,portfolio,receipt,
  st.incarnation,st.restore_epoch,(p_payload->>'operation_id')::uuid,'ACCEPT',request_digest,preview.id,plan_id,
  preview.plan_digest,wl_ingestion._canonical_v1(result),n);
 -- Commit is the financial linearization point; it fences any remaining work.
 UPDATE wl_ingestion.sets SET state='COMMITTED',revision=revision+1,receipt_id=receipt,cleanup_state='pending'
  WHERE tenant_id=tenant AND portfolio_id=portfolio AND id=selected.id;
 UPDATE wl_ingestion.members SET state='committed' WHERE tenant_id=tenant AND portfolio_id=portfolio AND set_id=selected.id;
 UPDATE wl_ingestion.leases SET state='cancelled' WHERE tenant_id=tenant AND portfolio_id=portfolio
  AND set_id=selected.id AND state IN ('offered','active');
 -- Deferred references are proven here, so a broken acceptance never reports ok:true.
 SET CONSTRAINTS ACCEPTED_FOREIGN_KEYS IMMEDIATE;
 RETURN pg_catalog.jsonb_build_object('ok',true,'value',result);
EXCEPTION WHEN SQLSTATE '22023' THEN
 -- The failed block rolls back every effect; only a fixed code leaves the database.
 code:=SQLERRM;
 IF code NOT IN ('import_invalid','import_limit','import_conflict','import_stale','import_mapping_required',
  'import_evidence_unsupported','import_operation_conflict','import_expired','instance_not_ready') THEN code:='import_invalid'; END IF;
 RETURN pg_catalog.jsonb_build_object('ok',false,'code',code);
WHEN unique_violation THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_operation_conflict');
WHEN foreign_key_violation THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_conflict');
WHEN data_exception THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid');
WHEN serialization_failure OR deadlock_detected OR lock_not_available OR query_canceled THEN RAISE;
WHEN OTHERS THEN RAISE EXCEPTION USING ERRCODE='XX000',MESSAGE='internal_error';
END $accept$;
REVOKE ALL ON FUNCTION wl_ingestion.accept_preview_v1(text,uuid,bigint,jsonb,text,jsonb) FROM PUBLIC;
'''.replace('SESSION_RECHECK', _identity.check_session()).replace('ACCEPTED_FOREIGN_KEYS', ','.join(
    'wl_ingestion.' + json.loads(x)['name'] for x in _FOREIGN_KEYS if json.loads(x)['table'] in (
        'accepted_inputs', 'accepted_plans', 'source_revisions', 'activity_heads', 'snapshot_heads', 'mappings',
        'authority_links', 'lineage', 'receipts', 'audit', 'outbox')))


REPLAY_DDL = r'''
CREATE FUNCTION wl_ingestion._replay_v1(p_tenant uuid,p_portfolio uuid,p_incarnation uuid,
 p_epoch bigint,p_operation uuid,p_kind text,p_request_digest text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $replay$
DECLARE st wl_pg.instance_state%ROWTYPE;saved wl_ingestion.receipts%ROWTYPE;result jsonb;
BEGIN
 -- Call only after live authentication has derived scope and locked the realm.
 -- A receipt is an outcome, never authentication or authority for a new write.
 IF p_tenant IS NULL OR p_portfolio IS NULL OR p_incarnation IS NULL OR p_operation IS NULL OR
  p_tenant='00000000-0000-0000-0000-000000000000'::uuid OR
  p_portfolio='00000000-0000-0000-0000-000000000000'::uuid OR
  p_incarnation='00000000-0000-0000-0000-000000000000'::uuid OR
  p_operation='00000000-0000-0000-0000-000000000000'::uuid OR p_epoch IS NULL OR p_epoch<0 OR
  p_kind IS NULL OR p_kind NOT IN ('CREATE','DECISIONS','CANCEL','ACCEPT') OR p_request_digest IS NULL OR
  p_request_digest COLLATE "C" !~ '^[0-9a-f]{64}$' THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid'; END IF;
 SELECT * INTO st FROM wl_pg.instance_state WHERE id=1;
 IF st.id IS NULL OR NOT st.ready OR st.incarnation IS DISTINCT FROM p_incarnation OR
  st.restore_epoch IS DISTINCT FROM p_epoch THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='instance_not_ready'; END IF;
 SELECT * INTO saved FROM wl_ingestion.receipts r WHERE r.tenant_id=p_tenant AND r.portfolio_id=p_portfolio
  AND r.incarnation=p_incarnation AND r.restore_epoch=p_epoch AND r.operation_id=p_operation;
 IF saved.id IS NULL THEN RETURN NULL; END IF;
 IF saved.operation_kind IS DISTINCT FROM p_kind OR saved.request_digest IS DISTINCT FROM p_request_digest THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
 IF pg_catalog.octet_length(saved.result_bytes) NOT BETWEEN 1 AND 16384 THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid'; END IF;
 result:=pg_catalog.convert_from(saved.result_bytes,'UTF8')::jsonb;
 IF saved.result_bytes<>wl_ingestion._canonical_v1(result) THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid'; END IF;
 RETURN result;
EXCEPTION WHEN SQLSTATE '22023' THEN
 IF SQLERRM IN ('import_invalid','import_limit','import_conflict','instance_not_ready') THEN RAISE; END IF;
 RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
WHEN data_exception THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
WHEN OTHERS THEN RAISE EXCEPTION USING ERRCODE='XX000',MESSAGE='internal_error';
END $replay$;
REVOKE ALL ON FUNCTION wl_ingestion._replay_v1(uuid,uuid,uuid,bigint,uuid,text,text) FROM PUBLIC;
'''


# Selected shared bounds per bucket: (user rate, instance rate) per 300s window,
# (user, instance) concurrent raw slots and storage sets/bytes. The table checks
# repeat the held limits; rate limits exist only here.
QUOTA_LIMITS = {
    'read': {'rate': (60, 600)},
    'control': {'rate': (30, 300)},
    'raw': {'rate': (10, 60), 'leases': (1, 4)},
    'storage': {'sets': (8, 64), 'bytes': (134217728, 1073741824)},
}
SET_RESERVATION_BYTES = 16777216

QUOTA_DDL = r'''
CREATE FUNCTION wl_ingestion._quota_v1(p_tenant uuid,p_portfolio uuid,p_bucket text,
 p_count bigint,p_bytes bigint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $quota$
DECLARE n timestamptz;ub wl_ingestion.quotas%ROWTYPE;ib wl_ingestion.instance_budgets%ROWTYPE;
 v_rate bigint:=0;v_leases bigint:=0;v_sets bigint:=0;v_bytes bigint:=0;
 user_rate bigint;instance_rate bigint;
BEGIN
 -- Call only after live authentication has derived scope. A rate unit is one
 -- admitted attempt; raw +1/-1 also takes/releases one concurrent slot; storage
 -- +1/-1 reserves/releases one outstanding set with its byte reservation.
 IF p_tenant IS NULL OR p_portfolio IS NULL OR
  p_tenant='00000000-0000-0000-0000-000000000000'::uuid OR
  p_portfolio='00000000-0000-0000-0000-000000000000'::uuid OR p_bucket IS NULL OR
  p_count IS NULL OR p_bytes IS NULL THEN INVALID; END IF;
 IF p_bucket IN ('read','control') THEN
  IF p_count<>1 OR p_bytes<>0 THEN INVALID; END IF;
  v_rate:=1;
  user_rate:=CASE p_bucket WHEN 'read' THEN READ_USER ELSE CONTROL_USER END;
  instance_rate:=CASE p_bucket WHEN 'read' THEN READ_INSTANCE ELSE CONTROL_INSTANCE END;
 ELSIF p_bucket='raw' THEN
  IF p_count NOT IN (1,-1) OR p_bytes<>0 THEN INVALID; END IF;
  v_leases:=p_count; v_rate:=CASE WHEN p_count=1 THEN 1 ELSE 0 END;
  user_rate:=RAW_USER; instance_rate:=RAW_INSTANCE;
 ELSIF p_bucket='storage' THEN
  IF p_count NOT IN (-1,0,1) OR p_bytes NOT BETWEEN -SET_BYTES AND SET_BYTES OR
   (p_count=0 AND p_bytes=0) OR (p_count=1 AND p_bytes<0) OR (p_count=-1 AND p_bytes>0) THEN INVALID; END IF;
  v_sets:=p_count; v_bytes:=p_bytes;
 ELSE INVALID; END IF;
 n:=wl_identity._clock_timestamp_v1();
 IF n IS NULL OR NOT pg_catalog.isfinite(n) THEN INVALID; END IF;
 -- Declared lock order: the instance bucket row precedes the scoped user row.
 INSERT INTO wl_ingestion.instance_budgets(bucket,window_start,used_count,reserved_bytes,lease_count,
  outstanding_sets) VALUES(p_bucket,n,0,0,0,0) ON CONFLICT DO NOTHING;
 SELECT * INTO ib FROM wl_ingestion.instance_budgets b WHERE b.bucket=p_bucket FOR UPDATE;
 INSERT INTO wl_ingestion.quotas(tenant_id,portfolio_id,bucket,window_start,used_count,reserved_bytes,
  lease_count,outstanding_sets) VALUES(p_tenant,p_portfolio,p_bucket,n,0,0,0,0) ON CONFLICT DO NOTHING;
 SELECT * INTO ub FROM wl_ingestion.quotas q WHERE q.tenant_id=p_tenant AND q.portfolio_id=p_portfolio
  AND q.bucket=p_bucket FOR UPDATE;
 IF ib.bucket IS NULL OR ub.bucket IS NULL THEN INVALID; END IF;
 IF v_rate>0 THEN
  -- Only the attempt count resets; held slots, sets and bytes never do.
  IF n>=ib.window_start+interval '300 seconds' THEN
   UPDATE wl_ingestion.instance_budgets SET window_start=n,used_count=0 WHERE bucket=p_bucket
    RETURNING * INTO ib;
  END IF;
  IF n>=ub.window_start+interval '300 seconds' THEN
   UPDATE wl_ingestion.quotas SET window_start=n,used_count=0 WHERE tenant_id=p_tenant AND
    portfolio_id=p_portfolio AND bucket=p_bucket RETURNING * INTO ub;
  END IF;
  IF ub.used_count+v_rate>user_rate OR ib.used_count+v_rate>instance_rate THEN BUSY; END IF;
 END IF;
 -- A release must match an earlier reservation; nothing is released twice.
 IF ub.lease_count+v_leases<0 OR ib.lease_count+v_leases<0 OR
  ub.outstanding_sets+v_sets<0 OR ib.outstanding_sets+v_sets<0 OR
  ub.reserved_bytes+v_bytes<0 OR ib.reserved_bytes+v_bytes<0 THEN INVALID; END IF;
 IF v_leases>0 AND (ub.lease_count+v_leases>RAW_SLOTS_USER OR ib.lease_count+v_leases>RAW_SLOTS_INSTANCE) THEN
  BUSY; END IF;
 IF (v_sets>0 OR v_bytes>0) AND (ub.outstanding_sets+v_sets>SETS_USER OR ib.outstanding_sets+v_sets>SETS_INSTANCE OR
  ub.reserved_bytes+v_bytes>BYTES_USER OR ib.reserved_bytes+v_bytes>BYTES_INSTANCE) THEN LIMIT; END IF;
 UPDATE wl_ingestion.instance_budgets SET used_count=used_count+v_rate,lease_count=lease_count+v_leases,
  outstanding_sets=outstanding_sets+v_sets,reserved_bytes=reserved_bytes+v_bytes WHERE bucket=p_bucket;
 UPDATE wl_ingestion.quotas SET used_count=used_count+v_rate,lease_count=lease_count+v_leases,
  outstanding_sets=outstanding_sets+v_sets,reserved_bytes=reserved_bytes+v_bytes
  WHERE tenant_id=p_tenant AND portfolio_id=p_portfolio AND bucket=p_bucket;
EXCEPTION WHEN SQLSTATE '22023' THEN
 IF SQLERRM IN ('import_invalid','import_limit','import_busy') THEN RAISE; END IF;
 RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
WHEN serialization_failure OR deadlock_detected OR lock_not_available OR query_canceled THEN RAISE;
WHEN data_exception THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
WHEN OTHERS THEN RAISE EXCEPTION USING ERRCODE='XX000',MESSAGE='internal_error';
END $quota$;
REVOKE ALL ON FUNCTION wl_ingestion._quota_v1(uuid,uuid,text,bigint,bigint) FROM PUBLIC;
'''
for _name, _value in (
        ('READ_USER', QUOTA_LIMITS['read']['rate'][0]), ('READ_INSTANCE', QUOTA_LIMITS['read']['rate'][1]),
        ('CONTROL_USER', QUOTA_LIMITS['control']['rate'][0]),
        ('CONTROL_INSTANCE', QUOTA_LIMITS['control']['rate'][1]),
        ('RAW_USER', QUOTA_LIMITS['raw']['rate'][0]), ('RAW_INSTANCE', QUOTA_LIMITS['raw']['rate'][1]),
        ('RAW_SLOTS_USER', QUOTA_LIMITS['raw']['leases'][0]),
        ('RAW_SLOTS_INSTANCE', QUOTA_LIMITS['raw']['leases'][1]),
        ('SETS_USER', QUOTA_LIMITS['storage']['sets'][0]), ('SETS_INSTANCE', QUOTA_LIMITS['storage']['sets'][1]),
        ('BYTES_USER', QUOTA_LIMITS['storage']['bytes'][0]),
        ('BYTES_INSTANCE', QUOTA_LIMITS['storage']['bytes'][1]), ('SET_BYTES', SET_RESERVATION_BYTES)):
    QUOTA_DDL = re.sub(r'\b' + _name + r'\b', str(_value), QUOTA_DDL)
QUOTA_DDL = (QUOTA_DDL.replace('INVALID;', "RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';")
    .replace('BUSY;', "RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_busy';")
    .replace('LIMIT;', "RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_limit';"))


# Transient-only cleanup for one terminal set. Accepted inputs, Plans, source
# revisions, receipts and history are never touched. The caller proves the
# terminal fence and child absence; live work leases make this fail closed.
PURGE_DDL = r'''
CREATE FUNCTION wl_ingestion._purge_v1(p_tenant uuid,p_portfolio uuid,p_set uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $purge$
DECLARE s wl_ingestion.sets%ROWTYPE;
BEGIN
 IF p_tenant IS NULL OR p_portfolio IS NULL OR p_set IS NULL OR
  p_tenant='00000000-0000-0000-0000-000000000000'::uuid OR
  p_portfolio='00000000-0000-0000-0000-000000000000'::uuid OR
  p_set='00000000-0000-0000-0000-000000000000'::uuid THEN INVALID; END IF;
 -- Quota rows precede the set in the declared lock order.
 PERFORM 1 FROM wl_ingestion.instance_budgets b WHERE b.bucket='storage' FOR UPDATE;
 PERFORM 1 FROM wl_ingestion.quotas q WHERE q.tenant_id=p_tenant AND q.portfolio_id=p_portfolio
  AND q.bucket='storage' FOR UPDATE;
 SELECT * INTO s FROM wl_ingestion.sets x WHERE x.tenant_id=p_tenant AND x.portfolio_id=p_portfolio
  AND x.id=p_set FOR UPDATE;
 IF s.id IS NULL THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='not_found'; END IF;
 IF s.state NOT IN ('COMMITTED','REJECTED','CANCELLED','EXPIRED') THEN INVALID; END IF;
 -- Completed cleanup already released the reservation exactly once.
 IF s.cleanup_state='complete' THEN RETURN; END IF;
 IF EXISTS(SELECT 1 FROM wl_ingestion.leases l WHERE l.tenant_id=p_tenant AND l.portfolio_id=p_portfolio
  AND l.set_id=p_set AND l.work_kind<>'cleanup' AND l.state IN ('offered','active')) THEN BUSY; END IF;
 IF s.cleanup_state<>'pending' THEN
  UPDATE wl_ingestion.sets SET cleanup_state='pending' WHERE tenant_id=p_tenant AND
   portfolio_id=p_portfolio AND id=p_set;
 END IF;
 DELETE FROM wl_ingestion.previews WHERE tenant_id=p_tenant AND portfolio_id=p_portfolio AND set_id=p_set;
 DELETE FROM wl_ingestion.decisions WHERE tenant_id=p_tenant AND portfolio_id=p_portfolio AND set_id=p_set;
 DELETE FROM wl_ingestion.stages WHERE tenant_id=p_tenant AND portfolio_id=p_portfolio AND set_id=p_set;
 UPDATE wl_ingestion.members SET context_bytes=NULL WHERE tenant_id=p_tenant AND portfolio_id=p_portfolio
  AND set_id=p_set AND context_bytes IS NOT NULL;
 -- Release only after the transient rows are proven absent.
 IF EXISTS(SELECT 1 FROM wl_ingestion.previews v WHERE v.tenant_id=p_tenant AND v.portfolio_id=p_portfolio
   AND v.set_id=p_set) OR
  EXISTS(SELECT 1 FROM wl_ingestion.decisions d WHERE d.tenant_id=p_tenant AND d.portfolio_id=p_portfolio
   AND d.set_id=p_set) OR
  EXISTS(SELECT 1 FROM wl_ingestion.stages g WHERE g.tenant_id=p_tenant AND g.portfolio_id=p_portfolio
   AND g.set_id=p_set) OR
  EXISTS(SELECT 1 FROM wl_ingestion.members m WHERE m.tenant_id=p_tenant AND m.portfolio_id=p_portfolio
   AND m.set_id=p_set AND m.context_bytes IS NOT NULL) THEN
  RAISE EXCEPTION USING ERRCODE='XX000',MESSAGE='internal_error'; END IF;
 PERFORM wl_ingestion._quota_v1(p_tenant,p_portfolio,'storage',-1,-s.reserved_bytes);
 UPDATE wl_ingestion.sets SET cleanup_state='complete' WHERE tenant_id=p_tenant AND
  portfolio_id=p_portfolio AND id=p_set;
EXCEPTION WHEN SQLSTATE '22023' THEN
 IF SQLERRM IN ('import_invalid','import_busy','not_found') THEN RAISE; END IF;
 RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
WHEN serialization_failure OR deadlock_detected OR lock_not_available OR query_canceled THEN RAISE;
WHEN data_exception THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
WHEN OTHERS THEN RAISE EXCEPTION USING ERRCODE='XX000',MESSAGE='internal_error';
END $purge$;
REVOKE ALL ON FUNCTION wl_ingestion._purge_v1(uuid,uuid,uuid) FROM PUBLIC;
'''.replace('INVALID;', "RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';").replace(
    'BUSY;', "RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_busy';")


def _instant_sql(expression):
    """A closed Instant for a DB timestamp, keeping its exact microseconds."""
    return ("pg_catalog.jsonb_build_object('tag','instant','token',pg_catalog.to_char((" + expression +
            ") AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.US')||'+00:00','zone',null,'fractional_digits',6)")


# Public SetResult for one locked set; members follow their ordinal.
_SET_RESULT_SQL = ("pg_catalog.jsonb_build_object('id',x.id::text,'state',x.state,'revision',x.revision::text,"
    "'created_at'," + _instant_sql('x.created_at') + ",'expires_at'," + _instant_sql('x.expires_at') + ","
    "'members',COALESCE((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('id',m.id::text,"
    "'ordinal',m.ordinal,'connection_id',m.connection_id::text,'installation_id',m.installation_id,"
    "'format_version',m.format_version,'state',m.state,'error_code',m.error_code,'cleanup_state',x.cleanup_state)"
    " ORDER BY m.ordinal) FROM wl_ingestion.members m WHERE m.tenant_id=x.tenant_id AND "
    "m.portfolio_id=x.portfolio_id AND m.set_id=x.id),'[]'::jsonb),"
    "'preview_id',(SELECT v.id::text FROM wl_ingestion.previews v WHERE v.tenant_id=x.tenant_id AND "
    "v.portfolio_id=x.portfolio_id AND v.set_id=x.id ORDER BY v.set_revision DESC,v.created_at DESC,v.id LIMIT 1),"
    "'receipt_id',x.receipt_id::text,'cleanup_state',x.cleanup_state)")

CANCEL_DDL = r"""
CREATE FUNCTION wl_ingestion.cancel_set_v1(p_digest text,p_user uuid,p_version bigint,p_realm jsonb,
 p_catalog_digest text,p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $cancel$
DECLARE guard jsonb;st wl_pg.instance_state%ROWTYPE;ss wl_identity.sessions%ROWTYPE;
 selected wl_ingestion.sets%ROWTYPE;root wl_ingestion.roots%ROWTYPE;
 tenant uuid;portfolio uuid;wanted uuid;receipt uuid;n timestamptz;
 request_digest text;code text;result jsonb;
BEGIN
 -- The route supplies the set ID; the body adds only the operation and revision.
 IF pg_catalog.jsonb_typeof(p_payload) IS DISTINCT FROM 'object' OR
  ARRAY(SELECT pg_catalog.jsonb_object_keys(p_payload) ORDER BY 1)<>
   ARRAY['expected_set_revision','operation_id','set_id']::text[] OR
  pg_catalog.jsonb_typeof(p_payload->'operation_id')<>'string' OR pg_catalog.jsonb_typeof(p_payload->'set_id')<>'string' OR
  pg_catalog.jsonb_typeof(p_payload->'expected_set_revision')<>'string' OR
  (p_payload->>'operation_id') COLLATE "C" !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' OR
  (p_payload->>'set_id') COLLATE "C" !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' OR
  p_payload->>'operation_id'='00000000-0000-0000-0000-000000000000' OR
  p_payload->>'set_id'='00000000-0000-0000-0000-000000000000' OR
  (p_payload->>'expected_set_revision') COLLATE "C" !~ '^[1-9][0-9]{0,17}$' THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid');
 END IF;
 guard:=wl_ingestion._guard_user_v1(p_digest,p_user,p_version,p_realm,p_catalog_digest);
 IF guard->>'ok' IS DISTINCT FROM 'true' THEN RETURN guard; END IF;
 tenant:=(guard#>>'{value,tenant_id}')::uuid;portfolio:=(guard#>>'{value,portfolio_id}')::uuid;
 wanted:=(p_payload->>'set_id')::uuid;
 SELECT * INTO st FROM wl_pg.instance_state WHERE id=1;
 request_digest:=pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(p_payload)),'hex');
 -- An exact earlier cancellation answers before any mutable check.
 BEGIN
  result:=wl_ingestion._replay_v1(tenant,portfolio,st.incarnation,st.restore_epoch,
   (p_payload->>'operation_id')::uuid,'CANCEL',request_digest);
 EXCEPTION WHEN SQLSTATE '22023' THEN
  IF SQLERRM='import_conflict' THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_operation_conflict'); END IF;
  RAISE;
 END;
 IF result IS NOT NULL THEN RETURN pg_catalog.jsonb_build_object('ok',true,'value',result); END IF;
 -- Root, set, members and leases in the declared order, the same rows ACCEPT locks.
 SELECT * INTO root FROM wl_ingestion.roots WHERE tenant_id=tenant AND portfolio_id=portfolio FOR UPDATE;
 SELECT * INTO selected FROM wl_ingestion.sets WHERE tenant_id=tenant AND portfolio_id=portfolio AND id=wanted FOR UPDATE;
 PERFORM 1 FROM wl_ingestion.members WHERE tenant_id=tenant AND portfolio_id=portfolio AND set_id=selected.id ORDER BY id FOR UPDATE;
 PERFORM 1 FROM wl_ingestion.leases WHERE tenant_id=tenant AND portfolio_id=portfolio AND set_id=selected.id ORDER BY id FOR UPDATE;
 -- The same operation may have committed while this call waited for the set.
 BEGIN
  result:=wl_ingestion._replay_v1(tenant,portfolio,st.incarnation,st.restore_epoch,
   (p_payload->>'operation_id')::uuid,'CANCEL',request_digest);
 EXCEPTION WHEN SQLSTATE '22023' THEN
  IF SQLERRM='import_conflict' THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_operation_conflict'); END IF;
  RAISE;
 END;
 IF result IS NOT NULL THEN RETURN pg_catalog.jsonb_build_object('ok',true,'value',result); END IF;
 IF selected.id IS NULL OR root.tenant_id IS NULL THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','not_found'); END IF;
 n:=wl_identity._clock_timestamp_v1();
 SELECT * INTO ss FROM wl_identity.sessions WHERE token_digest=p_digest;
SESSION_RECHECK
 -- Acceptance that won first stays authoritative; cancel reverses nothing.
 IF selected.state='COMMITTED' THEN
  SELECT SET_RESULT INTO result FROM wl_ingestion.sets x WHERE x.tenant_id=tenant AND x.portfolio_id=portfolio AND x.id=wanted;
  RETURN pg_catalog.jsonb_build_object('ok',true,'value',result);
 END IF;
 IF selected.state='EXPIRED' THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_expired'); END IF;
 IF selected.state IN ('CANCELLED','REJECTED') THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_stale'); END IF;
 IF n>=selected.expires_at THEN
  -- Expiry wins under the set lock; it fences work and records no cancellation.
  UPDATE wl_ingestion.sets SET state='EXPIRED',cleanup_state='pending' WHERE tenant_id=tenant AND portfolio_id=portfolio AND id=selected.id;
  UPDATE wl_ingestion.members SET state='expired',fence=fence+1 WHERE tenant_id=tenant AND portfolio_id=portfolio
   AND set_id=selected.id AND state NOT IN ('rejected','cancelled','expired','committed');
  UPDATE wl_ingestion.leases SET state='cancelled' WHERE tenant_id=tenant AND portfolio_id=portfolio
   AND set_id=selected.id AND state IN ('offered','active');
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_expired');
 END IF;
 IF selected.revision<>(p_payload->>'expected_set_revision')::bigint THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_stale'); END IF;
 -- A winning cancellation advances the set revision and control generation once,
 -- fences every member attempt and live lease, and leaves cleanup to the worker.
 UPDATE wl_ingestion.sets SET state='CANCELLED',revision=revision+1,cleanup_state='pending'
  WHERE tenant_id=tenant AND portfolio_id=portfolio AND id=selected.id;
 UPDATE wl_ingestion.members SET state='cancelled',fence=fence+1 WHERE tenant_id=tenant AND portfolio_id=portfolio
  AND set_id=selected.id AND state NOT IN ('rejected','cancelled','expired','committed');
 UPDATE wl_ingestion.leases SET state='cancelled' WHERE tenant_id=tenant AND portfolio_id=portfolio
  AND set_id=selected.id AND state IN ('offered','active');
 UPDATE wl_ingestion.roots SET control_generation=control_generation+1 WHERE tenant_id=tenant AND portfolio_id=portfolio;
 SELECT SET_RESULT INTO result FROM wl_ingestion.sets x WHERE x.tenant_id=tenant AND x.portfolio_id=portfolio AND x.id=wanted;
 receipt:=pg_catalog.gen_random_uuid();
 INSERT INTO wl_ingestion.receipts(tenant_id,portfolio_id,id,incarnation,restore_epoch,operation_id,operation_kind,
  request_digest,preview_id,accepted_plan_id,plan_digest,result_bytes,created_at) VALUES(tenant,portfolio,receipt,
  st.incarnation,st.restore_epoch,(p_payload->>'operation_id')::uuid,'CANCEL',request_digest,NULL,NULL,NULL,
  wl_ingestion._canonical_v1(result),n);
 INSERT INTO wl_ingestion.audit(tenant_id,portfolio_id,id,receipt_id,action,before_accepted_generation,
  after_accepted_generation,before_mapping_generation,after_mapping_generation,created_at)
  VALUES(tenant,portfolio,pg_catalog.gen_random_uuid(),receipt,'CANCELLED',root.accepted_generation,
   root.accepted_generation,root.mapping_generation,root.mapping_generation,n);
 RETURN pg_catalog.jsonb_build_object('ok',true,'value',result);
EXCEPTION WHEN SQLSTATE '22023' THEN
 -- The failed block rolls back every change; only a fixed code leaves the database.
 code:=SQLERRM;
 IF code NOT IN ('import_invalid','import_conflict','import_stale','import_expired','instance_not_ready') THEN
  code:='import_invalid'; END IF;
 RETURN pg_catalog.jsonb_build_object('ok',false,'code',code);
WHEN unique_violation THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_operation_conflict');
WHEN data_exception THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid');
WHEN serialization_failure OR deadlock_detected OR lock_not_available OR query_canceled THEN RAISE;
WHEN OTHERS THEN RAISE EXCEPTION USING ERRCODE='XX000',MESSAGE='internal_error';
END $cancel$;
REVOKE ALL ON FUNCTION wl_ingestion.cancel_set_v1(text,uuid,bigint,jsonb,text,jsonb) FROM PUBLIC;
""".replace('SESSION_RECHECK', _identity.check_session()).replace('SET_RESULT', _SET_RESULT_SQL)


_UUID_RE = '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'


def _decisions_predicate():
    """Closed Decisions shape and scalars; references are checked at preparation."""
    from ..ingestion.contracts import definition
    return _MinimalScalarPredicate().compile("(p_payload->'decisions')", definition('Decisions'))


# Live transient bytes held against a set's fixed reservation.
_HELD_BYTES_SQL = ("(COALESCE((SELECT pg_catalog.sum(pg_catalog.octet_length(m.context_bytes)) FROM wl_ingestion.members m "
    "WHERE m.tenant_id=tenant AND m.portfolio_id=portfolio AND m.set_id=selected.id),0)+"
    "COALESCE((SELECT pg_catalog.sum(pg_catalog.octet_length(g.minimal_bytes)) FROM wl_ingestion.stages g "
    "WHERE g.tenant_id=tenant AND g.portfolio_id=portfolio AND g.set_id=selected.id),0)+"
    "COALESCE((SELECT pg_catalog.sum(pg_catalog.octet_length(d.canonical_bytes)) FROM wl_ingestion.decisions d "
    "WHERE d.tenant_id=tenant AND d.portfolio_id=portfolio AND d.set_id=selected.id),0)+"
    "COALESCE((SELECT pg_catalog.sum(pg_catalog.octet_length(v.review_bytes)+COALESCE(pg_catalog.octet_length(v.plan_bytes),0)) "
    "FROM wl_ingestion.previews v WHERE v.tenant_id=tenant AND v.portfolio_id=portfolio AND v.set_id=selected.id),0))")

DECIDE_DDL = r"""
CREATE FUNCTION wl_ingestion.decide_set_v1(p_digest text,p_user uuid,p_version bigint,p_realm jsonb,
 p_catalog_digest text,p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $decide$
DECLARE guard jsonb;st wl_pg.instance_state%ROWTYPE;ss wl_identity.sessions%ROWTYPE;
 selected wl_ingestion.sets%ROWTYPE;root wl_ingestion.roots%ROWTYPE;
 tenant uuid;portfolio uuid;wanted uuid;operation uuid;receipt uuid;n timestamptz;
 request_digest text;code text;result jsonb;document bytea;latest bigint;
BEGIN
 -- The route supplies the set ID; the body is one complete closed Decisions object.
 IF pg_catalog.jsonb_typeof(p_payload) IS DISTINCT FROM 'object' OR
  ARRAY(SELECT pg_catalog.jsonb_object_keys(p_payload) ORDER BY 1)<>ARRAY['decisions','set_id']::text[] OR
  pg_catalog.jsonb_typeof(p_payload->'set_id')<>'string' OR
  (p_payload->>'set_id') COLLATE "C" !~ 'UUID_RE' OR
  p_payload->>'set_id'='00000000-0000-0000-0000-000000000000' OR NOT DECISIONS_SHAPE OR
  p_payload#>>'{decisions,operation_id}'='00000000-0000-0000-0000-000000000000' OR
  (p_payload#>>'{decisions,expected_set_revision}') COLLATE "C" !~ '^[1-9][0-9]{0,17}$' THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid');
 END IF;
 guard:=wl_ingestion._guard_user_v1(p_digest,p_user,p_version,p_realm,p_catalog_digest);
 IF guard->>'ok' IS DISTINCT FROM 'true' THEN RETURN guard; END IF;
 tenant:=(guard#>>'{value,tenant_id}')::uuid;portfolio:=(guard#>>'{value,portfolio_id}')::uuid;
 wanted:=(p_payload->>'set_id')::uuid;operation:=(p_payload#>>'{decisions,operation_id}')::uuid;
 SELECT * INTO st FROM wl_pg.instance_state WHERE id=1;
 request_digest:=pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(p_payload)),'hex');
 BEGIN
  result:=wl_ingestion._replay_v1(tenant,portfolio,st.incarnation,st.restore_epoch,operation,'DECISIONS',request_digest);
 EXCEPTION WHEN SQLSTATE '22023' THEN
  IF SQLERRM='import_conflict' THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_operation_conflict'); END IF;
  RAISE;
 END;
 IF result IS NOT NULL THEN RETURN pg_catalog.jsonb_build_object('ok',true,'value',result); END IF;
 SELECT * INTO root FROM wl_ingestion.roots WHERE tenant_id=tenant AND portfolio_id=portfolio FOR UPDATE;
 SELECT * INTO selected FROM wl_ingestion.sets WHERE tenant_id=tenant AND portfolio_id=portfolio AND id=wanted FOR UPDATE;
 PERFORM 1 FROM wl_ingestion.members WHERE tenant_id=tenant AND portfolio_id=portfolio AND set_id=selected.id ORDER BY id FOR UPDATE;
 PERFORM 1 FROM wl_ingestion.leases WHERE tenant_id=tenant AND portfolio_id=portfolio AND set_id=selected.id ORDER BY id FOR UPDATE;
 BEGIN
  result:=wl_ingestion._replay_v1(tenant,portfolio,st.incarnation,st.restore_epoch,operation,'DECISIONS',request_digest);
 EXCEPTION WHEN SQLSTATE '22023' THEN
  IF SQLERRM='import_conflict' THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_operation_conflict'); END IF;
  RAISE;
 END;
 IF result IS NOT NULL THEN RETURN pg_catalog.jsonb_build_object('ok',true,'value',result); END IF;
 IF selected.id IS NULL OR root.tenant_id IS NULL THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','not_found'); END IF;
 n:=wl_identity._clock_timestamp_v1();
 SELECT * INTO ss FROM wl_identity.sessions WHERE token_digest=p_digest;
SESSION_RECHECK
 IF selected.state='EXPIRED' THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_expired'); END IF;
 IF selected.state IN ('COMMITTED','CANCELLED','REJECTED') THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_stale'); END IF;
 IF n>=selected.expires_at THEN
  UPDATE wl_ingestion.sets SET state='EXPIRED',cleanup_state='pending' WHERE tenant_id=tenant AND portfolio_id=portfolio AND id=selected.id;
  UPDATE wl_ingestion.members SET state='expired',fence=fence+1 WHERE tenant_id=tenant AND portfolio_id=portfolio
   AND set_id=selected.id AND state NOT IN ('rejected','cancelled','expired','committed');
  UPDATE wl_ingestion.leases SET state='cancelled' WHERE tenant_id=tenant AND portfolio_id=portfolio
   AND set_id=selected.id AND state IN ('offered','active');
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_expired');
 END IF;
 -- Decisions apply only to a reviewed set at the exact revision the owner saw.
 IF selected.state NOT IN ('NEEDS_MAPPING','CONFLICT','READY') OR
  selected.revision<>(p_payload#>>'{decisions,expected_set_revision}')::bigint THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_stale'); END IF;
 document:=wl_ingestion._canonical_v1(p_payload->'decisions');
 -- Retained decisions share the fixed transient reservation of the set; never overcommit.
 IF HELD_BYTES+pg_catalog.octet_length(document)>selected.reserved_bytes THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_limit'); END IF;
 SELECT pg_catalog.max(d.revision) INTO latest FROM wl_ingestion.decisions d
  WHERE d.tenant_id=tenant AND d.portfolio_id=portfolio AND d.set_id=selected.id;
 UPDATE wl_ingestion.sets SET state='RECONCILING',revision=revision+1 WHERE tenant_id=tenant AND portfolio_id=portfolio AND id=selected.id;
 INSERT INTO wl_ingestion.decisions(tenant_id,portfolio_id,set_id,revision,request_digest,canonical_bytes,digest,created_at,purge_at)
  VALUES(tenant,portfolio,selected.id,COALESCE(latest,0)+1,request_digest,document,
   pg_catalog.encode(pg_catalog.sha256(document),'hex'),n,selected.expires_at);
 -- Earlier preparation work is fenced; the worker prepares the new revision.
 UPDATE wl_ingestion.leases SET state='cancelled' WHERE tenant_id=tenant AND portfolio_id=portfolio
  AND set_id=selected.id AND work_kind='prepare' AND state IN ('offered','active');
 UPDATE wl_ingestion.roots SET control_generation=control_generation+1 WHERE tenant_id=tenant AND portfolio_id=portfolio;
 SELECT SET_RESULT INTO result FROM wl_ingestion.sets x WHERE x.tenant_id=tenant AND x.portfolio_id=portfolio AND x.id=wanted;
 receipt:=pg_catalog.gen_random_uuid();
 INSERT INTO wl_ingestion.receipts(tenant_id,portfolio_id,id,incarnation,restore_epoch,operation_id,operation_kind,
  request_digest,preview_id,accepted_plan_id,plan_digest,result_bytes,created_at) VALUES(tenant,portfolio,receipt,
  st.incarnation,st.restore_epoch,operation,'DECISIONS',request_digest,NULL,NULL,NULL,wl_ingestion._canonical_v1(result),n);
 INSERT INTO wl_ingestion.audit(tenant_id,portfolio_id,id,receipt_id,action,before_accepted_generation,
  after_accepted_generation,before_mapping_generation,after_mapping_generation,created_at)
  VALUES(tenant,portfolio,pg_catalog.gen_random_uuid(),receipt,'DECIDED',root.accepted_generation,
   root.accepted_generation,root.mapping_generation,root.mapping_generation,n);
 RETURN pg_catalog.jsonb_build_object('ok',true,'value',result);
EXCEPTION WHEN SQLSTATE '22023' THEN
 code:=SQLERRM;
 IF code NOT IN ('import_invalid','import_limit','import_conflict','import_stale','import_expired','instance_not_ready') THEN
  code:='import_invalid'; END IF;
 RETURN pg_catalog.jsonb_build_object('ok',false,'code',code);
WHEN unique_violation THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_operation_conflict');
WHEN data_exception THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid');
WHEN serialization_failure OR deadlock_detected OR lock_not_available OR query_canceled THEN RAISE;
WHEN OTHERS THEN RAISE EXCEPTION USING ERRCODE='XX000',MESSAGE='internal_error';
END $decide$;
REVOKE ALL ON FUNCTION wl_ingestion.decide_set_v1(text,uuid,bigint,jsonb,text,jsonb) FROM PUBLIC;
""".replace('SESSION_RECHECK', _identity.check_session()).replace('SET_RESULT', _SET_RESULT_SQL).replace(
    'HELD_BYTES', _HELD_BYTES_SQL).replace('UUID_RE', _UUID_RE).replace('DECISIONS_SHAPE', _decisions_predicate())


# Owner decision (Option A): the database builds each member's exact child
# context at creation from stored source state and the operator-reviewed wrapper
# profile. The context fence is the creation fence 1; later raw attempts advance
# only the member/lease fence. job_id and the evidence reference are fresh per
# member, evidence time is the DB clock to whole seconds, and native discovery
# gets a fresh ephemeral namespace, never real tenant or portfolio IDs.
CREATE_DDL = r"""
CREATE FUNCTION wl_ingestion.create_set_v1(p_digest text,p_user uuid,p_version bigint,p_realm jsonb,
 p_catalog_digest text,p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $create$
DECLARE guard jsonb;st wl_pg.instance_state%ROWTYPE;ss wl_identity.sessions%ROWTYPE;
 cs wl_sources.catalog_state%ROWTYPE;ingestion_state wl_ingestion.instance_state%ROWTYPE;
 cl wl_sources.connection_lifecycle%ROWTYPE;em wl_sources.enablements%ROWTYPE;
 tenant uuid;portfolio uuid;realm text;n timestamptz;new_set uuid;receipt uuid;new_member uuid;
 request_digest text;code text;result jsonb;catalog jsonb;wrappers jsonb;profile jsonb;pick jsonb;
 context jsonb;context_raw bytea;evidence text;generation bigint;availability bigint;profiles integer;
 position integer:=0;
BEGIN
 -- Only the operation ID and up to four member selections; no financial values.
 IF pg_catalog.jsonb_typeof(p_payload) IS DISTINCT FROM 'object' OR
  ARRAY(SELECT pg_catalog.jsonb_object_keys(p_payload) ORDER BY 1)<>ARRAY['members','operation_id']::text[] OR
  pg_catalog.jsonb_typeof(p_payload->'operation_id')<>'string' OR
  (p_payload->>'operation_id') COLLATE "C" !~ 'UUID_RE' OR
  p_payload->>'operation_id'='00000000-0000-0000-0000-000000000000' OR
  pg_catalog.jsonb_typeof(p_payload->'members')<>'array' OR
  pg_catalog.jsonb_array_length(p_payload->'members') NOT BETWEEN 1 AND 4 OR EXISTS(
   SELECT 1 FROM pg_catalog.jsonb_array_elements(p_payload->'members') m(value) WHERE
    pg_catalog.jsonb_typeof(m.value)<>'object' OR
    ARRAY(SELECT pg_catalog.jsonb_object_keys(m.value) ORDER BY 1)<>
     ARRAY['connection_id','declared_bytes','format_version','installation_id']::text[] OR
    pg_catalog.jsonb_typeof(m.value->'connection_id')<>'string' OR
    (m.value->>'connection_id') COLLATE "C" !~ 'UUID_RE' OR
    m.value->>'connection_id'='00000000-0000-0000-0000-000000000000' OR
    pg_catalog.jsonb_typeof(m.value->'installation_id')<>'string' OR
    (m.value->>'installation_id') COLLATE "C" !~ '^[0-9a-f]{64}$' OR
    pg_catalog.jsonb_typeof(m.value->'format_version')<>'string' OR
    pg_catalog.length(m.value->>'format_version') NOT BETWEEN 1 AND 128 OR
    pg_catalog.translate(m.value->>'format_version',CONTROLS,'')<>m.value->>'format_version' OR
    (m.value->'declared_bytes'<>'null'::jsonb AND (pg_catalog.jsonb_typeof(m.value->'declared_bytes')<>'number' OR
     (m.value->>'declared_bytes') COLLATE "C" !~ '^[1-9][0-9]{0,7}$' OR
     (m.value->>'declared_bytes')::bigint>10485760))) THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid');
 END IF;
 guard:=wl_ingestion._guard_user_v1(p_digest,p_user,p_version,p_realm,p_catalog_digest);
 IF guard->>'ok' IS DISTINCT FROM 'true' THEN RETURN guard; END IF;
 tenant:=(guard#>>'{value,tenant_id}')::uuid;portfolio:=(guard#>>'{value,portfolio_id}')::uuid;
 realm:=pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(guard#>'{value,realm}')),'hex');
 SELECT * INTO st FROM wl_pg.instance_state WHERE id=1;
 request_digest:=pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(p_payload)),'hex');
 BEGIN
  result:=wl_ingestion._replay_v1(tenant,portfolio,st.incarnation,st.restore_epoch,
   (p_payload->>'operation_id')::uuid,'CREATE',request_digest);
 EXCEPTION WHEN SQLSTATE '22023' THEN
  IF SQLERRM='import_conflict' THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_operation_conflict'); END IF;
  RAISE;
 END;
 IF result IS NOT NULL THEN RETURN pg_catalog.jsonb_build_object('ok',true,'value',result); END IF;
 -- Source lifecycle rows in the declared order; the selection is pinned under them.
 PERFORM 1 FROM wl_sources.lifecycle_roots WHERE tenant_id=tenant AND portfolio_id=portfolio FOR SHARE;
 PERFORM 1 FROM wl_sources.enablements WHERE tenant_id=tenant AND portfolio_id=portfolio ORDER BY plugin_id,capability FOR SHARE;
 PERFORM 1 FROM wl_pg.connections WHERE tenant_id=tenant AND portfolio_id=portfolio ORDER BY id,version FOR SHARE;
 PERFORM 1 FROM wl_sources.connection_lifecycle WHERE tenant_id=tenant AND portfolio_id=portfolio ORDER BY id FOR SHARE;
 -- Reserve the worst-case set capacity once; instance and user storage rows come next.
 PERFORM wl_ingestion._quota_v1(tenant,portfolio,'storage',1,SET_BYTES);
 INSERT INTO wl_ingestion.roots(tenant_id,portfolio_id,accepted_generation,mapping_generation,control_generation)
  VALUES(tenant,portfolio,0,0,0) ON CONFLICT DO NOTHING;
 PERFORM 1 FROM wl_ingestion.roots WHERE tenant_id=tenant AND portfolio_id=portfolio FOR UPDATE;
 -- The same operation may have committed while this call waited.
 BEGIN
  result:=wl_ingestion._replay_v1(tenant,portfolio,st.incarnation,st.restore_epoch,
   (p_payload->>'operation_id')::uuid,'CREATE',request_digest);
 EXCEPTION WHEN SQLSTATE '22023' THEN
  IF SQLERRM='import_conflict' THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_operation_conflict'; END IF;
  RAISE;
 END;
 IF result IS NOT NULL THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='replay_after_wait'; END IF;
 n:=wl_identity._clock_timestamp_v1();
 SELECT * INTO ss FROM wl_identity.sessions WHERE token_digest=p_digest;
SESSION_RECHECK
 SELECT * INTO cs FROM wl_sources.catalog_state WHERE id=1;
 SELECT * INTO ingestion_state FROM wl_ingestion.instance_state WHERE id=1;
 catalog:=pg_catalog.convert_from(cs.bundle_bytes,'UTF8')::jsonb;
 wrappers:=pg_catalog.convert_from(ingestion_state.wrapper_catalog_bytes,'UTF8')::jsonb;
 IF pg_catalog.jsonb_typeof(wrappers)<>'array' THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='source_unavailable'; END IF;
 evidence:=pg_catalog.to_char(n AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS')||'+00:00';
 new_set:=pg_catalog.gen_random_uuid();
 INSERT INTO wl_ingestion.sets(tenant_id,portfolio_id,id,actor_user_id,creation_operation_id,request_digest,incarnation,
  restore_epoch,realm_digest,state,revision,created_at,expires_at,member_count,reserved_bytes,receipt_id,cleanup_state)
  VALUES(tenant,portfolio,new_set,tenant,(p_payload->>'operation_id')::uuid,request_digest,st.incarnation,st.restore_epoch,
   realm,'RECEIVING',1,n,n+interval '86400 seconds',pg_catalog.jsonb_array_length(p_payload->'members'),SET_BYTES,NULL,'not_needed');
 FOR pick IN SELECT value FROM pg_catalog.jsonb_array_elements(p_payload->'members') LOOP
  SELECT * INTO cl FROM wl_sources.connection_lifecycle WHERE tenant_id=tenant AND portfolio_id=portfolio
   AND id=(pick->>'connection_id')::uuid;
  em:=NULL;
  IF cl.id IS NOT NULL THEN
   SELECT * INTO em FROM wl_sources.enablements WHERE tenant_id=tenant AND portfolio_id=portfolio
    AND plugin_id=cl.plugin_id AND capability=cl.capability;
  END IF;
  SELECT c.generation INTO generation FROM wl_pg.connections c WHERE c.tenant_id=tenant AND c.portfolio_id=portfolio
   AND c.id=cl.id AND c.version=cl.connection_version;
  SELECT (a.value->>'availability_generation')::bigint INTO availability FROM pg_catalog.jsonb_array_elements(
   CASE WHEN pg_catalog.jsonb_typeof(catalog->'availability')='array' THEN catalog->'availability' ELSE '[]'::jsonb END) a(value)
   WHERE a.value->>'installation_id'=pick->>'installation_id' AND a.value->>'status'='ACTIVE' AND
    (a.value->>'availability_generation') COLLATE "C" ~ '^[0-9]{1,18}$' LIMIT 1;
  -- Exactly one reviewed profile must accept this installation and format.
  SELECT pg_catalog.count(*),(pg_catalog.array_agg(w.value))[1] INTO profiles,profile
   FROM pg_catalog.jsonb_array_elements(wrappers) w(value) WHERE pg_catalog.jsonb_typeof(w.value)='object' AND
    w.value->>'installation_id'=pick->>'installation_id' AND
    pg_catalog.jsonb_typeof(w.value->'format_versions')='array' AND w.value->'format_versions' ? (pick->>'format_version') AND
    w.value->>'projection' IN ('parser2-minimal-v1','domain1-minimal-v1') AND
    (w.value->>'profile_digest') COLLATE "C" ~ '^[0-9a-f]{64}$' AND (w.value->>'image_digest') COLLATE "C" ~ '^[0-9a-f]{64}$';
  IF cl.id IS NULL OR NOT cl.enabled OR cl.capability<>'FILE_IMPORT' OR cl.installation_id<>pick->>'installation_id' OR
   em.plugin_id IS NULL OR NOT em.enabled OR em.installation_id<>pick->>'installation_id' OR generation IS NULL OR
   availability IS NULL OR profiles<>1 THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='source_unavailable'; END IF;
  new_member:=pg_catalog.gen_random_uuid();
  context:=pg_catalog.jsonb_build_object('version',1,'job_id',pg_catalog.gen_random_uuid()::text,'member_id',new_member::text,
   'fence','1','installation_id',pick->>'installation_id','wrapper_profile_digest',profile->>'profile_digest',
   'format_version',pick->>'format_version','image_digest',profile->>'image_digest');
  IF profile->>'projection'='parser2-minimal-v1' THEN
   context:=context||pg_catalog.jsonb_build_object('payload_kind','parser_v2','parser_context',
    pg_catalog.jsonb_build_object('evidence_at',evidence,'source_reference',pg_catalog.gen_random_uuid()::text,
     'account_alias',cl.parser_source_alias,'source_timezone',NULL,'format_selection',pick->>'format_version',
     'revisions','[]'::jsonb,'scope_revisions','[]'::jsonb));
  ELSE
   context:=context||pg_catalog.jsonb_build_object('payload_kind','native_discovery_v1','provider_id',cl.provider_id,
    'evidence_reference',pg_catalog.gen_random_uuid()::text,
    'evidence_at',pg_catalog.jsonb_build_object('tag','instant','token',evidence,'zone',NULL,'fractional_digits',0),
    'namespace',pg_catalog.jsonb_build_object('tenant_id',pg_catalog.gen_random_uuid()::text,
     'portfolio_id',pg_catalog.gen_random_uuid()::text,'connection_id',pg_catalog.gen_random_uuid()::text));
  END IF;
  context_raw:=wl_ingestion._canonical_v1(context);
  INSERT INTO wl_ingestion.members(tenant_id,portfolio_id,set_id,id,ordinal,connection_id,connection_version,installation_id,
   format_version,context_digest,context_bytes,raw_digest,raw_bytes,state,error_code,stage_digest,fence,connection_generation,
   enablement_generation,availability_generation,wrapper_profile_digest,raw_deadline)
   VALUES(tenant,portfolio,new_set,new_member,position,cl.id,cl.connection_version,cl.installation_id,pick->>'format_version',
    pg_catalog.encode(pg_catalog.sha256(context_raw),'hex'),context_raw,NULL,NULL,'waiting',NULL,NULL,1,generation,
    em.generation,availability,profile->>'profile_digest',NULL);
  position:=position+1;
 END LOOP;
 SELECT SET_RESULT INTO result FROM wl_ingestion.sets x WHERE x.tenant_id=tenant AND x.portfolio_id=portfolio AND x.id=new_set;
 receipt:=pg_catalog.gen_random_uuid();
 INSERT INTO wl_ingestion.receipts(tenant_id,portfolio_id,id,incarnation,restore_epoch,operation_id,operation_kind,
  request_digest,preview_id,accepted_plan_id,plan_digest,result_bytes,created_at) VALUES(tenant,portfolio,receipt,
  st.incarnation,st.restore_epoch,(p_payload->>'operation_id')::uuid,'CREATE',request_digest,NULL,NULL,NULL,
  wl_ingestion._canonical_v1(result),n);
 INSERT INTO wl_ingestion.audit(tenant_id,portfolio_id,id,receipt_id,action,before_accepted_generation,
  after_accepted_generation,before_mapping_generation,after_mapping_generation,created_at)
  SELECT tenant,portfolio,pg_catalog.gen_random_uuid(),receipt,'CREATED',r.accepted_generation,r.accepted_generation,
   r.mapping_generation,r.mapping_generation,n FROM wl_ingestion.roots r WHERE r.tenant_id=tenant AND r.portfolio_id=portfolio;
 RETURN pg_catalog.jsonb_build_object('ok',true,'value',result);
EXCEPTION WHEN SQLSTATE '22023' THEN
 -- Every reservation and row above rolls back with this block.
 code:=SQLERRM;
 IF code='replay_after_wait' THEN
  RETURN pg_catalog.jsonb_build_object('ok',true,'value',wl_ingestion._replay_v1(tenant,portfolio,st.incarnation,
   st.restore_epoch,(p_payload->>'operation_id')::uuid,'CREATE',request_digest));
 END IF;
 IF code NOT IN ('import_invalid','import_limit','import_busy','import_operation_conflict','source_unavailable',
  'session_changed','instance_not_ready') THEN code:='import_invalid'; END IF;
 RETURN pg_catalog.jsonb_build_object('ok',false,'code',code);
WHEN unique_violation THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_operation_conflict');
WHEN data_exception THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid');
WHEN serialization_failure OR deadlock_detected OR lock_not_available OR query_canceled THEN RAISE;
WHEN OTHERS THEN RAISE EXCEPTION USING ERRCODE='XX000',MESSAGE='internal_error';
END $create$;
REVOKE ALL ON FUNCTION wl_ingestion.create_set_v1(text,uuid,bigint,jsonb,text,jsonb) FROM PUBLIC;
""".replace('SESSION_RECHECK', _identity.check_session().replace(
    "RETURN pg_catalog.jsonb_build_object('ok',false,'code','", "RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='")
    .replace("');", "';")).replace('SET_RESULT', _SET_RESULT_SQL).replace(
    'UUID_RE', _UUID_RE).replace('SET_BYTES', str(SET_RESERVATION_BYTES)).replace(
    'CONTROLS', '||'.join('pg_catalog.chr(' + str(c) + ')' for c in range(1, 32)))

# Live recheck of one member's pins captured at creation (raising, so a failed
# reserve or bind keeps no slot). Same rules as acceptance.
_MEMBER_PIN_SQL = r"""
 SELECT * INTO cl FROM wl_sources.connection_lifecycle WHERE tenant_id=tenant AND portfolio_id=portfolio AND id=mem.connection_id;
 em:=NULL;
 IF cl.id IS NOT NULL THEN
  SELECT * INTO em FROM wl_sources.enablements WHERE tenant_id=tenant AND portfolio_id=portfolio
   AND plugin_id=cl.plugin_id AND capability=cl.capability;
 END IF;
 SELECT * INTO cs FROM wl_sources.catalog_state WHERE id=1;
 SELECT * INTO ingestion_state FROM wl_ingestion.instance_state WHERE id=1;
 catalog:=pg_catalog.convert_from(cs.bundle_bytes,'UTF8')::jsonb;
 wrappers:=pg_catalog.convert_from(ingestion_state.wrapper_catalog_bytes,'UTF8')::jsonb;
 IF cl.id IS NULL OR NOT cl.enabled OR em.plugin_id IS NULL OR NOT em.enabled OR NOT EXISTS(
   SELECT 1 FROM pg_catalog.jsonb_array_elements(CASE WHEN pg_catalog.jsonb_typeof(catalog->'availability')='array'
    THEN catalog->'availability' ELSE '[]'::jsonb END) a(value)
   WHERE a.value->>'installation_id'=mem.installation_id AND a.value->>'status'='ACTIVE') OR
  NOT EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(CASE WHEN pg_catalog.jsonb_typeof(wrappers)='array'
    THEN wrappers ELSE '[]'::jsonb END) w(value) WHERE pg_catalog.jsonb_typeof(w.value)='object' AND
   w.value->>'profile_digest'=mem.wrapper_profile_digest AND w.value->>'installation_id'=mem.installation_id) THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='source_unavailable'; END IF;
 SELECT c.generation INTO generation FROM wl_pg.connections c WHERE c.tenant_id=tenant AND c.portfolio_id=portfolio
  AND c.id=mem.connection_id AND c.version=mem.connection_version;
 IF cl.connection_version<>mem.connection_version OR cl.installation_id<>mem.installation_id OR
  em.installation_id<>mem.installation_id OR em.generation<>mem.enablement_generation OR
  generation IS DISTINCT FROM mem.connection_generation OR NOT EXISTS(
   SELECT 1 FROM pg_catalog.jsonb_array_elements(catalog->'availability') a(value)
   WHERE a.value->>'installation_id'=mem.installation_id AND a.value->>'status'='ACTIVE' AND
    a.value->>'availability_generation'=mem.availability_generation::text) THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale'; END IF;
"""

# reserve opens one raw attempt; bind fixes its exact bytes once. Neither ever
# receives raw content: only a hash, a length and the API's handoff-token digest.
RESERVE_DDL = r"""
CREATE FUNCTION wl_ingestion.reserve_member_v1(p_digest text,p_user uuid,p_version bigint,p_realm jsonb,
 p_catalog_digest text,p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $reserve$
DECLARE guard jsonb;st wl_pg.instance_state%ROWTYPE;ss wl_identity.sessions%ROWTYPE;
 cs wl_sources.catalog_state%ROWTYPE;ingestion_state wl_ingestion.instance_state%ROWTYPE;
 cl wl_sources.connection_lifecycle%ROWTYPE;em wl_sources.enablements%ROWTYPE;
 selected wl_ingestion.sets%ROWTYPE;mem wl_ingestion.members%ROWTYPE;offer wl_ingestion.leases%ROWTYPE;
 tenant uuid;portfolio uuid;n timestamptz;worker uuid;workers_enabled integer;next_fence bigint;
 attempts bigint;lease uuid;code text;catalog jsonb;wrappers jsonb;generation bigint;deadline timestamptz;
 offer_until timestamptz;bind boolean;
BEGIN
 IF pg_catalog.jsonb_typeof(p_payload) IS DISTINCT FROM 'object' OR pg_catalog.jsonb_typeof(p_payload->'action')<>'string' OR
  p_payload->>'action' NOT IN ('reserve','bind') THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid'); END IF;
 bind:=p_payload->>'action'='bind';
 IF ARRAY(SELECT pg_catalog.jsonb_object_keys(p_payload) ORDER BY 1)<>(CASE WHEN bind THEN
   ARRAY['action','fence','handoff_token_digest','member_id','raw_bytes','raw_sha256','set_id']::text[] ELSE
   ARRAY['action','expected_set_revision','member_id','set_id']::text[] END) OR
  pg_catalog.jsonb_typeof(p_payload->'set_id')<>'string' OR (p_payload->>'set_id') COLLATE "C" !~ 'UUID_RE' OR
  pg_catalog.jsonb_typeof(p_payload->'member_id')<>'string' OR (p_payload->>'member_id') COLLATE "C" !~ 'UUID_RE' OR
  p_payload->>'set_id'='00000000-0000-0000-0000-000000000000' OR
  p_payload->>'member_id'='00000000-0000-0000-0000-000000000000' OR
  (NOT bind AND (pg_catalog.jsonb_typeof(p_payload->'expected_set_revision')<>'string' OR
   (p_payload->>'expected_set_revision') COLLATE "C" !~ '^[1-9][0-9]{0,17}$')) OR
  (bind AND (pg_catalog.jsonb_typeof(p_payload->'fence')<>'string' OR (p_payload->>'fence') COLLATE "C" !~ '^[1-9][0-9]{0,17}$' OR
   pg_catalog.jsonb_typeof(p_payload->'raw_sha256')<>'string' OR (p_payload->>'raw_sha256') COLLATE "C" !~ '^[0-9a-f]{64}$' OR
   pg_catalog.jsonb_typeof(p_payload->'handoff_token_digest')<>'string' OR
   (p_payload->>'handoff_token_digest') COLLATE "C" !~ '^[0-9a-f]{64}$' OR
   pg_catalog.jsonb_typeof(p_payload->'raw_bytes')<>'number' OR (p_payload->>'raw_bytes') COLLATE "C" !~ '^[1-9][0-9]{0,7}$' OR
   (p_payload->>'raw_bytes')::bigint>10485760)) THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid');
 END IF;
 guard:=wl_ingestion._guard_user_v1(p_digest,p_user,p_version,p_realm,p_catalog_digest);
 IF guard->>'ok' IS DISTINCT FROM 'true' THEN RETURN guard; END IF;
 tenant:=(guard#>>'{value,tenant_id}')::uuid;portfolio:=(guard#>>'{value,portfolio_id}')::uuid;
 SELECT * INTO st FROM wl_pg.instance_state WHERE id=1;
 PERFORM 1 FROM wl_sources.lifecycle_roots WHERE tenant_id=tenant AND portfolio_id=portfolio FOR SHARE;
 PERFORM 1 FROM wl_sources.enablements WHERE tenant_id=tenant AND portfolio_id=portfolio ORDER BY plugin_id,capability FOR SHARE;
 PERFORM 1 FROM wl_pg.connections WHERE tenant_id=tenant AND portfolio_id=portfolio ORDER BY id,version FOR SHARE;
 PERFORM 1 FROM wl_sources.connection_lifecycle WHERE tenant_id=tenant AND portfolio_id=portfolio ORDER BY id FOR SHARE;
 -- A new attempt counts against the raw rate and takes one shared concurrent slot.
 IF NOT bind THEN PERFORM wl_ingestion._quota_v1(tenant,portfolio,'raw',1,0); END IF;
 PERFORM 1 FROM wl_ingestion.roots WHERE tenant_id=tenant AND portfolio_id=portfolio FOR UPDATE;
 SELECT * INTO selected FROM wl_ingestion.sets WHERE tenant_id=tenant AND portfolio_id=portfolio
  AND id=(p_payload->>'set_id')::uuid FOR UPDATE;
 PERFORM 1 FROM wl_ingestion.members WHERE tenant_id=tenant AND portfolio_id=portfolio AND set_id=selected.id ORDER BY id FOR UPDATE;
 PERFORM 1 FROM wl_ingestion.leases WHERE tenant_id=tenant AND portfolio_id=portfolio AND set_id=selected.id ORDER BY id FOR UPDATE;
 n:=wl_identity._clock_timestamp_v1();
 SELECT * INTO ss FROM wl_identity.sessions WHERE token_digest=p_digest;
SESSION_RECHECK
 IF selected.id IS NULL THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='not_found'; END IF;
 SELECT * INTO mem FROM wl_ingestion.members WHERE tenant_id=tenant AND portfolio_id=portfolio AND set_id=selected.id
  AND id=(p_payload->>'member_id')::uuid;
 IF mem.id IS NULL THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='not_found'; END IF;
 IF selected.state='EXPIRED' OR (selected.state NOT IN ('COMMITTED','REJECTED','CANCELLED') AND n>=selected.expires_at) THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_expired'; END IF;
 IF selected.state<>'RECEIVING' OR (NOT bind AND selected.revision<>(p_payload->>'expected_set_revision')::bigint) THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale'; END IF;
MEMBER_PINS
 IF NOT bind THEN
  -- One live attempt per member; a re-upload starts a new fence with empty raw fields.
  IF mem.state NOT IN ('waiting','reupload_required') THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  SELECT pg_catalog.count(*),(pg_catalog.array_agg(w.id))[1] INTO workers_enabled,worker FROM wl_ingestion.workers w WHERE w.enabled;
  IF workers_enabled<>1 THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_runner_unavailable'; END IF;
  next_fence:=mem.fence+CASE WHEN mem.state='reupload_required' THEN 1 ELSE 0 END;
  deadline:=n+interval '120 seconds';
  UPDATE wl_ingestion.members SET state='receiving',fence=next_fence,raw_deadline=deadline,
   error_code=CASE WHEN next_fence<>fence THEN NULL ELSE error_code END,
   raw_digest=CASE WHEN next_fence<>fence THEN NULL ELSE raw_digest END,
   raw_bytes=CASE WHEN next_fence<>fence THEN NULL ELSE raw_bytes END
   WHERE tenant_id=tenant AND portfolio_id=portfolio AND set_id=selected.id AND id=mem.id;
  SELECT pg_catalog.count(*) INTO attempts FROM wl_ingestion.leases l WHERE l.tenant_id=tenant AND l.portfolio_id=portfolio
   AND l.set_id=selected.id AND l.member_id=mem.id AND l.work_kind='normalize';
  lease:=pg_catalog.gen_random_uuid();
  -- Unbound offer: no worker can claim it until bind adds the token digest.
  INSERT INTO wl_ingestion.leases(tenant_id,portfolio_id,id,set_id,member_id,work_kind,attempt,fence,worker_id,token_digest,
   session_digest,credential_version,incarnation,restore_epoch,created_at,expires_at,state,claim_request_id,
   claim_request_digest,last_request_id,last_request_digest,last_result_bytes)
   VALUES(tenant,portfolio,lease,selected.id,mem.id,'normalize',attempts+1,next_fence,worker,NULL,p_digest,
    ss.credential_version,st.incarnation,st.restore_epoch,n,n+interval '30 seconds','offered',NULL,NULL,NULL,NULL,NULL);
  RETURN pg_catalog.jsonb_build_object('ok',true,'value',pg_catalog.jsonb_build_object('action','reserve',
   'set_id',selected.id::text,'member_id',mem.id::text,'lease_id',lease::text,'fence',next_fence::text,
   'raw_deadline',INSTANT_DEADLINE,'offer_expires_at',INSTANT_OFFER));
 END IF;
 -- bind: the exact attempt reserved by this same session, before its deadline.
 IF mem.state<>'receiving' OR mem.fence::text<>p_payload->>'fence' THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale'; END IF;
 IF mem.raw_deadline IS NULL OR n>=mem.raw_deadline THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_reupload_required'; END IF;
 IF mem.raw_digest IS NOT NULL THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
 SELECT * INTO offer FROM wl_ingestion.leases l WHERE l.tenant_id=tenant AND l.portfolio_id=portfolio AND l.set_id=selected.id
  AND l.member_id=mem.id AND l.work_kind='normalize' AND l.fence=mem.fence AND l.state='offered' AND l.token_digest IS NULL;
 IF offer.id IS NULL OR offer.session_digest<>p_digest OR n>=offer.expires_at OR
  NOT EXISTS(SELECT 1 FROM wl_ingestion.workers w WHERE w.id=offer.worker_id AND w.enabled) THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_reupload_required'; END IF;
 offer_until:=LEAST(n+interval '60 seconds',mem.raw_deadline);
 UPDATE wl_ingestion.members SET raw_digest=p_payload->>'raw_sha256',raw_bytes=(p_payload->>'raw_bytes')::bigint
  WHERE tenant_id=tenant AND portfolio_id=portfolio AND set_id=selected.id AND id=mem.id;
 UPDATE wl_ingestion.leases SET token_digest=p_payload->>'handoff_token_digest',expires_at=offer_until
  WHERE tenant_id=tenant AND portfolio_id=portfolio AND id=offer.id;
 -- Handoff metadata for the trusted API only; it adds its own plaintext token.
 RETURN pg_catalog.jsonb_build_object('ok',true,'value',pg_catalog.jsonb_build_object('version',1,
  'job_id',pg_catalog.convert_from(mem.context_bytes,'UTF8')::jsonb->>'job_id','set_id',selected.id::text,
  'member_id',mem.id::text,'fence',mem.fence::text,'raw_sha256',p_payload->>'raw_sha256',
  'raw_bytes',(p_payload->>'raw_bytes')::bigint,'context_sha256',mem.context_digest,
  'context_bytes',pg_catalog.octet_length(mem.context_bytes),'realm_digest',selected.realm_digest,
  'expires_at',INSTANT_UNTIL,'raw_deadline',INSTANT_RAW));
EXCEPTION WHEN SQLSTATE '22023' THEN
 -- Every reservation and change above rolls back with this block.
 code:=SQLERRM;
 IF code NOT IN ('import_invalid','import_busy','import_conflict','import_stale','import_expired','import_reupload_required',
  'import_runner_unavailable','source_unavailable','not_found','session_changed','instance_not_ready') THEN
  code:='import_invalid'; END IF;
 RETURN pg_catalog.jsonb_build_object('ok',false,'code',code);
WHEN data_exception THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid');
WHEN serialization_failure OR deadlock_detected OR lock_not_available OR query_canceled THEN RAISE;
WHEN OTHERS THEN RAISE EXCEPTION USING ERRCODE='XX000',MESSAGE='internal_error';
END $reserve$;
REVOKE ALL ON FUNCTION wl_ingestion.reserve_member_v1(text,uuid,bigint,jsonb,text,jsonb) FROM PUBLIC;
""".replace('MEMBER_PINS', _MEMBER_PIN_SQL).replace('SESSION_RECHECK', _identity.check_session().replace(
    "RETURN pg_catalog.jsonb_build_object('ok',false,'code','", "RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='")
    .replace("');", "';")).replace('UUID_RE', _UUID_RE).replace('INSTANT_DEADLINE', _instant_sql('deadline')).replace(
    'INSTANT_OFFER', _instant_sql("n+interval '30 seconds'")).replace('INSTANT_UNTIL', _instant_sql('offer_until')).replace(
    'INSTANT_RAW', _instant_sql('mem.raw_deadline'))


# A whole-second Instant; lease deadlines are truncated to seconds when set.
def _second_sql(expression):
    return ("pg_catalog.jsonb_build_object('tag','instant','token',pg_catalog.to_char((" + expression +
            ") AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS')||'+00:00','zone',null,'fractional_digits',0)")


# The set's pins as a Plan's pinned_sources entries, in member-ID order (the
# order acceptance uses), hashed canonically. The worker can compare it with the
# pins in a later Plan without reading any member row.
_FINGERPRINT_SQL = ("pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(COALESCE((SELECT "
    "pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('member_id',p.id::text,'connection_id',p.connection_id::text,"
    "'connection_version',p.connection_version,'connection_generation',p.connection_generation::text,"
    "'enablement_generation',p.enablement_generation::text,'availability_generation',p.availability_generation::text,"
    "'installation_id',p.installation_id,'wrapper_profile_digest',p.wrapper_profile_digest,'format_version',"
    "p.format_version,'context_digest',p.context_digest) ORDER BY p.id::text COLLATE \"C\") FROM wl_ingestion.members p "
    "WHERE p.tenant_id=tenant AND p.portfolio_id=portfolio AND p.set_id=selected.id),'[]'::jsonb))),'hex')")


def _raising(fragment):
    return fragment.replace("RETURN pg_catalog.jsonb_build_object('ok',false,'code','",
                            "RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='").replace("');", "';")


# r7: normalization keeps the originating user's live authority. The session
# that reserved the attempt, its user and credential version must still hold.
_ORIGIN_SQL = (r"""
 SELECT * INTO st FROM wl_pg.instance_state WHERE id=1;
 SELECT * INTO ss FROM wl_identity.sessions WHERE token_digest=held.session_digest;
 SELECT * INTO u FROM wl_identity.users WHERE id=ss.user_id;
""" + _raising(_identity.check_user(code='session_changed') + _identity.check_session()) + r"""
 IF ss.user_id<>selected.actor_user_id OR ss.credential_version<>held.credential_version OR
  u.credential_version<>ss.credential_version THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='session_changed'; END IF;
""")


def _finish_codes():
    """Member error codes a worker may record: exactly the public MemberResult enum."""
    from ..ingestion.contracts import definition
    return definition('MemberResult', 'wire')['properties']['error_code']['anyOf'][0]['enum']


def _lease_ddl(name, mode):
    """Render a normalize-lease worker function: claim, renew, admit or finish.

    All start with the worker guard, take scope only from the set row, lock in
    the same order as reserve and recheck the member's creation-time pins. Prepare
    and cleanup leases are refused until their claim functions exist.
    """
    claim, admit, finish = mode == 'claim', mode == 'admit', mode == 'finish'
    extra = {'claim': ['context_digest', 'raw_digest'], 'renew': [],
             'admit': ['discovery_digest', 'payload_bytes', 'raw_digest', 'stage_digest'],
             'finish': ['cleanup_proofs', 'error_code', 'outcome']}[mode]
    keys = ['credential_epoch', 'fence', 'job_id', 'member_id', 'realm_digest', 'request_id', 'set_id', 'version',
            'work_kind'] + extra
    hashes = [k for k in extra if k in ('context_digest', 'raw_digest', 'discovery_digest', 'stage_digest')]
    shape = ''.join(
        " OR pg_catalog.jsonb_typeof(p_request->'" + k + "')<>'string' OR (p_request->>'" + k + "') COLLATE \"C\" !~ 'UUID_RE'"
        " OR p_request->>'" + k + "'='00000000-0000-0000-0000-000000000000'" for k in ('job_id', 'set_id', 'member_id', 'request_id'))
    shape += ''.join(" OR pg_catalog.jsonb_typeof(p_request->'" + k + "')<>'string' OR (p_request->>'" + k +
                     "') COLLATE \"C\" !~ '^[0-9a-f]{64}$'" for k in hashes)
    if admit:
        shape += (" OR pg_catalog.jsonb_typeof(p_request->'payload_bytes')<>'number' OR (p_request->>'payload_bytes')"
                  " COLLATE \"C\" !~ '^[1-9][0-9]{0,6}$' OR (p_request->>'payload_bytes')::bigint>4194304")
    if finish:
        codes = ','.join("'" + c + "'" for c in _finish_codes())
        shape += r"""
  OR pg_catalog.jsonb_typeof(p_request->'outcome')<>'string' OR
  p_request->>'outcome' NOT IN ('stage_admitted','reupload_required','rejected') OR
  (p_request->>'outcome'='stage_admitted' AND p_request->'error_code'<>'null'::jsonb) OR
  (p_request->>'outcome'<>'stage_admitted' AND (pg_catalog.jsonb_typeof(p_request->'error_code')<>'string' OR
   p_request->>'error_code' NOT IN (CODES))) OR
  pg_catalog.jsonb_typeof(p_request->'cleanup_proofs')<>'array' OR pg_catalog.jsonb_array_length(p_request->'cleanup_proofs')>3 OR
  EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(p_request->'cleanup_proofs') q(value) WHERE
   pg_catalog.jsonb_typeof(q.value)<>'object' OR ARRAY(SELECT pg_catalog.jsonb_object_keys(q.value) ORDER BY 1)<>
    ARRAY['checked_at','fence','job_id','launcher_instance_id','proof_digest','state']::text[] OR
   q.value->'job_id' IS DISTINCT FROM p_request->'job_id' OR q.value->'fence' IS DISTINCT FROM p_request->'fence' OR
   pg_catalog.jsonb_typeof(q.value->'state')<>'string' OR q.value->>'state' NOT IN ('absent','not_created','pending','failed') OR
   pg_catalog.jsonb_typeof(q.value->'launcher_instance_id')<>'string' OR
   (q.value->>'launcher_instance_id') COLLATE "C" !~ 'UUID_RE' OR
   pg_catalog.jsonb_typeof(q.value->'proof_digest')<>'string' OR (q.value->>'proof_digest') COLLATE "C" !~ '^[0-9a-f]{64}$' OR
   pg_catalog.jsonb_typeof(q.value->'checked_at')<>'object' OR
   ARRAY(SELECT pg_catalog.jsonb_object_keys(q.value->'checked_at') ORDER BY 1)<>
    ARRAY['fractional_digits','tag','token','zone']::text[] OR q.value#>'{checked_at,tag}' IS DISTINCT FROM '"instant"'::jsonb OR
   pg_catalog.jsonb_typeof(q.value#>'{checked_at,token}')<>'string' OR q.value#>'{checked_at,zone}'<>'null'::jsonb OR
   (q.value#>>'{checked_at,fractional_digits}') COLLATE "C" !~ '^[0-9]$')""".replace('CODES', codes)
        step = r"""
 IF held.state<>'active' OR mem.state<>'normalizing' THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale'; END IF;
 IF p_request->>'outcome'='stage_admitted' THEN
  -- Admission needs the user's authority and source pins still valid and exactly
  -- this attempt's stage; a re-upload or rejection needs neither.
ORIGIN
MEMBER_PINS
  SELECT pg_catalog.count(*),(pg_catalog.array_agg(g.digest))[1] INTO staged_count,staged FROM wl_ingestion.stages g
   WHERE g.tenant_id=tenant AND g.portfolio_id=portfolio AND g.set_id=selected.id AND g.member_id=mem.id AND
    g.created_at>=held.created_at;
  IF staged_count<>1 THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid'; END IF;
  ack:=FINISH_ACK_ADMITTED;
 ELSIF p_request->>'outcome'='reupload_required' THEN ack:=FINISH_ACK_REUPLOAD;
 ELSE ack:=FINISH_ACK_REJECTED; END IF;
 -- The lease finishes first: a terminal set no longer accepts lease changes.
 UPDATE wl_ingestion.leases SET state='finished',last_request_id=(p_request->>'request_id')::uuid,
  last_request_digest=request_digest,last_result_bytes=wl_ingestion._canonical_v1(ack)
  WHERE tenant_id=tenant AND portfolio_id=portfolio AND id=held.id;
 IF p_request->>'outcome'='stage_admitted' THEN
  UPDATE wl_ingestion.members SET state='admitted',stage_digest=staged
   WHERE tenant_id=tenant AND portfolio_id=portfolio AND set_id=selected.id AND id=mem.id;
  -- The last admitted member hands the set to preparation.
  IF NOT EXISTS(SELECT 1 FROM wl_ingestion.members m WHERE m.tenant_id=tenant AND m.portfolio_id=portfolio AND
    m.set_id=selected.id AND m.state<>'admitted') THEN
   UPDATE wl_ingestion.sets SET state='NORMALIZING' WHERE tenant_id=tenant AND portfolio_id=portfolio AND id=selected.id;
  END IF;
 ELSIF p_request->>'outcome'='reupload_required' THEN
  UPDATE wl_ingestion.members SET state='reupload_required',error_code=p_request->>'error_code'
   WHERE tenant_id=tenant AND portfolio_id=portfolio AND set_id=selected.id AND id=mem.id;
 ELSE
  -- Owner decision: one rejected file rejects the set; a new set starts over.
  UPDATE wl_ingestion.sets SET state='REJECTED',cleanup_state='pending'
   WHERE tenant_id=tenant AND portfolio_id=portfolio AND id=selected.id;
  UPDATE wl_ingestion.members SET state='rejected',
   error_code=CASE WHEN id=mem.id THEN p_request->>'error_code' ELSE error_code END
   WHERE tenant_id=tenant AND portfolio_id=portfolio AND set_id=selected.id;
  UPDATE wl_ingestion.leases SET state='cancelled' WHERE tenant_id=tenant AND portfolio_id=portfolio AND
   set_id=selected.id AND state IN ('offered','active');
 END IF;
 -- Owner decision: the raw slot returns only with proven child cleanup;
 -- otherwise it stays held until a later cleanup call proves it.
 IF cleaned THEN PERFORM wl_ingestion._quota_v1(tenant,portfolio,'raw',-1,0); END IF;
 RETURN pg_catalog.jsonb_build_object('ok',true,'value',ack);"""
        replay = r"""
 -- A lost acknowledgement: the finished lease returns its exact stored result.
 IF held.state='finished' THEN
  IF held.last_request_id IS DISTINCT FROM (p_request->>'request_id')::uuid OR
   held.last_request_digest IS DISTINCT FROM request_digest THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale'; END IF;
  RETURN pg_catalog.jsonb_build_object('ok',true,'value',pg_catalog.convert_from(held.last_result_bytes,'UTF8')::jsonb);
 END IF;"""
    elif admit:
        step = r"""
 IF held.state<>'active' OR mem.state<>'normalizing' OR mem.raw_digest IS DISTINCT FROM p_request->>'raw_digest' THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale'; END IF;
 IF pg_catalog.octet_length(p_bytes)<>(p_request->>'payload_bytes')::bigint OR
  pg_catalog.encode(pg_catalog.sha256(p_bytes),'hex')<>p_request->>'stage_digest' THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid'; END IF;
 -- A proven identical stage is never parsed or stored twice.
 IF EXISTS(SELECT 1 FROM wl_ingestion.stages g WHERE g.tenant_id=tenant AND g.portfolio_id=portfolio AND
   g.set_id=selected.id AND g.member_id=mem.id AND g.digest=p_request->>'stage_digest') THEN
  RETURN pg_catalog.jsonb_build_object('ok',true,'value',STAGE_ACK_AGAIN);
 END IF;
 -- One stage per raw attempt: any stage stored since this attempt's offer.
 IF EXISTS(SELECT 1 FROM wl_ingestion.stages g WHERE g.tenant_id=tenant AND g.portfolio_id=portfolio AND
   g.set_id=selected.id AND g.member_id=mem.id AND g.created_at>=held.created_at) THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
 evidence:=wl_ingestion._validate_minimal_v1(p_bytes);
 -- The evidence must describe exactly this attempt's bytes, context and pins.
 context:=pg_catalog.convert_from(mem.context_bytes,'UTF8')::jsonb;
 IF evidence->'provenance'->>'raw_sha256' IS DISTINCT FROM mem.raw_digest OR
  evidence->'provenance'->>'discovery_sha256' IS DISTINCT FROM p_request->>'discovery_digest' OR
  evidence->'provenance'->>'installation_id' IS DISTINCT FROM mem.installation_id OR
  evidence->'provenance'->>'wrapper_profile_digest' IS DISTINCT FROM mem.wrapper_profile_digest OR
  evidence->'provenance'->>'format_selection' IS DISTINCT FROM mem.format_version OR
  evidence->'provenance'->>'image_digest' IS DISTINCT FROM context->>'image_digest' OR
  -- CASE stays parenthesised: PL/pgSQL ends an IF condition at a bare THEN.
  evidence->'provenance'->'evidence_reference' IS DISTINCT FROM (CASE context->>'payload_kind'
   WHEN 'parser_v2' THEN context#>'{parser_context,source_reference}' ELSE context->'evidence_reference' END) OR
  evidence->'provenance'->'evidence_at' IS DISTINCT FROM (CASE context->>'payload_kind'
   WHEN 'parser_v2' THEN pg_catalog.jsonb_build_object('tag','instant','token',context#>'{parser_context,evidence_at}',
    'zone',NULL,'fractional_digits',0) ELSE context->'evidence_at' END) OR
  evidence->'provenance'->'parser_api' IS DISTINCT FROM (CASE context->>'payload_kind'
   WHEN 'parser_v2' THEN '2'::jsonb ELSE 'null'::jsonb END) THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid'; END IF;
 -- Retained transient bytes stay within the set's fixed reservation.
 IF HELD_BYTES+pg_catalog.octet_length(p_bytes)>selected.reserved_bytes THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_limit'; END IF;
 INSERT INTO wl_ingestion.stages(tenant_id,portfolio_id,set_id,member_id,digest,codec,minimal_bytes,created_at,purge_at)
  VALUES(tenant,portfolio,selected.id,mem.id,p_request->>'stage_digest','minimal-evidence-v1',p_bytes,n,selected.expires_at);
 RETURN pg_catalog.jsonb_build_object('ok',true,'value',STAGE_ACK_NEW);"""
    elif claim:
        step = r"""
 IF held.state='active' THEN
  -- A lost acknowledgement: only the same claim request is recognised.
  IF held.claim_request_id IS DISTINCT FROM (p_request->>'request_id')::uuid OR
   held.claim_request_digest IS DISTINCT FROM request_digest THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  IF mem.state<>'normalizing' THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale'; END IF;
  RETURN pg_catalog.jsonb_build_object('ok',true,'value',ACK_HELD);
 END IF;
 -- The bound offer: exact raw bytes and child context from reserve/bind.
 IF mem.state<>'receiving' OR mem.raw_digest IS DISTINCT FROM p_request->>'raw_digest' OR
  mem.context_digest<>p_request->>'context_digest' THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale'; END IF;
 UPDATE wl_ingestion.members SET state='normalizing'
  WHERE tenant_id=tenant AND portfolio_id=portfolio AND set_id=selected.id AND id=mem.id;
 UPDATE wl_ingestion.leases SET state='active',claim_request_id=(p_request->>'request_id')::uuid,
  claim_request_digest=request_digest,expires_at=until WHERE tenant_id=tenant AND portfolio_id=portfolio AND id=held.id;
 RETURN pg_catalog.jsonb_build_object('ok',true,'value',ACK_CLAIMED);"""
    else:
        step = r"""
 IF held.state<>'active' OR mem.state<>'normalizing' THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale'; END IF;
 -- A lost acknowledgement: the last request gets its exact stored result.
 IF held.last_request_id=(p_request->>'request_id')::uuid THEN
  IF held.last_request_digest IS DISTINCT FROM request_digest THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict'; END IF;
  RETURN pg_catalog.jsonb_build_object('ok',true,'value',pg_catalog.convert_from(held.last_result_bytes,'UTF8')::jsonb);
 END IF;
 -- Never shorten a lease; the trigger keeps it within 60 seconds of now.
 until:=GREATEST(until,held.expires_at);
 ack:=ACK_RENEWED;
 UPDATE wl_ingestion.leases SET expires_at=until,last_request_id=(p_request->>'request_id')::uuid,
  last_request_digest=request_digest,last_result_bytes=wl_ingestion._canonical_v1(ack)
  WHERE tenant_id=tenant AND portfolio_id=portfolio AND id=held.id;
 RETURN pg_catalog.jsonb_build_object('ok',true,'value',ack);"""

    def ack(outcome, expiry):
        return ("pg_catalog.jsonb_build_object('version',1,'job_id',p_request->>'job_id','set_id',selected.id::text,"
                "'member_id',mem.id::text,'work_kind','normalize','fence',held.fence::text,'credential_epoch',"
                "guard#>>'{value,credential_epoch}','expires_at'," + _second_sql(expiry) + ",'outcome','" + outcome +
                "','source_fingerprint'," + _FINGERPRINT_SQL + ")")
    def finish_ack(state):
        return ("pg_catalog.jsonb_build_object('version',1,'job_id',p_request->>'job_id','fence',held.fence::text,"
                "'member_id',mem.id::text,'state','" + state + "','cleanup_complete',cleaned)")

    def stage_ack(outcome):
        return ("pg_catalog.jsonb_build_object('version',1,'job_id',p_request->>'job_id','fence',held.fence::text,"
                "'member_id',mem.id::text,'stage_digest',p_request->>'stage_digest','outcome','" + outcome + "')")
    step = (step.replace('FINISH_ACK_ADMITTED', finish_ack('admitted')).replace('FINISH_ACK_REUPLOAD',
            finish_ack('reupload_required')).replace('FINISH_ACK_REJECTED', finish_ack('rejected'))
            .replace('STAGE_ACK_AGAIN', stage_ack('already_admitted')).replace('STAGE_ACK_NEW', stage_ack('admitted'))
            .replace('HELD_BYTES', _HELD_BYTES_SQL).replace('ACK_HELD', ack('already_claimed', 'held.expires_at'))
            .replace('ACK_CLAIMED', ack('claimed', 'until')).replace('ACK_RENEWED', ack('renewed', 'until')))
    return (r"""
CREATE FUNCTION wl_ingestion.NAME(p_worker uuid,p_token text,p_request jsonb,p_bytes bytea) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $lease$
DECLARE guard jsonb;cs wl_sources.catalog_state%ROWTYPE;ingestion_state wl_ingestion.instance_state%ROWTYPE;
 cl wl_sources.connection_lifecycle%ROWTYPE;em wl_sources.enablements%ROWTYPE;
 selected wl_ingestion.sets%ROWTYPE;mem wl_ingestion.members%ROWTYPE;held wl_ingestion.leases%ROWTYPE;
 tenant uuid;portfolio uuid;scopes integer;n timestamptz;until timestamptz;code text;catalog jsonb;wrappers jsonb;
 generation bigint;request_digest text;ack jsonb;evidence jsonb;context jsonb;cleaned boolean;staged text;
 staged_count integer;st wl_pg.instance_state%ROWTYPE;ss wl_identity.sessions%ROWTYPE;u wl_identity.users%ROWTYPE;
BEGIN
 -- Only stage admission carries bytes; only normalize leases exist so far.
 IF (p_bytes IS NULL)=BYTES_EXPECTED OR pg_catalog.jsonb_typeof(p_request) IS DISTINCT FROM 'object' OR
  ARRAY(SELECT pg_catalog.jsonb_object_keys(p_request) ORDER BY 1)<>ARRAY[KEYS]::text[] OR
  p_request->'version' IS DISTINCT FROM '1'::jsonb OR p_request->'work_kind' IS DISTINCT FROM '"normalize"'::jsonb OR
  pg_catalog.jsonb_typeof(p_request->'fence')<>'string' OR (p_request->>'fence') COLLATE "C" !~ '^[1-9][0-9]{0,17}$'SHAPE THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid');
 END IF;
 guard:=wl_ingestion._guard_worker_v1(p_worker,p_token,p_request);
 IF guard->>'ok' IS DISTINCT FROM 'true' THEN RETURN guard; END IF;
 request_digest:=pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(p_request)),'hex');
CLEANED
 -- Scope comes from the stored set, never from the worker.
 SELECT pg_catalog.count(*),(pg_catalog.array_agg(x.tenant_id))[1],(pg_catalog.array_agg(x.portfolio_id))[1]
  INTO scopes,tenant,portfolio FROM wl_ingestion.sets x WHERE x.id=(p_request->>'set_id')::uuid;
 IF scopes<>1 THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','not_found'); END IF;
 PERFORM 1 FROM wl_sources.lifecycle_roots WHERE tenant_id=tenant AND portfolio_id=portfolio FOR SHARE;
 PERFORM 1 FROM wl_sources.enablements WHERE tenant_id=tenant AND portfolio_id=portfolio ORDER BY plugin_id,capability FOR SHARE;
 PERFORM 1 FROM wl_pg.connections WHERE tenant_id=tenant AND portfolio_id=portfolio ORDER BY id,version FOR SHARE;
 PERFORM 1 FROM wl_sources.connection_lifecycle WHERE tenant_id=tenant AND portfolio_id=portfolio ORDER BY id FOR SHARE;
QUOTA_LOCKS
 PERFORM 1 FROM wl_ingestion.roots WHERE tenant_id=tenant AND portfolio_id=portfolio FOR UPDATE;
 SELECT * INTO selected FROM wl_ingestion.sets WHERE tenant_id=tenant AND portfolio_id=portfolio
  AND id=(p_request->>'set_id')::uuid FOR UPDATE;
 PERFORM 1 FROM wl_ingestion.members WHERE tenant_id=tenant AND portfolio_id=portfolio AND set_id=selected.id ORDER BY id FOR UPDATE;
 PERFORM 1 FROM wl_ingestion.leases WHERE tenant_id=tenant AND portfolio_id=portfolio AND set_id=selected.id ORDER BY id FOR UPDATE;
 n:=wl_identity._clock_timestamp_v1();
 SELECT * INTO mem FROM wl_ingestion.members WHERE tenant_id=tenant AND portfolio_id=portfolio AND set_id=selected.id
  AND id=(p_request->>'member_id')::uuid;
 IF mem.id IS NULL THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='not_found'; END IF;
 -- The newest normalize lease at the requested fence.
 SELECT * INTO held FROM wl_ingestion.leases l WHERE l.tenant_id=tenant AND l.portfolio_id=portfolio AND l.set_id=selected.id
  AND l.member_id=mem.id AND l.work_kind='normalize' AND l.fence=(p_request->>'fence')::bigint AND l.state IN (LIVE_STATES)
  ORDER BY l.attempt DESC LIMIT 1;
 IF held.id IS NULL THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale'; END IF;
 -- Only the worker the lease names, holding the API's handoff token.
 IF held.worker_id<>p_worker OR held.token_digest IS NULL OR held.token_digest<>guard#>>'{value,token_digest}' THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='authentication_required'; END IF;
REPLAY
 IF selected.state='EXPIRED' OR (selected.state NOT IN ('COMMITTED','REJECTED','CANCELLED') AND n>=selected.expires_at) THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_expired'; END IF;
 IF selected.state<>'RECEIVING' OR n>=held.expires_at OR mem.fence<>held.fence OR mem.context_bytes IS NULL OR
  pg_catalog.convert_from(mem.context_bytes,'UTF8')::jsonb->>'job_id' IS DISTINCT FROM p_request->>'job_id' THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_stale'; END IF;
SESSION_PINS
 -- r7: the 120s raw deadline dominates every phase; leases never extend it.
 IF mem.raw_deadline IS NULL OR n>=pg_catalog.date_trunc('second',mem.raw_deadline) THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_reupload_required'; END IF;
 until:=LEAST(pg_catalog.date_trunc('second',n+interval '30 seconds'),pg_catalog.date_trunc('second',selected.expires_at),
  pg_catalog.date_trunc('second',mem.raw_deadline));
 IF until<=n THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_expired'; END IF;
STEP
EXCEPTION WHEN SQLSTATE '22023' THEN
 -- Every change above rolls back with this block.
 code:=SQLERRM;
 IF code NOT IN ('import_invalid','import_conflict','import_stale','import_expired','source_unavailable','not_found',
  'authentication_required','import_limit','import_evidence_unsupported','import_reupload_required','session_changed',
  'credentials_changed','instance_not_ready') THEN code:='import_invalid'; END IF;
 RETURN pg_catalog.jsonb_build_object('ok',false,'code',code);
WHEN data_exception THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid');
WHEN serialization_failure OR deadlock_detected OR lock_not_available OR query_canceled THEN RAISE;
WHEN OTHERS THEN RAISE EXCEPTION USING ERRCODE='XX000',MESSAGE='internal_error';
END $lease$;
REVOKE ALL ON FUNCTION wl_ingestion.NAME(uuid,text,jsonb,bytea) FROM PUBLIC;
""".replace('SESSION_PINS', '' if finish else 'ORIGIN\nMEMBER_PINS').replace('STEP', step)
            .replace('ORIGIN', _ORIGIN_SQL).replace('MEMBER_PINS', _MEMBER_PIN_SQL)
            .replace('SHAPE', shape).replace('BYTES_EXPECTED', 'true' if admit else 'false')
            .replace('REPLAY', replay if finish else '')
            .replace('LIVE_STATES', "'offered','active','finished'" if finish else "'offered','active'")
            .replace('CLEANED', " cleaned:=COALESCE(pg_catalog.jsonb_array_length(p_request->'cleanup_proofs')>0 AND NOT EXISTS("
                     "SELECT 1 FROM pg_catalog.jsonb_array_elements(p_request->'cleanup_proofs') q(value) WHERE "
                     "q.value->>'state' NOT IN ('absent','not_created')),false);" if finish else '')
            .replace('QUOTA_LOCKS', r""" -- The raw quota rows come before the ingestion root, as in reserve.
 IF cleaned THEN
  PERFORM 1 FROM wl_ingestion.instance_budgets WHERE bucket='raw' FOR UPDATE;
  PERFORM 1 FROM wl_ingestion.quotas WHERE tenant_id=tenant AND portfolio_id=portfolio AND bucket='raw' FOR UPDATE;
 END IF;""" if finish else '')
            .replace('KEYS', ','.join("'" + k + "'" for k in sorted(keys))).replace('UUID_RE', _UUID_RE)
            .replace('NAME', name))


# claim turns the bound offer into the active normalize lease; renew extends it;
# admit stores the child's validated minimal evidence for that attempt.
CLAIM_DDL = _lease_ddl('claim_member_v1', 'claim')
RENEW_DDL = _lease_ddl('renew_member_v1', 'renew')
ADMIT_DDL = _lease_ddl('admit_stage_v1', 'admit')
FINISH_DDL = _lease_ddl('finish_member_v1', 'finish')

# One-ID reads: live authentication first, then only the caller's own scope.
# They take no locks, write nothing and never grant authority for a later write.
READ_SET_DDL = r"""
CREATE FUNCTION wl_ingestion.read_set_v1(p_digest text,p_user uuid,p_version bigint,p_realm jsonb,
 p_catalog_digest text,p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $read_set$
DECLARE guard jsonb;tenant uuid;portfolio uuid;result jsonb;
BEGIN
 IF pg_catalog.jsonb_typeof(p_payload) IS DISTINCT FROM 'object' OR
  ARRAY(SELECT pg_catalog.jsonb_object_keys(p_payload) ORDER BY 1)<>ARRAY['set_id']::text[] OR
  pg_catalog.jsonb_typeof(p_payload->'set_id')<>'string' OR (p_payload->>'set_id') COLLATE "C" !~ 'UUID_RE' OR
  p_payload->>'set_id'='00000000-0000-0000-0000-000000000000' THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid');
 END IF;
 guard:=wl_ingestion._guard_user_v1(p_digest,p_user,p_version,p_realm,p_catalog_digest);
 IF guard->>'ok' IS DISTINCT FROM 'true' THEN RETURN guard; END IF;
 tenant:=(guard#>>'{value,tenant_id}')::uuid;portfolio:=(guard#>>'{value,portfolio_id}')::uuid;
 SELECT SET_RESULT INTO result FROM wl_ingestion.sets x WHERE x.tenant_id=tenant AND x.portfolio_id=portfolio
  AND x.id=(p_payload->>'set_id')::uuid;
 IF result IS NULL THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','not_found'); END IF;
 RETURN pg_catalog.jsonb_build_object('ok',true,'value',result);
EXCEPTION WHEN data_exception THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid');
WHEN serialization_failure OR deadlock_detected OR lock_not_available OR query_canceled THEN RAISE;
WHEN OTHERS THEN RAISE EXCEPTION USING ERRCODE='XX000',MESSAGE='internal_error';
END $read_set$;
REVOKE ALL ON FUNCTION wl_ingestion.read_set_v1(text,uuid,bigint,jsonb,text,jsonb) FROM PUBLIC;
""".replace('SET_RESULT', _SET_RESULT_SQL).replace('UUID_RE', _UUID_RE)

READ_RECEIPT_DDL = r"""
CREATE FUNCTION wl_ingestion.read_receipt_v1(p_digest text,p_user uuid,p_version bigint,p_realm jsonb,
 p_catalog_digest text,p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $read_receipt$
DECLARE guard jsonb;tenant uuid;portfolio uuid;saved wl_ingestion.receipts%ROWTYPE;
 entry wl_ingestion.audit%ROWTYPE;result jsonb;
BEGIN
 IF pg_catalog.jsonb_typeof(p_payload) IS DISTINCT FROM 'object' OR
  ARRAY(SELECT pg_catalog.jsonb_object_keys(p_payload) ORDER BY 1)<>ARRAY['receipt_id']::text[] OR
  pg_catalog.jsonb_typeof(p_payload->'receipt_id')<>'string' OR (p_payload->>'receipt_id') COLLATE "C" !~ 'UUID_RE' OR
  p_payload->>'receipt_id'='00000000-0000-0000-0000-000000000000' THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid');
 END IF;
 guard:=wl_ingestion._guard_user_v1(p_digest,p_user,p_version,p_realm,p_catalog_digest);
 IF guard->>'ok' IS DISTINCT FROM 'true' THEN RETURN guard; END IF;
 tenant:=(guard#>>'{value,tenant_id}')::uuid;portfolio:=(guard#>>'{value,portfolio_id}')::uuid;
 -- Historical receipts from earlier restore realms stay readable in the owner scope.
 SELECT * INTO saved FROM wl_ingestion.receipts r WHERE r.tenant_id=tenant AND r.portfolio_id=portfolio
  AND r.id=(p_payload->>'receipt_id')::uuid;
 IF saved.id IS NULL THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','not_found'); END IF;
 IF pg_catalog.octet_length(saved.result_bytes) NOT BETWEEN 1 AND 16384 OR saved.result_bytes<>
  wl_ingestion._canonical_v1(pg_catalog.convert_from(saved.result_bytes,'UTF8')::jsonb) THEN
  RAISE EXCEPTION USING ERRCODE='XX000',MESSAGE='internal_error'; END IF;
 IF saved.operation_kind='ACCEPT' THEN
  RETURN pg_catalog.jsonb_build_object('ok',true,'value',pg_catalog.convert_from(saved.result_bytes,'UTF8')::jsonb);
 END IF;
 -- Control receipts store their set view; the history DTO is rebuilt from the row
 -- and its audit entry. They change no facts.
 SELECT * INTO entry FROM wl_ingestion.audit a WHERE a.tenant_id=tenant AND a.portfolio_id=portfolio AND a.receipt_id=saved.id;
 IF entry.id IS NULL THEN RAISE EXCEPTION USING ERRCODE='XX000',MESSAGE='internal_error'; END IF;
 result:=pg_catalog.jsonb_build_object('id',saved.id::text,'operation_id',saved.operation_id::text,
  'kind',saved.operation_kind,'origin_incarnation',saved.incarnation::text,
  'origin_restore_epoch',saved.restore_epoch::text,'preview_id',saved.preview_id::text,'plan_digest',saved.plan_digest,
  'accepted_generation',entry.after_accepted_generation::text,'mapping_generation',entry.after_mapping_generation::text,
  'new_facts','0','historical_facts','0','duplicates','0','no_change',true,'created_at',INSTANT);
 RETURN pg_catalog.jsonb_build_object('ok',true,'value',result);
EXCEPTION WHEN data_exception THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid');
WHEN serialization_failure OR deadlock_detected OR lock_not_available OR query_canceled THEN RAISE;
WHEN OTHERS THEN RAISE EXCEPTION USING ERRCODE='XX000',MESSAGE='internal_error';
END $read_receipt$;
REVOKE ALL ON FUNCTION wl_ingestion.read_receipt_v1(text,uuid,bigint,jsonb,text,jsonb) FROM PUBLIC;
""".replace('UUID_RE', _UUID_RE).replace('INSTANT', _instant_sql('saved.created_at'))


# A verified cursor payload is rechecked against live authority; its MAC was
# already checked by the API, which alone holds the cursor key. The realm digest
# is the SHA-256 of the canonical realm object the user guard derives.
_CURSOR_PRELUDE_SQL = r"""
 realm:=pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(guard#>'{value,realm}')),'hex');
 SELECT * INTO st FROM wl_pg.instance_state WHERE id=1;
 n:=wl_identity._clock_timestamp_v1();
 SELECT * INTO ss FROM wl_identity.sessions WHERE token_digest=p_digest;
SESSION_RECHECK
 horizon:=LEAST(ss.expires_at,ss.last_activity+interval '1800 seconds');
 IF p_payload->'cursor'<>'null'::jsonb THEN
  cur:=p_payload->'cursor';
  IF pg_catalog.jsonb_typeof(cur)<>'object' OR
   ARRAY(SELECT pg_catalog.jsonb_object_keys(cur) ORDER BY 1)<>ARRAY['after_key','expires_at','filter',
    'portfolio_id','realm_digest','resource_id','resource_revision','review_digest','user_id','version']::text[] OR
   cur->'version'<>'1'::jsonb OR cur->>'user_id' IS DISTINCT FROM tenant::text OR
   cur->>'portfolio_id' IS DISTINCT FROM portfolio::text OR cur->>'realm_digest' IS DISTINCT FROM realm OR
   pg_catalog.jsonb_typeof(cur->'after_key')<>'string' OR pg_catalog.jsonb_typeof(cur->'expires_at')<>'string' OR
   (cur->>'expires_at') COLLATE "C" !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}\+00:00$' THEN
   RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid'); END IF;
  -- An expired cursor, or one outliving this session, starts over.
  IF (cur->>'expires_at')::timestamptz<=n OR (cur->>'expires_at')::timestamptz>horizon THEN
   RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_stale'); END IF;
 END IF;
"""


def _cursor_next_sql(resource, revision, review, filter_, after, horizon):
    return ("pg_catalog.jsonb_build_object('version',1,'user_id',tenant::text,'portfolio_id',portfolio::text,"
            "'realm_digest',realm,'resource_id'," + resource + ",'resource_revision'," + revision +
            ",'review_digest'," + review + ",'filter'," + filter_ + ",'after_key'," + after +
            ",'expires_at',pg_catalog.to_char((" + horizon + ") AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.US')||'+00:00')")


_STATES_SQL = "('RECEIVING','NORMALIZING','RECONCILING','NEEDS_MAPPING','CONFLICT','READY','COMMITTED','REJECTED','CANCELLED','EXPIRED')"

READ_SETS_DDL = r"""
CREATE FUNCTION wl_ingestion.read_sets_v1(p_digest text,p_user uuid,p_version bigint,p_realm jsonb,
 p_catalog_digest text,p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $read_sets$
DECLARE guard jsonb;st wl_pg.instance_state%ROWTYPE;ss wl_identity.sessions%ROWTYPE;
 tenant uuid;portfolio uuid;realm text;n timestamptz;horizon timestamptz;cur jsonb;
 page_size integer;wanted text;after_at timestamptz;after_id uuid;items jsonb;last_at timestamptz;last_id uuid;more boolean;
BEGIN
 -- Fixed query keys only: cursor (already MAC-verified, or null), limit and an optional state.
 IF pg_catalog.jsonb_typeof(p_payload) IS DISTINCT FROM 'object' OR
  ARRAY(SELECT pg_catalog.jsonb_object_keys(p_payload) ORDER BY 1)<>ARRAY['cursor','limit','state']::text[] OR
  pg_catalog.jsonb_typeof(p_payload->'limit')<>'string' OR
  (p_payload->>'limit') COLLATE "C" !~ '^([1-9]|[1-4][0-9]|50)$' OR
  pg_catalog.jsonb_typeof(p_payload->'state') NOT IN ('string','null') OR
  (p_payload->'state'<>'null'::jsonb AND p_payload->>'state' NOT IN STATES) THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid');
 END IF;
 guard:=wl_ingestion._guard_user_v1(p_digest,p_user,p_version,p_realm,p_catalog_digest);
 IF guard->>'ok' IS DISTINCT FROM 'true' THEN RETURN guard; END IF;
 tenant:=(guard#>>'{value,tenant_id}')::uuid;portfolio:=(guard#>>'{value,portfolio_id}')::uuid;
 page_size:=(p_payload->>'limit')::integer;wanted:=p_payload->>'state';
CURSOR_PRELUDE
 IF cur IS NOT NULL THEN
  -- A list cursor names no resource and keeps the filter it was issued for.
  IF cur->'resource_id'<>'null'::jsonb OR cur->'resource_revision'<>'null'::jsonb OR
   cur->'review_digest'<>'null'::jsonb OR cur->>'filter' IS DISTINCT FROM wanted OR
   (cur->>'after_key') COLLATE "C" !~ '^(0|[1-9][0-9]{0,18}):[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
   RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid'); END IF;
  after_at:='1970-01-01T00:00:00+00:00'::timestamptz+
   pg_catalog.split_part(cur->>'after_key',':',1)::bigint*interval '1 microsecond';
  after_id:=pg_catalog.split_part(cur->>'after_key',':',2)::uuid;
 END IF;
 -- Newest first by creation time, then ID; the page reads one row ahead.
 SELECT COALESCE(pg_catalog.jsonb_agg(q.result ORDER BY q.created_at DESC,q.id DESC) FILTER (WHERE q.position<=page_size),'[]'::jsonb),
  pg_catalog.max(q.created_at) FILTER (WHERE q.position=page_size),
  (pg_catalog.array_agg(q.id) FILTER (WHERE q.position=page_size))[1],
  pg_catalog.count(*)>page_size
  INTO items,last_at,last_id,more FROM (
   SELECT SET_RESULT AS result,x.created_at,x.id,
    pg_catalog.row_number() OVER (ORDER BY x.created_at DESC,x.id DESC) AS position
   FROM wl_ingestion.sets x WHERE x.tenant_id=tenant AND x.portfolio_id=portfolio AND (wanted IS NULL OR x.state=wanted)
    AND (after_at IS NULL OR (x.created_at,x.id)<(after_at,after_id))
   ORDER BY x.created_at DESC,x.id DESC LIMIT page_size+1) q;
 RETURN pg_catalog.jsonb_build_object('ok',true,'value',pg_catalog.jsonb_build_object('items',items,
  'next',CASE WHEN more THEN NEXT_CURSOR ELSE NULL END));
EXCEPTION WHEN SQLSTATE '22023' THEN
 IF SQLERRM IN ('session_changed','instance_not_ready') THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code',SQLERRM); END IF;
 RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid');
WHEN data_exception THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid');
WHEN serialization_failure OR deadlock_detected OR lock_not_available OR query_canceled THEN RAISE;
WHEN OTHERS THEN RAISE EXCEPTION USING ERRCODE='XX000',MESSAGE='internal_error';
END $read_sets$;
REVOKE ALL ON FUNCTION wl_ingestion.read_sets_v1(text,uuid,bigint,jsonb,text,jsonb) FROM PUBLIC;
""".replace('CURSOR_PRELUDE', _CURSOR_PRELUDE_SQL).replace('SESSION_RECHECK', _identity.check_session()).replace(
    'SET_RESULT', _SET_RESULT_SQL).replace('STATES', _STATES_SQL).replace('NEXT_CURSOR', _cursor_next_sql(
    'NULL', 'NULL', 'NULL', 'wanted',
    "((EXTRACT(EPOCH FROM last_at)*1000000)::bigint)::text||':'||last_id::text", 'horizon'))

# Rows of one page stop before this many canonical bytes; metadata adds at most
# 16 KiB, so a page stays within the declared 4 MiB + 16 KiB response bound.
PREVIEW_PAGE_BYTES = 4194304

READ_PREVIEW_DDL = r"""
CREATE FUNCTION wl_ingestion.read_preview_v1(p_digest text,p_user uuid,p_version bigint,p_realm jsonb,
 p_catalog_digest text,p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $read_preview$
DECLARE guard jsonb;st wl_pg.instance_state%ROWTYPE;ss wl_identity.sessions%ROWTYPE;
 preview wl_ingestion.previews%ROWTYPE;selected wl_ingestion.sets%ROWTYPE;
 tenant uuid;portfolio uuid;realm text;n timestamptz;horizon timestamptz;cur jsonb;
 page_size integer;start_at integer:=0;total integer;used bigint:=0;rows jsonb:='[]'::jsonb;
 document jsonb;one jsonb;taken integer:=0;
BEGIN
 IF pg_catalog.jsonb_typeof(p_payload) IS DISTINCT FROM 'object' OR
  ARRAY(SELECT pg_catalog.jsonb_object_keys(p_payload) ORDER BY 1)<>ARRAY['cursor','limit','preview_id']::text[] OR
  pg_catalog.jsonb_typeof(p_payload->'preview_id')<>'string' OR (p_payload->>'preview_id') COLLATE "C" !~ 'UUID_RE' OR
  p_payload->>'preview_id'='00000000-0000-0000-0000-000000000000' OR
  pg_catalog.jsonb_typeof(p_payload->'limit')<>'string' OR
  (p_payload->>'limit') COLLATE "C" !~ '^([1-9]|[1-4][0-9]|50)$' THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid');
 END IF;
 guard:=wl_ingestion._guard_user_v1(p_digest,p_user,p_version,p_realm,p_catalog_digest);
 IF guard->>'ok' IS DISTINCT FROM 'true' THEN RETURN guard; END IF;
 tenant:=(guard#>>'{value,tenant_id}')::uuid;portfolio:=(guard#>>'{value,portfolio_id}')::uuid;
 page_size:=(p_payload->>'limit')::integer;
CURSOR_PRELUDE
 SELECT * INTO preview FROM wl_ingestion.previews v WHERE v.tenant_id=tenant AND v.portfolio_id=portfolio
  AND v.id=(p_payload->>'preview_id')::uuid;
 IF preview.id IS NULL THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','not_found'); END IF;
 SELECT * INTO selected FROM wl_ingestion.sets x WHERE x.tenant_id=tenant AND x.portfolio_id=portfolio AND x.id=preview.set_id;
 IF pg_catalog.encode(pg_catalog.sha256(preview.review_bytes),'hex')<>preview.review_digest OR
  preview.review_bytes<>wl_ingestion._canonical_v1(pg_catalog.convert_from(preview.review_bytes,'UTF8')::jsonb) THEN
  RAISE EXCEPTION USING ERRCODE='XX000',MESSAGE='internal_error'; END IF;
 document:=pg_catalog.convert_from(preview.review_bytes,'UTF8')::jsonb;
 IF pg_catalog.jsonb_typeof(document#>'{content,rows}')<>'array' OR document->>'id' IS DISTINCT FROM preview.id::text THEN
  RAISE EXCEPTION USING ERRCODE='XX000',MESSAGE='internal_error'; END IF;
 horizon:=LEAST(horizon,selected.expires_at,preview.expires_at);
 IF cur IS NOT NULL THEN
  -- A page cursor is tied to this exact preview, revision and review document.
  IF cur->'filter'<>'null'::jsonb OR cur->>'resource_id' IS DISTINCT FROM preview.id::text OR
   cur->>'resource_revision' IS DISTINCT FROM preview.set_revision::text OR
   cur->>'review_digest' IS DISTINCT FROM preview.review_digest OR
   (cur->>'after_key') COLLATE "C" !~ '^[1-9][0-9]{0,8}$' THEN
   RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_stale'); END IF;
  IF (cur->>'expires_at')::timestamptz>horizon THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_stale'); END IF;
  start_at:=(cur->>'after_key')::integer;
 END IF;
 total:=pg_catalog.jsonb_array_length(document#>'{content,rows}');
 IF start_at>=total THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_stale'); END IF;
 -- Whole rows only: stop before the row or byte bound, never truncate a row.
 WHILE start_at+taken<total AND taken<page_size LOOP
  one:=document#>ARRAY['content','rows',(start_at+taken)::text];
  EXIT WHEN taken>0 AND used+pg_catalog.octet_length(wl_ingestion._canonical_v1(one))>PAGE_BYTES;
  used:=used+pg_catalog.octet_length(wl_ingestion._canonical_v1(one));
  rows:=rows||pg_catalog.jsonb_build_array(one);taken:=taken+1;
 END LOOP;
 RETURN pg_catalog.jsonb_build_object('ok',true,'value',pg_catalog.jsonb_build_object('page',
  pg_catalog.jsonb_build_object('id',preview.id::text,'set_id',preview.set_id::text,
   'set_revision',preview.set_revision::text,'state',selected.state,'preview_digest',preview.plan_digest,
   'expires_at',INSTANT,'rows',rows,
   -- Confirmation needs the current READY revision with its complete Plan before expiry.
   'can_confirm',(selected.state='READY' AND preview.plan_bytes IS NOT NULL AND
    selected.revision=preview.set_revision AND n<selected.expires_at AND n<preview.expires_at),
   'review_digest',preview.review_digest,'content_digest',document->>'content_digest',
   'accepted_generation',preview.expected_accepted_generation::text,
   'mapping_generation',preview.expected_mapping_generation::text,
   'control_generation',preview.expected_control_generation::text),
  'next',CASE WHEN start_at+taken<total AND horizon>n THEN NEXT_CURSOR ELSE NULL END));
EXCEPTION WHEN SQLSTATE '22023' THEN
 IF SQLERRM IN ('session_changed','instance_not_ready') THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code',SQLERRM); END IF;
 RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid');
WHEN data_exception THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid');
WHEN serialization_failure OR deadlock_detected OR lock_not_available OR query_canceled THEN RAISE;
WHEN OTHERS THEN RAISE EXCEPTION USING ERRCODE='XX000',MESSAGE='internal_error';
END $read_preview$;
REVOKE ALL ON FUNCTION wl_ingestion.read_preview_v1(text,uuid,bigint,jsonb,text,jsonb) FROM PUBLIC;
""".replace('CURSOR_PRELUDE', _CURSOR_PRELUDE_SQL).replace('SESSION_RECHECK', _identity.check_session()).replace(
    'UUID_RE', _UUID_RE).replace('PAGE_BYTES', str(PREVIEW_PAGE_BYTES)).replace(
    'INSTANT', _instant_sql('preview.expires_at')).replace('NEXT_CURSOR', _cursor_next_sql(
    'preview.id::text', 'preview.set_revision::text', 'preview.review_digest', 'NULL',
    '(start_at+taken)::text', 'horizon'))


def user_guard_ddl():
    """Render the declared private guard without altering predecessor providers.

    The complete migration must verify its ownership/privileges and the source
    profile before any application can reach it. Current source/profile pins
    remain checks for new effects, after proven receipt replay.
    """
    from . import identity_schema as identity
    guard = identity.GUARD
    if guard.count("'0002_identity'") != 1:
        raise ValueError('Frozen identity guard changed')
    guard = guard.replace("'0002_identity'", "'0004_ingestion'")
    anchor = ' SELECT * INTO a FROM wl_identity.instance_auth_state WHERE id=1 FOR UPDATE;'
    if guard.count(anchor) != 1:
        raise ValueError('Frozen identity lock order changed')
    guard = guard.replace(anchor, """
 SELECT * INTO ingestion_state FROM wl_ingestion.instance_state WHERE id=1 FOR SHARE;
 IF ingestion_state.id IS NULL OR NOT ingestion_state.ready THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','instance_not_ready');
 END IF;
""" + anchor)
    body = guard + """
 IF NOT a.bootstrap_closed OR a.admin_user_id IS NULL THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','instance_not_ready');
 END IF;
""" + identity.user_lock('p_user') + identity.session_lock('p_digest') + """
 SELECT * INTO cs FROM wl_sources.catalog_state WHERE id=1 FOR SHARE;
 PERFORM 1 FROM wl_pg.portfolios WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id FOR KEY SHARE;
 portfolio_found:=FOUND;
""" + identity.CLOCK + """
 IF p_realm IS DISTINCT FROM """ + identity.realm() + """ THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','instance_not_ready');
 END IF;
 IF cs.id IS NULL OR p_catalog_digest IS DISTINCT FROM cs.digest THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','source_catalog_unavailable');
 END IF;
""" + identity.check_user(version='p_version') + identity.check_session() + """
 IF ss.user_id<>u.id OR ss.credential_version<>u.credential_version THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','session_changed');
 END IF;
 IF NOT portfolio_found THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','instance_not_ready');
 END IF;
 PERFORM pg_catalog.set_config('ledger.tenant_id',u.id::text,true),
  pg_catalog.set_config('ledger.portfolio_id',u.portfolio_id::text,true);
 RETURN pg_catalog.jsonb_build_object('ok',true,'value',pg_catalog.jsonb_build_object(
  'tenant_id',u.id::text,'portfolio_id',u.portfolio_id::text,'realm',""" + identity.realm() + """));
"""
    return """CREATE FUNCTION wl_ingestion._guard_user_v1(
 p_digest text,p_user uuid,p_version bigint,p_realm jsonb,p_catalog_digest text) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $user_guard$
DECLARE st wl_pg.instance_state%ROWTYPE;a wl_identity.instance_auth_state%ROWTYPE;
 u wl_identity.users%ROWTYPE;ss wl_identity.sessions%ROWTYPE;
 cs wl_sources.catalog_state%ROWTYPE;ingestion_state wl_ingestion.instance_state%ROWTYPE;
 n timestamptz;portfolio_found boolean;
BEGIN
""" + body + """END $user_guard$;
REVOKE ALL ON FUNCTION wl_ingestion._guard_user_v1(text,uuid,bigint,jsonb,text) FROM PUBLIC;
"""


def worker_guard_ddl():
    """Render the private worker guard every worker function calls first.

    Identity is the actual database login mapped to an enabled registry row. The
    worker UUID, token and request fields are assertions checked against it; they
    are never scope authority. Lease, fence and token checks belong to each
    worker function. Cleanup must not depend on a live user session.
    """
    from . import identity_schema as identity
    return r"""CREATE FUNCTION wl_ingestion._guard_worker_v1(p_worker uuid,p_token text,p_request jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $worker_guard$
DECLARE st wl_pg.instance_state%ROWTYPE;ingestion_state wl_ingestion.instance_state%ROWTYPE;
 w wl_ingestion.workers%ROWTYPE;n timestamptz;realm text;
BEGIN
 IF p_worker IS NULL OR p_worker='00000000-0000-0000-0000-000000000000'::uuid OR p_token IS NULL OR
  p_token COLLATE "C" !~ '^[0-9a-f]{64}$' OR pg_catalog.jsonb_typeof(p_request) IS DISTINCT FROM 'object' OR
  pg_catalog.jsonb_typeof(p_request->'realm_digest') IS DISTINCT FROM 'string' OR
  pg_catalog.jsonb_typeof(p_request->'credential_epoch') IS DISTINCT FROM 'string' OR
  (p_request->>'realm_digest') COLLATE "C" !~ '^[0-9a-f]{64}$' OR
  (p_request->>'credential_epoch') COLLATE "C" !~ '^[1-9][0-9]{0,17}$' THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid');
 END IF;
 -- Shared instance rows first, as in the declared lock order.
 SELECT * INTO st FROM wl_pg.instance_state WHERE id=1 FOR SHARE;
 IF st.id IS NULL OR NOT st.ready OR
  (SELECT pg_catalog.count(*)<>1 OR pg_catalog.max(version_num) IS DISTINCT FROM '0004_ingestion' FROM wl_pg.alembic_version) THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','instance_not_ready');
 END IF;
 SELECT * INTO ingestion_state FROM wl_ingestion.instance_state WHERE id=1 FOR SHARE;
 IF ingestion_state.id IS NULL OR NOT ingestion_state.ready THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','instance_not_ready');
 END IF;
 n:=wl_identity._clock_timestamp_v1();
 IF n IS NULL OR NOT pg_catalog.isfinite(n) THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','instance_not_ready'); END IF;
 -- The registry row must belong to the role that actually logged in.
 SELECT * INTO w FROM wl_ingestion.workers x WHERE x.id=p_worker FOR SHARE;
 IF w.id IS NULL OR w.login_role IS DISTINCT FROM session_user THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','authentication_required'); END IF;
 IF NOT w.enabled OR w.credential_epoch::text IS DISTINCT FROM p_request->>'credential_epoch' THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','credentials_changed'); END IF;
 realm:=pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(""" + identity.realm() + r""")),'hex');
 IF p_request->>'realm_digest' IS DISTINCT FROM realm THEN
  RETURN pg_catalog.jsonb_build_object('ok',false,'code','instance_not_ready'); END IF;
 RETURN pg_catalog.jsonb_build_object('ok',true,'value',pg_catalog.jsonb_build_object('worker_id',w.id::text,
  'credential_epoch',w.credential_epoch::text,'realm_digest',realm,
  'token_digest',pg_catalog.encode(pg_catalog.sha256(pg_catalog.decode(p_token,'hex')),'hex'),
  'incarnation',st.incarnation::text,'restore_epoch',st.restore_epoch::text));
EXCEPTION WHEN serialization_failure OR deadlock_detected OR lock_not_available OR query_canceled THEN RAISE;
WHEN data_exception THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','import_invalid');
WHEN OTHERS THEN RAISE EXCEPTION USING ERRCODE='XX000',MESSAGE='internal_error';
END $worker_guard$;
REVOKE ALL ON FUNCTION wl_ingestion._guard_worker_v1(uuid,text,jsonb) FROM PUBLIC;
"""

CANONICAL_DDL = r'''
CREATE FUNCTION wl_ingestion._canonical_v1(p_value jsonb) RETURNS bytea
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $canonical$
DECLARE rendered text;maximum_depth integer;bad_number boolean;
BEGIN
 IF p_value IS NULL THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid'; END IF;
 IF pg_catalog.octet_length(p_value::text)>33554432 THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_limit';
 END IF;
 -- Traverse the tree once, ordering opening/scalar/closing pieces by a numeric
 -- path. This avoids a recursive function call and repeated tree scan per scalar.
 WITH RECURSIVE nodes(value,path,depth,prefix) AS (
  SELECT p_value,ARRAY[0],0,''::text
  UNION ALL
  SELECT child.value,nodes.path||child.ordinal,nodes.depth+1,
   CASE WHEN child.ordinal=1 THEN '' ELSE ',' END||child.label
  FROM nodes CROSS JOIN LATERAL (
   SELECT object_child.value,
    pg_catalog.row_number() OVER(ORDER BY object_child.key COLLATE "C")::integer AS ordinal,
    pg_catalog.to_jsonb(object_child.key)::text||':' AS label
   FROM pg_catalog.jsonb_each(CASE WHEN pg_catalog.jsonb_typeof(nodes.value)='object'
    THEN nodes.value ELSE '{}'::jsonb END) object_child
   UNION ALL
   SELECT array_child.value,array_child.ordinal::integer,''::text
   FROM pg_catalog.jsonb_array_elements(CASE WHEN pg_catalog.jsonb_typeof(nodes.value)='array'
    THEN nodes.value ELSE '[]'::jsonb END) WITH ORDINALITY array_child(value,ordinal)
  ) child WHERE nodes.depth<33
 ), properties AS (
  SELECT *,pg_catalog.jsonb_typeof(value) AS kind FROM nodes
 ), pieces AS (
  SELECT path||0 AS position,prefix||CASE kind WHEN 'object' THEN '{' WHEN 'array' THEN '['
   ELSE value::text END AS token FROM properties
  UNION ALL
  SELECT path||2147483647,CASE kind WHEN 'object' THEN '}' ELSE ']' END
   FROM properties WHERE kind IN ('object','array')
 )
 SELECT max(depth),pg_catalog.bool_or(CASE WHEN kind='number'
  THEN value::text COLLATE "C" !~ '^-?(0|[1-9][0-9]*)$' ELSE false END),
  (SELECT pg_catalog.string_agg(token,'' ORDER BY position) FROM pieces)
 INTO maximum_depth,bad_number,rendered FROM properties;
 IF maximum_depth>32 THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_limit'; END IF;
 IF bad_number THEN RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid'; END IF;
 IF pg_catalog.octet_length(pg_catalog.convert_to(rendered,'UTF8'))>16777216 THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_limit';
 END IF;
 RETURN pg_catalog.convert_to(rendered,'UTF8');
END $canonical$;
REVOKE ALL ON FUNCTION wl_ingestion._canonical_v1(jsonb) FROM PUBLIC;
'''


# A partial guard fragment; a complete checked migration must install all guards.
IMMUTABLE_DDL = r'''
CREATE FUNCTION wl_ingestion._immutable_v1() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $immutable$
BEGIN
 IF TG_TABLE_SCHEMA<>'wl_ingestion' OR TG_TABLE_NAME NOT IN
  ('accepted_inputs','accepted_plans','source_revisions','mappings',
   'authority_links','lineage','receipts','audit') OR TG_WHEN<>'BEFORE'
  OR TG_LEVEL<>'ROW' OR TG_OP<>'INSERT' THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
 END IF;
 -- Direct application DML remains denied by the profile grants. This trigger
 -- enforces append-only storage; the checked acceptance functions establish
 -- authorization and validate the complete accepted evidence before insertion.
 RETURN NEW;
END $immutable$;
REVOKE ALL ON FUNCTION wl_ingestion._immutable_v1() FROM PUBLIC;
'''


OUTBOX_GUARD_DDL = r'''
CREATE FUNCTION wl_ingestion._outbox_guard_v1() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $outbox$
DECLARE payload jsonb; field text; item jsonb; at_value jsonb; parts text[];
 token text; zone text; clock_at timestamptz; local_at timestamp;
 offset_minutes integer; counter_value text;
BEGIN
 IF TG_TABLE_SCHEMA<>'wl_ingestion' OR TG_TABLE_NAME<>'outbox' OR
  TG_WHEN<>'BEFORE' OR TG_LEVEL<>'ROW' OR TG_OP<>'INSERT' THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
 END IF;
 IF NEW.payload_bytes IS NULL OR pg_catalog.octet_length(NEW.payload_bytes)=0 THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
 END IF;
 IF pg_catalog.octet_length(NEW.payload_bytes)>4194304 THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_limit';
 END IF;
 payload:=pg_catalog.convert_from(NEW.payload_bytes,'UTF8')::jsonb;
 IF NEW.payload_bytes<>wl_ingestion._canonical_v1(payload) OR
  NEW.payload_digest<>pg_catalog.encode(pg_catalog.sha256(NEW.payload_bytes),'hex') OR
  pg_catalog.jsonb_typeof(payload)<>'object' THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
 END IF;
 IF NOT payload ?& ARRAY['version','type','tenant_id','portfolio_id','receipt_id',
  'accepted_generation','mapping_generation','plan_digest','changed_revision_ids',
  'changed_head_keys','accepted_at'] OR
  payload-ARRAY['version','type','tenant_id','portfolio_id','receipt_id',
  'accepted_generation','mapping_generation','plan_digest','changed_revision_ids',
  'changed_head_keys','accepted_at']<>'{}'::jsonb THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
 END IF;
 IF payload->'version'<>'1'::jsonb OR payload->'type'<>'"facts.accepted.v1"'::jsonb OR
  NEW.version<>1 OR NEW.type<>'facts.accepted.v1' OR NEW.dispatched_at IS NOT NULL THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
 END IF;
 FOREACH field IN ARRAY ARRAY['tenant_id','portfolio_id','receipt_id'] LOOP
  token:=payload->>field;
  IF pg_catalog.jsonb_typeof(payload->field)<>'string' OR
   token COLLATE "C" !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' OR
   token='00000000-0000-0000-0000-000000000000' THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
  END IF;
 END LOOP;
 IF payload->>'tenant_id'<>NEW.tenant_id::text OR
  payload->>'portfolio_id'<>NEW.portfolio_id::text OR
  payload->>'receipt_id'<>NEW.receipt_id::text OR
  pg_catalog.jsonb_typeof(payload->'plan_digest')<>'string' OR
  payload->>'plan_digest' COLLATE "C" !~ '^[0-9a-f]{64}$' OR
  payload->>'plan_digest'<>NEW.plan_digest THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
 END IF;
 FOREACH field IN ARRAY ARRAY['accepted_generation','mapping_generation'] LOOP
  counter_value:=payload->>field;
  IF pg_catalog.jsonb_typeof(payload->field)<>'string' OR
   counter_value COLLATE "C" !~ '^(0|[1-9][0-9]{0,18})$' OR
   (pg_catalog.length(counter_value)=19 AND
    counter_value COLLATE "C">'9223372036854775807') THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
  END IF;
 END LOOP;
 IF payload->>'accepted_generation'<>NEW.accepted_generation::text THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
 END IF;
 FOREACH field IN ARRAY ARRAY['changed_revision_ids','changed_head_keys'] LOOP
  IF pg_catalog.jsonb_typeof(payload->field)<>'array' THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
  END IF;
  IF pg_catalog.jsonb_array_length(payload->field)>40000 THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_limit';
  END IF;
  FOR item IN SELECT value FROM pg_catalog.jsonb_array_elements(payload->field) LOOP
   token:=item#>>'{}';
   IF pg_catalog.jsonb_typeof(item)<>'string' OR
    (field='changed_head_keys' AND token COLLATE "C" !~ '^[0-9a-f]{64}$') OR
    (field='changed_revision_ids' AND
     (token COLLATE "C" !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' OR
      token='00000000-0000-0000-0000-000000000000')) THEN
    RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
   END IF;
  END LOOP;
 END LOOP;
 at_value:=payload->'accepted_at';
 IF pg_catalog.jsonb_typeof(at_value)<>'object' THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
 END IF;
 IF NOT at_value ?& ARRAY['tag','token','zone','fractional_digits'] OR
  at_value-ARRAY['tag','token','zone','fractional_digits']<>'{}'::jsonb OR
  at_value->'tag'<>'"instant"'::jsonb OR
  pg_catalog.jsonb_typeof(at_value->'token')<>'string' THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
 END IF;
 token:=at_value->>'token'; zone:=at_value->>'zone';
 IF at_value->'zone'<>'null'::jsonb AND
  (pg_catalog.jsonb_typeof(at_value->'zone')<>'string' OR pg_catalog.length(zone)>128 OR
   zone COLLATE "C" !~ '^[A-Za-z0-9_+./-]+$' OR
   pg_catalog.string_to_array(zone,'/') && ARRAY['.','..']) THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
 END IF;
 parts:=pg_catalog.regexp_match(token COLLATE "C",
  E'^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(\\.[0-9]{1,6})?(Z|[+-][0-9]{2}:[0-9]{2})$');
 IF parts IS NULL THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
 END IF;
 IF at_value->'fractional_digits'<>pg_catalog.to_jsonb(
   CASE WHEN parts[7] IS NULL THEN 0 ELSE pg_catalog.length(parts[7])-1 END) OR
  parts[1]::integer=0 OR parts[4]::integer>23 OR parts[5]::integer>59 OR
  parts[6]::integer>59 OR parts[8]='-00:00' THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
 END IF;
 offset_minutes:=0;
 IF parts[8]<>'Z' THEN
  IF pg_catalog.substr(parts[8],2,2)::integer>23 OR
   pg_catalog.substr(parts[8],5,2)::integer>59 THEN
   RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
  END IF;
  offset_minutes:=(pg_catalog.substr(parts[8],2,2)::integer*60+
   pg_catalog.substr(parts[8],5,2)::integer)*CASE WHEN pg_catalog.left(parts[8],1)='-' THEN -1 ELSE 1 END;
 END IF;
 -- A manual offset preserves the frozen codec's valid +/-23:59 envelope;
 -- PostgreSQL's direct timestamptz input has a narrower offset bound.
 local_at:=pg_catalog.make_timestamp(parts[1]::integer,parts[2]::integer,parts[3]::integer,
  parts[4]::integer,parts[5]::integer,(parts[6]||COALESCE(parts[7],''))::double precision);
 clock_at:=pg_catalog.timezone('UTC',local_at-pg_catalog.make_interval(mins=>offset_minutes));
 IF NOT pg_catalog.isfinite(NEW.created_at) OR clock_at<>NEW.created_at THEN
  RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
 END IF;
 -- This guard binds the immutable event envelope. The checked effects function
 -- still proves actual accepted references, generations and changed-head sets.
 RETURN NEW;
EXCEPTION WHEN OTHERS THEN
 IF SQLSTATE='22023' AND SQLERRM IN ('import_invalid','import_limit') THEN RAISE; END IF;
 RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
END $outbox$;
REVOKE ALL ON FUNCTION wl_ingestion._outbox_guard_v1() FROM PUBLIC;
'''


# Row-local storage invariants for mutable control rows. The checked functions
# still authenticate, take locks in the declared order and recheck live source
# authority; this guard only rejects states no checked function may produce.
TRANSITION_DDL = r'''
CREATE FUNCTION wl_ingestion._transition_v1() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $transition$
DECLARE n timestamptz; parent wl_ingestion.sets%ROWTYPE; root wl_ingestion.roots%ROWTYPE;
 member wl_ingestion.members%ROWTYPE; worker wl_ingestion.workers%ROWTYPE;
 terminal text[]:=ARRAY['COMMITTED','REJECTED','CANCELLED','EXPIRED'];
 allowed text[]; latest bigint;
BEGIN
 IF TG_TABLE_SCHEMA<>'wl_ingestion' OR TG_WHEN<>'BEFORE' OR TG_LEVEL<>'ROW' OR TG_TABLE_NAME NOT IN
  ('roots','sets','members','leases','stages','decisions','previews','quotas',
   'instance_state','instance_budgets','workers') THEN REJECT;
 END IF;
 n:=wl_identity._clock_timestamp_v1();
 IF NOT pg_catalog.isfinite(n) THEN REJECT; END IF;
 -- Callers lock parents before children; reads here never take a later lock.
 IF TG_TABLE_NAME IN ('members','leases','stages','decisions','previews') THEN
  SELECT * INTO parent FROM wl_ingestion.sets s WHERE s.tenant_id=
   CASE WHEN TG_OP='DELETE' THEN OLD.tenant_id ELSE NEW.tenant_id END AND s.portfolio_id=
   CASE WHEN TG_OP='DELETE' THEN OLD.portfolio_id ELSE NEW.portfolio_id END AND s.id=
   CASE WHEN TG_OP='DELETE' THEN OLD.set_id ELSE NEW.set_id END;
  IF parent.id IS NULL THEN REJECT; END IF;
 END IF;

 IF TG_TABLE_NAME='roots' THEN
  IF TG_OP='INSERT' THEN
   IF NEW.accepted_generation<>0 OR NEW.mapping_generation<>0 OR NEW.control_generation<>0 THEN REJECT; END IF;
  ELSIF TG_OP='UPDATE' THEN
   -- Each counter advances at most once for one accepted or control effect.
   IF (NEW.tenant_id,NEW.portfolio_id) IS DISTINCT FROM (OLD.tenant_id,OLD.portfolio_id) OR
    NEW.accepted_generation-OLD.accepted_generation NOT IN (0,1) OR
    NEW.mapping_generation-OLD.mapping_generation NOT IN (0,1) OR
    NEW.control_generation-OLD.control_generation NOT IN (0,1) THEN REJECT; END IF;
  ELSE REJECT; END IF;
  RETURN NEW;

 ELSIF TG_TABLE_NAME='sets' THEN
  IF TG_OP='INSERT' THEN
   SELECT * INTO root FROM wl_ingestion.roots r WHERE r.tenant_id=NEW.tenant_id AND r.portfolio_id=NEW.portfolio_id;
   IF root.tenant_id IS NULL OR NEW.state<>'RECEIVING' OR NEW.revision<>1 OR NEW.receipt_id IS NOT NULL OR
    NEW.cleanup_state<>'not_needed' OR NEW.created_at>n OR n>=NEW.expires_at THEN REJECT; END IF;
   RETURN NEW;
  ELSIF TG_OP<>'UPDATE' THEN REJECT; END IF;
  IF (NEW.tenant_id,NEW.portfolio_id,NEW.id,NEW.actor_user_id,NEW.creation_operation_id,
    NEW.request_digest,NEW.incarnation,NEW.restore_epoch,NEW.realm_digest,NEW.created_at,
    NEW.expires_at,NEW.member_count,NEW.reserved_bytes) IS DISTINCT FROM
   (OLD.tenant_id,OLD.portfolio_id,OLD.id,OLD.actor_user_id,OLD.creation_operation_id,
    OLD.request_digest,OLD.incarnation,OLD.restore_epoch,OLD.realm_digest,OLD.created_at,
    OLD.expires_at,OLD.member_count,OLD.reserved_bytes) OR
   (OLD.receipt_id IS NOT NULL AND NEW.receipt_id IS DISTINCT FROM OLD.receipt_id) THEN REJECT; END IF;
  IF OLD.state=ANY(terminal) THEN
   -- A terminal set is never revived; only its transient cleanup progresses.
   IF NEW.state<>OLD.state OR NEW.revision<>OLD.revision THEN REJECT; END IF;
  ELSE
   IF NEW.state<>OLD.state THEN
    allowed:=CASE OLD.state WHEN 'RECEIVING' THEN ARRAY['NORMALIZING']
     WHEN 'NORMALIZING' THEN ARRAY['NEEDS_MAPPING','CONFLICT','READY']
     WHEN 'RECONCILING' THEN ARRAY['NEEDS_MAPPING','CONFLICT','READY']
     WHEN 'NEEDS_MAPPING' THEN ARRAY['RECONCILING'] WHEN 'CONFLICT' THEN ARRAY['RECONCILING']
     WHEN 'READY' THEN ARRAY['RECONCILING','COMMITTED'] ELSE ARRAY[]::text[] END
     ||ARRAY['CANCELLED','EXPIRED','REJECTED'];
    IF NOT NEW.state=ANY(allowed) THEN REJECT; END IF;
   END IF;
   -- Once the DB clock reaches expiry, the only live change is EXPIRED.
   IF (n>=OLD.expires_at)<>(NEW.state='EXPIRED') THEN EXPIRED; END IF;
   -- Decisions, cancellation, READY preparation and acceptance each advance the
   -- set revision once; upload, discovery-only preparation and expiry do not.
   IF NEW.revision-OLD.revision<>(CASE WHEN NEW.state<>OLD.state AND
    NEW.state IN ('RECONCILING','CANCELLED','READY','COMMITTED') THEN 1 ELSE 0 END) THEN REJECT; END IF;
  END IF;
  IF (NOT NEW.state=ANY(terminal) AND NEW.cleanup_state<>'not_needed') OR
   (NEW.cleanup_state<>OLD.cleanup_state AND NOT (
    (OLD.cleanup_state='not_needed' AND NEW.cleanup_state='pending') OR
    (OLD.cleanup_state='pending' AND NEW.cleanup_state IN ('complete','failed')) OR
    (OLD.cleanup_state='failed' AND NEW.cleanup_state='pending'))) THEN REJECT; END IF;
  RETURN NEW;

 ELSIF TG_TABLE_NAME='members' THEN
  IF TG_OP='INSERT' THEN
   IF parent.state<>'RECEIVING' OR n>=parent.expires_at OR NEW.ordinal>=parent.member_count OR
    NEW.state<>'waiting' OR NEW.fence<>1 OR NEW.context_bytes IS NULL OR NEW.raw_digest IS NOT NULL OR
    NEW.raw_bytes IS NOT NULL OR NEW.raw_deadline IS NOT NULL OR NEW.stage_digest IS NOT NULL OR
    NEW.error_code IS NOT NULL THEN REJECT; END IF;
   RETURN NEW;
  ELSIF TG_OP<>'UPDATE' THEN REJECT; END IF;
  -- The selection, source generations and wrapper captured at creation stay pinned.
  IF (NEW.tenant_id,NEW.portfolio_id,NEW.set_id,NEW.id,NEW.ordinal,NEW.connection_id,
    NEW.connection_version,NEW.installation_id,NEW.format_version,NEW.context_digest,
    NEW.connection_generation,NEW.enablement_generation,NEW.availability_generation,
    NEW.wrapper_profile_digest) IS DISTINCT FROM
   (OLD.tenant_id,OLD.portfolio_id,OLD.set_id,OLD.id,OLD.ordinal,OLD.connection_id,
    OLD.connection_version,OLD.installation_id,OLD.format_version,OLD.context_digest,
    OLD.connection_generation,OLD.enablement_generation,OLD.availability_generation,
    OLD.wrapper_profile_digest) OR
   (NEW.context_bytes IS DISTINCT FROM OLD.context_bytes AND
    (NEW.context_bytes IS NOT NULL OR NOT parent.state=ANY(terminal))) OR
   (NEW.raw_digest IS NULL)<>(NEW.raw_bytes IS NULL) THEN REJECT; END IF;
  IF OLD.state IN ('rejected','cancelled','expired','committed') THEN
   IF (NEW.state,NEW.fence,NEW.raw_digest,NEW.raw_bytes,NEW.raw_deadline,NEW.stage_digest,NEW.error_code)
    IS DISTINCT FROM (OLD.state,OLD.fence,OLD.raw_digest,OLD.raw_bytes,OLD.raw_deadline,
    OLD.stage_digest,OLD.error_code) THEN REJECT; END IF;
   RETURN NEW;
  END IF;
  IF NEW.state<>OLD.state THEN
   allowed:=CASE OLD.state WHEN 'waiting' THEN ARRAY['receiving','reupload_required']
    WHEN 'receiving' THEN ARRAY['normalizing','reupload_required']
    WHEN 'normalizing' THEN ARRAY['admitted','reupload_required']
    WHEN 'reupload_required' THEN ARRAY['receiving'] WHEN 'admitted' THEN ARRAY['committed']
    ELSE ARRAY[]::text[] END||ARRAY['rejected','cancelled','expired'];
   IF NOT NEW.state=ANY(allowed) THEN REJECT; END IF;
  END IF;
  -- A member's terminal outcome follows its already locked set.
  IF NEW.state IN ('committed','cancelled','expired','rejected') THEN
   IF parent.state<>pg_catalog.upper(NEW.state) THEN REJECT; END IF;
  ELSIF parent.state=ANY(terminal) THEN REJECT;
  ELSIF n>=parent.expires_at THEN EXPIRED;
  END IF;
  -- A new raw attempt advances the fence; reserve and bind fill empty fields once.
  IF NEW.fence-OLD.fence NOT IN (0,1) OR
   (OLD.state='reupload_required' AND NEW.state='receiving' AND NEW.fence<>OLD.fence+1) OR
   ((NEW.raw_digest,NEW.raw_bytes,NEW.raw_deadline) IS DISTINCT FROM
    (OLD.raw_digest,OLD.raw_bytes,OLD.raw_deadline) AND NEW.fence=OLD.fence AND
    NOT (OLD.raw_digest IS NULL AND (OLD.raw_deadline IS NULL OR NEW.raw_deadline=OLD.raw_deadline))) OR
   (NEW.state IN ('normalizing','admitted','committed') AND NEW.raw_digest IS NULL) OR
   (NEW.state IN ('admitted','committed') AND (NEW.stage_digest IS NULL OR NEW.error_code IS NOT NULL)) THEN
   REJECT; END IF;
  IF NEW.stage_digest IS DISTINCT FROM OLD.stage_digest AND (OLD.stage_digest IS NOT NULL OR
   OLD.state<>'normalizing' OR NEW.state<>'admitted' OR NOT EXISTS(SELECT 1 FROM wl_ingestion.stages g
    WHERE g.tenant_id=NEW.tenant_id AND g.portfolio_id=NEW.portfolio_id AND g.set_id=NEW.set_id
     AND g.member_id=NEW.id AND g.digest=NEW.stage_digest)) THEN REJECT; END IF;
  RETURN NEW;

 ELSIF TG_TABLE_NAME='leases' THEN
  IF TG_OP='DELETE' THEN REJECT; END IF;
  SELECT * INTO worker FROM wl_ingestion.workers w WHERE w.id=NEW.worker_id;
  IF NEW.work_kind='normalize' THEN
   SELECT * INTO member FROM wl_ingestion.members m WHERE m.tenant_id=NEW.tenant_id AND
    m.portfolio_id=NEW.portfolio_id AND m.set_id=NEW.set_id AND m.id=NEW.member_id;
   IF member.id IS NULL THEN REJECT; END IF;
  END IF;
  IF TG_OP='INSERT' THEN
   IF worker.id IS NULL OR NOT worker.enabled OR NEW.state NOT IN ('offered','active') OR
    NEW.created_at>n OR NEW.expires_at<=n OR NEW.incarnation<>parent.incarnation OR
    NEW.restore_epoch<>parent.restore_epoch OR NEW.last_request_id IS NOT NULL OR
    -- Raw reception has a short unbound offer; any token-bound lease lasts at most 60s.
    NEW.expires_at>NEW.created_at+(CASE WHEN NEW.work_kind='normalize' AND NEW.token_digest IS NULL
     THEN interval '30 seconds' ELSE interval '60 seconds' END) OR
    (NEW.state='active' AND (NEW.work_kind='normalize' OR NEW.token_digest IS NULL OR
     NEW.claim_request_id IS NULL)) OR (NEW.state='offered' AND NEW.claim_request_id IS NOT NULL) OR
    (NEW.work_kind='cleanup')<>(parent.state=ANY(terminal)) OR
    (NEW.work_kind<>'cleanup' AND n>=parent.expires_at) OR
    (NEW.work_kind='normalize' AND (NEW.fence<>member.fence OR
     member.state NOT IN ('waiting','receiving'))) THEN REJECT; END IF;
   RETURN NEW;
  END IF;
  IF (NEW.tenant_id,NEW.portfolio_id,NEW.id,NEW.set_id,NEW.member_id,NEW.work_kind,NEW.attempt,
    NEW.fence,NEW.worker_id,NEW.session_digest,NEW.credential_version,NEW.incarnation,
    NEW.restore_epoch,NEW.created_at) IS DISTINCT FROM
   (OLD.tenant_id,OLD.portfolio_id,OLD.id,OLD.set_id,OLD.member_id,OLD.work_kind,OLD.attempt,
    OLD.fence,OLD.worker_id,OLD.session_digest,OLD.credential_version,OLD.incarnation,
    OLD.restore_epoch,OLD.created_at) OR OLD.state IN ('finished','expired','cancelled') THEN
   REJECT; END IF;
  IF NEW.state<>OLD.state AND NOT NEW.state=ANY(CASE OLD.state
   WHEN 'offered' THEN ARRAY['active','expired','cancelled']
   ELSE ARRAY['finished','expired','cancelled'] END) THEN REJECT; END IF;
  IF NEW.state='expired' THEN
   IF n<OLD.expires_at OR NEW.expires_at<>OLD.expires_at THEN REJECT; END IF;
  ELSIF NEW.state IN ('offered','active','finished') THEN
   -- Work after the deadline, a disabled worker or a newer member fence is stale.
   IF n>=OLD.expires_at OR NOT worker.enabled OR
    (NEW.work_kind<>'cleanup' AND parent.state=ANY(terminal)) OR
    (NEW.work_kind='normalize' AND member.fence<>NEW.fence) THEN EXPIRED; END IF;
  END IF;
  IF (NEW.token_digest IS DISTINCT FROM OLD.token_digest AND NOT (OLD.token_digest IS NULL AND
    OLD.state='offered' AND NEW.state='offered')) OR
   ((NEW.claim_request_id,NEW.claim_request_digest) IS DISTINCT FROM
    (OLD.claim_request_id,OLD.claim_request_digest) AND NOT (OLD.claim_request_id IS NULL AND
    OLD.state='offered' AND NEW.state='active')) OR
   (NEW.state='active' AND (NEW.token_digest IS NULL OR NEW.claim_request_id IS NULL)) OR
   ((NEW.last_request_id,NEW.last_request_digest,NEW.last_result_bytes) IS DISTINCT FROM
    (OLD.last_request_id,OLD.last_request_digest,OLD.last_result_bytes) AND OLD.state<>'active') OR
   (NEW.expires_at<>OLD.expires_at AND (NEW.state NOT IN ('offered','active') OR NEW.expires_at<=n OR
    NEW.expires_at>n+interval '60 seconds')) THEN REJECT; END IF;
  RETURN NEW;

 ELSIF TG_TABLE_NAME IN ('stages','decisions','previews') THEN
  IF TG_OP='DELETE' THEN
   -- Transient review/evidence rows are removed only after terminal state or expiry.
   IF NOT (parent.state=ANY(terminal) OR n>=OLD.purge_at) THEN REJECT; END IF;
   RETURN OLD;
  ELSIF TG_OP<>'INSERT' THEN REJECT; END IF;
  IF parent.state=ANY(terminal) THEN REJECT; END IF;
  IF n>=parent.expires_at THEN EXPIRED; END IF;
  IF NEW.created_at>n OR NEW.purge_at<>parent.expires_at THEN REJECT; END IF;
  IF TG_TABLE_NAME='stages' THEN
   IF NOT EXISTS(SELECT 1 FROM wl_ingestion.members m WHERE m.tenant_id=NEW.tenant_id AND
    m.portfolio_id=NEW.portfolio_id AND m.set_id=NEW.set_id AND m.id=NEW.member_id AND
    m.state='normalizing') THEN REJECT; END IF;
   RETURN NEW;
  END IF;
  SELECT pg_catalog.max(d.revision) INTO latest FROM wl_ingestion.decisions d
   WHERE d.tenant_id=NEW.tenant_id AND d.portfolio_id=NEW.portfolio_id AND d.set_id=NEW.set_id;
  IF TG_TABLE_NAME='decisions' THEN
   IF parent.state<>'RECONCILING' OR NEW.revision<>COALESCE(latest,0)+1 THEN REJECT; END IF;
   RETURN NEW;
  END IF;
  SELECT * INTO root FROM wl_ingestion.roots r WHERE r.tenant_id=NEW.tenant_id AND r.portfolio_id=NEW.portfolio_id;
  -- A preview pins the set after preparation and the current root generations.
  IF parent.state NOT IN ('NEEDS_MAPPING','CONFLICT','READY') OR
   (NEW.plan_bytes IS NOT NULL)<>(parent.state='READY') OR NEW.set_revision<>parent.revision OR
   NEW.decision_revision<>COALESCE(latest,0) OR root.tenant_id IS NULL OR
   (NEW.expected_accepted_generation,NEW.expected_mapping_generation,NEW.expected_control_generation)
    IS DISTINCT FROM (root.accepted_generation,root.mapping_generation,root.control_generation) OR
   (NEW.incarnation,NEW.restore_epoch,NEW.realm_digest) IS DISTINCT FROM
    (parent.incarnation,parent.restore_epoch,parent.realm_digest) OR
   NEW.expires_at>parent.expires_at THEN REJECT; END IF;
  RETURN NEW;

 ELSIF TG_TABLE_NAME IN ('quotas','instance_budgets') THEN
  IF TG_OP='INSERT' THEN
   IF NEW.used_count<>0 OR NEW.reserved_bytes<>0 OR NEW.lease_count<>0 OR NEW.outstanding_sets<>0 OR
    NEW.window_start>n THEN REJECT; END IF;
   RETURN NEW;
  ELSIF TG_OP<>'UPDATE' THEN REJECT; END IF;
  IF NEW.bucket<>OLD.bucket THEN REJECT; END IF;
  -- Instance rows have no scope columns, so read them only for quotas.
  IF TG_TABLE_NAME='quotas' THEN
   IF (NEW.tenant_id,NEW.portfolio_id) IS DISTINCT FROM (OLD.tenant_id,OLD.portfolio_id) THEN REJECT; END IF;
  END IF;
  -- Only the rate count resets with a 300s window; held bytes/leases/sets never do.
  IF NEW.window_start<>OLD.window_start THEN
   IF NEW.window_start<OLD.window_start+interval '300 seconds' OR NEW.window_start>n OR
    (NEW.reserved_bytes,NEW.lease_count,NEW.outstanding_sets) IS DISTINCT FROM
    (OLD.reserved_bytes,OLD.lease_count,OLD.outstanding_sets) THEN REJECT; END IF;
  ELSIF NEW.used_count<OLD.used_count THEN REJECT; END IF;
  RETURN NEW;

 ELSIF TG_TABLE_NAME='instance_state' THEN
  IF TG_OP='INSERT' THEN
   IF NEW.ready THEN REJECT; END IF;
   RETURN NEW;
  ELSIF TG_OP<>'UPDATE' THEN REJECT; END IF;
  -- Readiness covers one verified catalog and runtime profile.
  IF NEW.id<>OLD.id OR (OLD.ready AND NEW.ready AND
   (NEW.wrapper_catalog_bytes,NEW.wrapper_catalog_digest,NEW.runtime_profile_digest) IS DISTINCT FROM
   (OLD.wrapper_catalog_bytes,OLD.wrapper_catalog_digest,OLD.runtime_profile_digest)) THEN REJECT; END IF;
  RETURN NEW;

 ELSE
  IF TG_OP='INSERT' THEN RETURN NEW; ELSIF TG_OP<>'UPDATE' THEN REJECT; END IF;
  IF NEW.id<>OLD.id OR NEW.credential_epoch<OLD.credential_epoch OR
   ((NEW.login_role,NEW.peer_identity) IS DISTINCT FROM (OLD.login_role,OLD.peer_identity) AND
    NEW.credential_epoch=OLD.credential_epoch) THEN REJECT; END IF;
  RETURN NEW;
 END IF;
EXCEPTION WHEN OTHERS THEN
 IF SQLSTATE='22023' AND SQLERRM IN ('import_invalid','import_expired') THEN RAISE; END IF;
 RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
END $transition$;
REVOKE ALL ON FUNCTION wl_ingestion._transition_v1() FROM PUBLIC;
'''.replace('REJECT;', "RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';").replace(
    'EXPIRED;', "RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_expired';")


# Current-head storage guard. _references_v1 still proves source authority,
# economic group binding and observation order before the effects write.
HEAD_DDL = r'''
CREATE FUNCTION wl_ingestion._head_v1() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $head$
DECLARE target wl_ingestion.source_revisions%ROWTYPE; node wl_ingestion.source_revisions%ROWTYPE;
 scope jsonb; item jsonb; token text; ids text[]; path uuid[]; cursor_id uuid;
 reached boolean:=false;
BEGIN
 IF TG_TABLE_SCHEMA<>'wl_ingestion' OR TG_TABLE_NAME NOT IN ('activity_heads','snapshot_heads') OR
  TG_WHEN<>'BEFORE' OR TG_LEVEL<>'ROW' OR TG_OP NOT IN ('INSERT','UPDATE') THEN REJECT; END IF;

 IF TG_TABLE_NAME='activity_heads' THEN
  IF TG_OP='UPDATE' AND (NEW.tenant_id,NEW.portfolio_id,NEW.economic_group_id) IS DISTINCT FROM
   (OLD.tenant_id,OLD.portfolio_id,OLD.economic_group_id) THEN REJECT; END IF;
  SELECT * INTO target FROM wl_ingestion.source_revisions r WHERE r.tenant_id=NEW.tenant_id AND
   r.portfolio_id=NEW.portfolio_id AND r.id=NEW.revision_id;
  IF target.id IS NULL OR target.collection<>'records' OR
   target.accepted_change NOT IN ('original','correction','void') OR
   pg_catalog.convert_from(target.typed_bytes,'UTF8')::jsonb->>'record_type' IS DISTINCT FROM 'activity' OR
   NEW.active<>(target.accepted_change<>'void') THEN REJECT; END IF;
  IF TG_OP='UPDATE' AND NEW.revision_id=OLD.revision_id THEN
   IF NEW.active<>OLD.active THEN REJECT; END IF;
   RETURN NEW;
  END IF;
  -- Walk explicit accepted parents; an update must descend from the old head.
  path:=ARRAY[target.id]; cursor_id:=target.parent_id;
  WHILE cursor_id IS NOT NULL LOOP
   IF TG_OP='UPDATE' AND cursor_id=OLD.revision_id THEN reached:=true; EXIT; END IF;
   IF cursor_id=ANY(path) THEN CONFLICT; END IF;
   SELECT * INTO node FROM wl_ingestion.source_revisions r WHERE r.tenant_id=NEW.tenant_id AND
    r.portfolio_id=NEW.portfolio_id AND r.id=cursor_id;
   IF node.id IS NULL OR node.collection<>'records' OR
    node.accepted_change NOT IN (CASE WHEN TG_OP='INSERT' THEN 'original' ELSE 'correction' END,'correction') THEN
    CONFLICT; END IF;
   path:=path||node.id; cursor_id:=node.parent_id;
  END LOOP;
  IF TG_OP='UPDATE' AND (NOT reached OR NOT OLD.active OR target.accepted_change NOT IN ('correction','void')) THEN
   CONFLICT; END IF;
  -- Another group heading any revision of this chain, above, below or beside the
  -- target, would fork one economic history. Walk only this tree: up through
  -- parents, then down every branch by the parent index. UNION stops on cycles.
  IF EXISTS(WITH RECURSIVE mine(id) AS (
    SELECT NEW.revision_id UNION SELECT r.parent_id FROM wl_ingestion.source_revisions r JOIN mine ON r.id=mine.id
     WHERE r.tenant_id=NEW.tenant_id AND r.portfolio_id=NEW.portfolio_id AND r.parent_id IS NOT NULL
   ), tree(id) AS (
    SELECT id FROM mine UNION SELECT r.id FROM wl_ingestion.source_revisions r JOIN tree ON r.parent_id=tree.id
     WHERE r.tenant_id=NEW.tenant_id AND r.portfolio_id=NEW.portfolio_id
   ) SELECT 1 FROM tree JOIN wl_ingestion.activity_heads h ON h.revision_id=tree.id
    WHERE h.tenant_id=NEW.tenant_id AND h.portfolio_id=NEW.portfolio_id AND
     h.economic_group_id<>NEW.economic_group_id) THEN CONFLICT; END IF;
  RETURN NEW;
 END IF;

 IF TG_OP='UPDATE' AND (NEW.tenant_id,NEW.portfolio_id,NEW.key_digest,NEW.account_id,NEW.fact_kind,
   NEW.scope_bytes) IS DISTINCT FROM (OLD.tenant_id,OLD.portfolio_id,OLD.key_digest,OLD.account_id,
   OLD.fact_kind,OLD.scope_bytes) THEN REJECT; END IF;
 scope:=pg_catalog.convert_from(NEW.scope_bytes,'UTF8')::jsonb;
 IF pg_catalog.jsonb_typeof(scope)<>'object' OR NOT scope ?& ARRAY['tag','category','instrument_ids'] OR
  scope-ARRAY['tag','category','instrument_ids']<>'{}'::jsonb OR
  pg_catalog.jsonb_typeof(scope->'instrument_ids')<>'array' OR
  pg_catalog.jsonb_array_length(scope->'instrument_ids')>2048 OR
  NOT (scope->'category' IN ('null'::jsonb,'"SECURITY"'::jsonb,'"CASH"'::jsonb,'"CRYPTO"'::jsonb,
   '"UNSUPPORTED"'::jsonb)) THEN REJECT; END IF;
 ids:=ARRAY[]::text[];
 FOR item IN SELECT value FROM pg_catalog.jsonb_array_elements(scope->'instrument_ids') LOOP
  token:=item#>>'{}';
  -- Canonical IDs are sorted and unique; each names an existing scoped instrument.
  IF pg_catalog.jsonb_typeof(item)<>'string' OR token COLLATE "C" !~
    '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' OR
   token='00000000-0000-0000-0000-000000000000' OR
   (pg_catalog.cardinality(ids)>0 AND token COLLATE "C"<=ids[pg_catalog.cardinality(ids)] COLLATE "C") OR
   NOT EXISTS(SELECT 1 FROM wl_pg.instruments i WHERE i.tenant_id=NEW.tenant_id AND
    i.portfolio_id=NEW.portfolio_id AND i.id=token::uuid) THEN REJECT; END IF;
  ids:=ids||token;
 END LOOP;
 IF NOT ((scope->>'tag'='all' AND scope->'category'='null'::jsonb AND pg_catalog.cardinality(ids)=0) OR
   (scope->>'tag'='category' AND scope->'category'<>'null'::jsonb AND pg_catalog.cardinality(ids)=0) OR
   (scope->>'tag'='instruments' AND scope->'category'='null'::jsonb AND pg_catalog.cardinality(ids)>0)) OR
  -- The key is the declared SnapshotHeadKey preimage, not a caller label.
  NEW.key_digest<>pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(
   pg_catalog.jsonb_build_object('version',1,'tenant_id',NEW.tenant_id::text,
    'portfolio_id',NEW.portfolio_id::text,'account_id',NEW.account_id::text,
    'record_kind','holdings','instrument_scope',scope))),'hex') THEN REJECT; END IF;
 IF EXISTS(SELECT 1 FROM wl_ingestion.source_revisions r WHERE r.tenant_id=NEW.tenant_id AND
   r.portfolio_id=NEW.portfolio_id AND r.id IN (NEW.latest_revision_id,NEW.complete_base_revision_id) AND
   (r.collection<>'snapshots' OR r.accepted_change NOT IN ('original','correction'))) OR
  NOT EXISTS(SELECT 1 FROM wl_ingestion.source_revisions r WHERE r.tenant_id=NEW.tenant_id AND
   r.portfolio_id=NEW.portfolio_id AND r.id=NEW.latest_revision_id) OR
  (NEW.complete_base_revision_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM wl_ingestion.source_revisions r
   WHERE r.tenant_id=NEW.tenant_id AND r.portfolio_id=NEW.portfolio_id AND r.id=NEW.complete_base_revision_id))
  THEN REJECT; END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.complete_base_revision_id<>NEW.latest_revision_id THEN CONFLICT; END IF;
  RETURN NEW;
 END IF;
 IF NEW.latest_revision_id=OLD.latest_revision_id THEN
  IF NEW.complete_base_revision_id IS DISTINCT FROM OLD.complete_base_revision_id THEN CONFLICT; END IF;
  RETURN NEW;
 END IF;
 -- A newer complete observation replaces the base; a partial one preserves it.
 IF NEW.complete_base_revision_id IS DISTINCT FROM OLD.complete_base_revision_id AND
  NEW.complete_base_revision_id IS DISTINCT FROM NEW.latest_revision_id THEN CONFLICT; END IF;
 SELECT * INTO target FROM wl_ingestion.source_revisions r WHERE r.tenant_id=NEW.tenant_id AND
  r.portfolio_id=NEW.portfolio_id AND r.id=NEW.latest_revision_id;
 IF target.accepted_change='correction' AND target.parent_id<>OLD.latest_revision_id THEN CONFLICT; END IF;
 -- The head cannot move back onto an ancestor of its current observation.
 path:=ARRAY[OLD.latest_revision_id]; cursor_id:=OLD.latest_revision_id;
 LOOP
  SELECT r.parent_id INTO cursor_id FROM wl_ingestion.source_revisions r WHERE r.tenant_id=NEW.tenant_id AND
   r.portfolio_id=NEW.portfolio_id AND r.id=cursor_id;
  EXIT WHEN cursor_id IS NULL;
  IF cursor_id=NEW.latest_revision_id OR cursor_id=ANY(path) THEN CONFLICT; END IF;
  path:=path||cursor_id;
 END LOOP;
 RETURN NEW;
EXCEPTION WHEN OTHERS THEN
 IF SQLSTATE='22023' AND SQLERRM IN ('import_invalid','import_conflict') THEN RAISE; END IF;
 RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';
END $head$;
REVOKE ALL ON FUNCTION wl_ingestion._head_v1() FROM PUBLIC;
'''.replace('REJECT;', "RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_invalid';").replace(
    'CONFLICT;', "RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='import_conflict';")


def _enum(column, choices):
    return column + ' IN (' + ','.join("'" + x + "'" for x in choices) + ')'


def _json_bytes(column, maximum, digest_column=None, nullable=False):
    result = [f'pg_catalog.octet_length({column}) BETWEEN 1 AND {maximum}',
              f'{column}=wl_ingestion._canonical_v1(pg_catalog.convert_from({column},\'UTF8\')::jsonb)']
    if digest_column:
        result.append(f'{digest_column}=pg_catalog.encode(pg_catalog.sha256({column}),\'hex\')')
    # Optional payloads remain nullable while every nonnull payload satisfies the
    # same restrictions. The explicit branch keeps NULL out of _canonical_v1,
    # which rejects NULL instead of returning unknown to the CHECK.
    if nullable:
        return [f'{column} IS NULL OR (' + ' AND '.join('(' + x + ')' for x in result) + ')']
    return result


def _value_rules(table):
    name = table['name']
    result = []
    for column in table['columns']:
        key, kind = column['name'], column['type']
        if kind == 'uuid':
            result.append(key + "<>'00000000-0000-0000-0000-000000000000'::uuid")
        elif kind == 'bigint':
            result.append(key + '>=0')
        elif kind == 'timestamptz':
            result.append(f'pg_catalog.isfinite({key})')
        elif kind == 'text':
            if (key in {'digest', 'installation_id'} or key.endswith('_digest')
                    or key.endswith('_version') and key != 'format_version'
                    or key == 'source_key' and name == 'source_revisions'):
                # source_revision is source text, not a digest. SourceKey's hash
                # is never accepted without the exact selector from its input.
                result.append(key + " COLLATE \"C\" ~ '^[0-9a-f]{64}$'")
            else:
                result.append(f'pg_catalog.length({key})<=4096')
    specific = {
        'sets': [
            _enum('state', ('RECEIVING','NORMALIZING','RECONCILING','NEEDS_MAPPING','CONFLICT',
                            'READY','COMMITTED','REJECTED','CANCELLED','EXPIRED')),
            'revision>=1', 'member_count BETWEEN 1 AND 4', 'actor_user_id=tenant_id',
            "expires_at=created_at+interval '86400 seconds'", 'reserved_bytes<=16777216',
            "(state='COMMITTED')=(receipt_id IS NOT NULL)",
            _enum('cleanup_state', ('not_needed','pending','complete','failed'))],
        'members': [
            'ordinal BETWEEN 0 AND 3', 'raw_bytes BETWEEN 1 AND 10485760',
            'context_bytes IS NULL OR pg_catalog.octet_length(context_bytes) BETWEEN 1 AND 1048576',
            "context_bytes IS NULL OR context_digest=pg_catalog.encode(pg_catalog.sha256(context_bytes),'hex')",
            'availability_generation>=1',
            _enum('state', ('waiting','receiving','normalizing','admitted','reupload_required',
                            'rejected','cancelled','expired','committed'))],
        'leases': [
            _enum('work_kind', ('normalize','prepare','cleanup')), 'attempt>=1', 'fence>=1',
            _enum('state', ('offered','active','finished','expired','cancelled')),
            "(work_kind='normalize')=(member_id IS NOT NULL)", 'expires_at>=created_at',
            '(claim_request_id IS NULL)=(claim_request_digest IS NULL)',
            '(last_request_id IS NULL)=(last_request_digest IS NULL)',
            '(last_request_id IS NULL)=(last_result_bytes IS NULL)'],
        'stages': ["codec='minimal-evidence-v1'", 'purge_at>=created_at'],
        'decisions': ['revision>=1','purge_at>=created_at'],
        'previews': ['set_revision>=1', '(plan_bytes IS NULL)=(plan_digest IS NULL)',
            'pg_catalog.octet_length(review_bytes)+COALESCE(pg_catalog.octet_length(plan_bytes),0)<=16777216',
            'purge_at>=created_at'],
        'accepted_inputs': ["codec='minimal-evidence-v1'"],
        'accepted_plans': ["codec='acceptance-plan-v1'"],
        'source_revisions': [
            _enum('collection', ('records','coverage','snapshots','membership')),
            _enum('source_change', ('original','correction','void')),
            _enum('accepted_change', ('original','correction','void','mirror','historical')),
            "pg_catalog.length(source_revision) BETWEEN 1 AND 256",
            "local_id COLLATE \"C\" ~ '^(0|[1-9][0-9]{0,7})$'",
            "accepted_change NOT IN ('correction','void') OR parent_id IS NOT NULL"],
        'snapshot_heads': ["fact_kind='holdings'"],
        'mappings': ['revision>=1', _enum('entity_kind', ('account','instrument','issuer')),
            "(entity_kind='account' AND account_id IS NOT NULL AND account_version IS NOT NULL "
            "AND instrument_id IS NULL AND instrument_version IS NULL AND issuer_id IS NULL AND issuer_version IS NULL) OR "
            "(entity_kind='instrument' AND instrument_id IS NOT NULL AND instrument_version IS NOT NULL "
            "AND account_id IS NULL AND account_version IS NULL AND issuer_id IS NULL AND issuer_version IS NULL) OR "
            "(entity_kind='issuer' AND issuer_id IS NOT NULL AND issuer_version IS NOT NULL "
            "AND account_id IS NULL AND account_version IS NULL AND instrument_id IS NULL AND instrument_version IS NULL)"],
        'authority_links': ['revision>=1', _enum('decision_kind', ('mirror','independent','authority','historical_only')),
            "(right_revision_id IS NULL)=(decision_kind='historical_only')", 'left_revision_id<>right_revision_id',
            'pg_catalog.length(evidence_reference) BETWEEN 1 AND 256'],
        'lineage': [_enum('collection', ('records','coverage','snapshots','membership')),
            "local_id COLLATE \"C\" ~ '^(0|[1-9][0-9]{0,7})$'"],
        'receipts': [_enum('operation_kind', ('CREATE','DECISIONS','CANCEL','ACCEPT')),
            "(operation_kind='ACCEPT')=(accepted_plan_id IS NOT NULL)",
            "(operation_kind='ACCEPT')=(plan_digest IS NOT NULL)"],
        'audit': [_enum('action', ('CREATED','DECIDED','CANCELLED','ACCEPTED','NO_CHANGE'))],
        'outbox': ["version=1", "type='facts.accepted.v1'", 'dispatched_at IS NULL'],
        'quotas': [_enum('bucket', ('read','control','raw','storage')),
            'reserved_bytes<=134217728','lease_count<=1','outstanding_sets<=8'],
        'instance_budgets': [_enum('bucket', ('read','control','raw','storage')),
            'reserved_bytes<=1073741824','lease_count<=4','outstanding_sets<=64'],
        'instance_state': ['id=1'],
        'workers': ['credential_epoch>=1','pg_catalog.length(peer_identity) BETWEEN 1 AND 256'],
    }
    result.extend(specific.get(name, ()))
    payloads = {
        'leases': [('last_result_bytes', 16384, None)],
        'stages': [('minimal_bytes', 4194304, 'digest')],
        'decisions': [('canonical_bytes', 16777216, 'digest')],
        'previews': [('plan_bytes', 16777216, 'plan_digest'), ('review_bytes', 16777216, 'review_digest')],
        'accepted_inputs': [('canonical_bytes', 4194304, 'digest')],
        'accepted_plans': [('canonical_bytes', 16777216, 'digest')],
        'source_revisions': [('typed_bytes', 4194304, 'typed_digest')],
        'snapshot_heads': [('scope_bytes', 4194304, None)],
        'lineage': [('source_claim_bytes', 4194304, None)],
        'receipts': [('result_bytes', 16384, None)],
        'outbox': [('payload_bytes', 4194304, 'payload_digest')],
        'instance_state': [('wrapper_catalog_bytes', 4194304, 'wrapper_catalog_digest')],
    }
    optional = {x['name'] for x in table['columns'] if x['nullable']}
    for column, maximum, hash_column in payloads.get(name, ()):
        result.extend(_json_bytes(column, maximum, hash_column, column in optional))
    return result


def tables_ddl():
    """Render tables/constraints only; no automatic migration or runtime grants."""
    spec = inventory()
    result = ['CREATE SCHEMA wl_ingestion;', 'REVOKE ALL ON SCHEMA wl_ingestion FROM PUBLIC;',
              CANONICAL_DDL]
    for table in spec['tables']:
        name = table['name']
        columns = []
        for item in table['columns']:
            key, kind = item['name'], item['type']
            generated = ''
            if name == 'mappings' and key in {'entity_id', 'entity_version'}:
                suffix = '_id' if key == 'entity_id' else '_version'
                generated = ' GENERATED ALWAYS AS (COALESCE(' + ','.join(
                    x + suffix for x in ('account','instrument','issuer')) + ')) STORED'
            columns.append(key + ' ' + kind + generated + ('' if item['nullable'] else ' NOT NULL'))
        for index in spec['indexes_and_unique_constraints']:
            if index['table'] == name and index['kind'] in {'PRIMARY_KEY', 'UNIQUE'}:
                phrase = 'PRIMARY KEY' if index['kind'] == 'PRIMARY_KEY' else 'UNIQUE'
                columns.append('CONSTRAINT ' + index['name'] + ' ' + phrase +
                               '(' + ','.join(index['columns']) + ')')
        rules = _value_rules(table)
        columns.append('CONSTRAINT ' + name + '_values_ck CHECK(' +
                       ' AND '.join('(' + rule + ')' for rule in rules) + ')')
        result.append('CREATE TABLE wl_ingestion.' + name + '(\n ' + ',\n '.join(columns) + '\n);')
        if table['scope'] == 'tenant':
            result.append('ALTER TABLE wl_ingestion.' + name + ' ENABLE ROW LEVEL SECURITY;')
            result.append('ALTER TABLE wl_ingestion.' + name + ' FORCE ROW LEVEL SECURITY;')
    for fk in spec['foreign_keys']:
        result.append('ALTER TABLE wl_ingestion.' + fk['table'] + ' ADD CONSTRAINT ' + fk['name'] +
            ' FOREIGN KEY(' + ','.join(fk['columns']) + ') REFERENCES ' + fk['target'] +
            '(' + ','.join(fk['target_columns']) + ') ON UPDATE NO ACTION ON DELETE NO ACTION'
            ' DEFERRABLE INITIALLY DEFERRED;')
    predicates = {
        'UNIQUE_PARTIAL_NORMALIZE_ACTIVE': "work_kind='normalize' AND state IN ('offered','active')",
        'UNIQUE_PARTIAL_PREPARE_ACTIVE': "work_kind='prepare' AND state IN ('offered','active')",
        'UNIQUE_PARTIAL_CLAIM_REQUEST_NOT_NULL': 'claim_request_id IS NOT NULL',
    }
    for index in spec['indexes_and_unique_constraints']:
        if index['kind'] in {'PRIMARY_KEY','UNIQUE'}:
            continue
        result.append('CREATE ' + ('' if index['kind'] == 'INDEX' else 'UNIQUE ') +
            'INDEX ' + index['name'] + ' ON wl_ingestion.' + index['table'] +
            '(' + ','.join(index['columns']) + ')' +
            (' WHERE ' + predicates[index['kind']] if index['kind'] in predicates else '') + ';')
    result.append('REVOKE ALL ON ALL TABLES IN SCHEMA wl_ingestion FROM PUBLIC;')
    return '\n'.join(result)


def policies_ddl(runtime_role, owner_role):
    """Render explicit forced-RLS policies for verified migration-owned roles."""
    for role in (runtime_role, owner_role):
        if (type(role) is not str or role == 'public'
                or not re.fullmatch(r'[a-z_][a-z0-9_]{0,62}', role, re.ASCII)):
            raise ValueError('Invalid migration role')
    if runtime_role == owner_role:
        raise ValueError('Separate migration role required')
    statements = []
    for name in TENANT_TABLES:
        statements.extend([
            f'CREATE POLICY runtime_scope ON wl_ingestion.{name} TO "{runtime_role}" USING('
            "tenant_id=NULLIF(pg_catalog.current_setting('ledger.tenant_id',true),'')::uuid AND "
            "portfolio_id=NULLIF(pg_catalog.current_setting('ledger.portfolio_id',true),'')::uuid);",
            f'CREATE POLICY operator_scope ON wl_ingestion.{name} TO "{owner_role}" USING(true) WITH CHECK(true);',
        ])
    return '\n'.join(statements)


def triggers_ddl():
    """Install only after every exact guard function has been independently checked."""
    statements = []
    for trigger in inventory()['triggers']:
        statements.append('CREATE TRIGGER ' + trigger['name'] + ' BEFORE ' +
            ' OR '.join(trigger['events']) + ' ON wl_ingestion.' + trigger['table'] +
            ' FOR EACH ROW EXECUTE FUNCTION wl_ingestion.' + trigger['function'] + '();')
    return '\n'.join(statements)
