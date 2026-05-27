"""Shared test fixtures and constants for the categorize.py integration tests.

Kept in a separate module (not conftest.py) so test files can import it directly
without relying on conftest import semantics.
"""

# Minimal standing-rules.yaml that satisfies categorize.py startup validation.
# Includes all B2-SR1 sections (p2-11..p2-16) so integration tests that run
# categorize.py as a subprocess do not fail at the startup loaders.
# Keep in sync with the section list in lib/standing_rules.py B2-SR1 loaders.
MINIMAL_STANDING_RULES_YAML = """\
_meta:
  schema_version: 1
  rule_set_version: '1.0-fixture'
supplier_rules:
  status: active
expenses_schema:
  status: active
  new_columns: [data_caixa, data_competencia, supplier_canonical, tags]
  legacy_column_removed: subcategory
name_canonicalization:
  status: active
  default_style: titlecase_accented
  exceptions: []
competencia_rules:
  status: active
  cc_installments:
    installment_1: row_date
    installment_n: 'row_date - (N-1) months'
tag_semantics:
  status: active
  reembolsavel:
    type: expense
    amount_sign: negative
  reembolso:
    type: receipt
    amount_sign: positive
tag_application_rules:
  status: active
  care_plus_receipt:
    condition: "supplier_canonical == 'Care Plus' AND amount > 0"
    always_apply: [reembolso, seguros]
  automotive_insurance:
    suppliers: [SUHAI, HDI, 'Tokio Marine']
    category: carro
    tag: seguros
family_canonicals:
  status: active
  members: [Pai, Mae, Irmao, Irma]
  rule: 'PIX to/from family uses relationship name'
tag_coverage:
  status: active
  rule_80_percent:
    target: 0.80
    scope: per_category
    fallback: include_if_under_10_vendors
  gate:
    untagged_amount_threshold_brl: 200
    action_if_below: auto_loop_to_step_4b
cross_month_propagation:
  status: active
  enabled: true
  trigger: new_canonical_or_category_or_tag_in_current_month
  scope: prior_completed_months
  action: propose_retroactive_in_batch
pass_2_rules:
  status: active
  scope_filter:
    - 'is_boundary_day(data_caixa)'
    - 'supplier.movable == true'
    - "source_type != 'fatura'"
  default_action: keep
  immutable_fields: [data_caixa]
  mutable_fields: [data_competencia]
  backfill_default_movable: false
cash_expense:
  status: active
  source_type: dinheiro
  supplier_canonical: Cash
  match_confidence: manual
  bank: manual
  tags: ''
investment_rules:
  status: active
  ledger_immutability:
    append_only: true
    applies_to: [orders.csv, proventos.csv, balcao.csv]
  code_migration_handling:
    type: separate_ledger
    file: config/corrections/code_migrations.csv
    filter_in_calculate: true
    known_migrations: {}
  field_ownership:
    CURATED: [name, issuer]
    SOURCE_BOUND: {}
    DERIVED: [manager, asset_class]
rf_naming:
  status: active
  format: '{Tipo} {Emissor}'
  tipo_enum: ['Deb. Inc.', 'Deb.', CRA, CRI, LCA, LCI]
  emissor_capitalization: 'Title case; exclude S/A; Ltda suffixes'
yoc:
  status: active
  lifetime: 'sum(income_proventos) / cost_basis'
  ttm: 'sum(income_proventos_last_365) / cost_basis'
  excluded_from_income: [fracao]
options_rules:
  status: active
  expiration_auto_generation:
    condition: buy_without_matching_sell_by_expiration
    action: generate_expiracao_row
    ratio: '1:0'
  price_fetching: skip
gates:
  status: active
  step_01_file_identification:
    user_confirmation_required: true
  step_3d_unmatched_rows:
    enforcement: no_silent_skip
    action: enumerate_all_unmatched
  step_5_5_coverage:
    threshold: 0.80
    action_if_below: auto_loop_to_step_4b
batch_ui:
  status: active
  categories:
    fields: [description, value, date, available_options]
    allow_new_creation: true
  suppliers:
    fields: [canonical, aliases, movable, default_category]
    conditional_required: movable_hint == mixed
  tags:
    one_row_one_decision: true
    options: [accept, merge, reject]
file_conventions:
  status: active
  amounts:
    credit_card: NEGATIVE
  transactions:
    iof: separate_transaction
  csv_encoding:
    tag_column_separator: ';'
    parser: lib.tags.parse_tag_column
    serializer: lib.tags.serialize_tag_column
communication:
  status: active
  language: 'português brasileiro'
  applies_to: 'all user-facing messages'
  technical_terms: 'English (function names, paths, column identifiers)'
"""
