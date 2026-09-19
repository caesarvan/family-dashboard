"""Fixed asset-analysis production baseline; source-only 66/9 preservation."""
BASELINE = 'finance-analysis-r1-assistant-trip-change'
KIND = 'assistant-trip-change-release-package'
INSTALLED_SOURCE = 'f25357f935d64774922efa68d42a2ba41bb18037'
INSTALLED_TREE = '1efb6a439fd8fdd95a1af5c4958296452ccfcb71'
PARENT_IMAGE = 'sha256:21625d6e2d9768ba48cca35100bb8bf02c1c4146afa6b7ad25b9b72cb559c1d2'
OLD_MANIFEST = '30d5fe729ab9c407c43d8de3fa0129acd9c1e8ec2aa3e9473c5fb5e2485cb5f4'
OLD_PACKAGE = 'eebaec9fdf903591ce86844ff16912a0a79e050c662404afa4f9e907328a5e66'
AUDIT_SHA256 = '2c1afe7d812e026477033bfc6e01bb3d4939ff8d3ef940759dfcfcbb4ebf948b'
DOCKER_BEFORE = 'b1668b82416b3afa86ed8dc138fd6183204faeb6b0f89871381f9fb633d86116'
COPY_BEFORE = b'COPY household_spaces.py journey_workflows.py finance_hub.py home_assistant.py ./\n'
COPY_AFTER = COPY_BEFORE + b'COPY assistant_trip_intent.py assistant_trip_change_api.py ./\n'
# Additions to the historical prepare_release allowlist include the installed
# inventory/analysis modules as well as this batch's two new runtime modules.
RUNTIME_ADDITIONS = frozenset({'inventory_sources.py', 'finance_analysis.py', 'finance_fx.py',
    'assistant_trip_intent.py', 'assistant_trip_change_api.py'})
FRONTEND_TESTS = frozenset({'frontend/tests/inventoryFollowup.test.mjs',
    'frontend/tests/inventorySources.test.mjs', 'frontend/tests/financeAnalysis.test.mjs',
    'frontend/tests/assistantTripChange.test.mjs'})
CHANGED_ROOT_FILES = frozenset({'app.py', 'assistant_trip_intent.py',
    'assistant_trip_change_api.py', 'Dockerfile', 'README.md'})
SCHEMA_BEFORE = SCHEMA_AFTER = (66, 9)
DOCKER_AFTER = '5856bdc2ef145f133084c879d92714f9aaa48301b6af5c941abaab64ef6895bd'
