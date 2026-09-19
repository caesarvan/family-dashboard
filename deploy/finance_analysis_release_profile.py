"""Reviewed 61/9 -> 66/9 release contract; historical baselines stay immutable."""
BASELINE = 'order-inventory-r1-finance-analysis'
KIND = 'finance-analysis-release-package'
INSTALLED_SOURCE = 'fe0c56ba5537e70207ae5b98213e3daa1daef95a'
PARENT_IMAGE = 'sha256:32905e70879d28f36b0e584d69f03434e4a1bf38e580c0ca1aeb1ed7ae3a3cc6'
OLD_MANIFEST = 'c4d5ecc38675e6d9d97569664cb8141d4cfd030f52c6086449b8ea8d84ebf080'
AUDIT_SHA256 = 'feee58ab01565aa0ed061edf013d46f7414b369e7b36b811ae849f27a18c2625'
DOCKER_BEFORE = '6ed4fa73f1bdc7f0c1b0c2d660610434648dadb44890abb4d493fe46b6e904ff'
COPY_BEFORE = b'COPY finance_source_bridge.py finance_accounts.py journey_time.py journey_reschedule.py ./\n'
COPY_AFTER = COPY_BEFORE + b'COPY finance_analysis.py finance_fx.py ./\n'
RUNTIME_ADDITIONS = frozenset({'inventory_sources.py', 'finance_analysis.py', 'finance_fx.py'})
FRONTEND_TESTS = frozenset({'frontend/tests/inventoryFollowup.test.mjs',
    'frontend/tests/inventorySources.test.mjs', 'frontend/tests/financeAnalysis.test.mjs'})
CHANGED_ROOT_FILES = frozenset({'app.py', 'data_portability.py', 'finance_analysis.py',
    'finance_fx.py', 'Dockerfile', 'README.md'})
SCHEMA_BEFORE = (61, 9)
SCHEMA_AFTER = (66, 9)
DOCKER_AFTER = 'b1668b82416b3afa86ed8dc138fd6183204faeb6b0f89871381f9fb633d86116'
