"""Fixed installed trip-change release -> finance-query source-only 66/9 update."""
BASELINE = 'assistant-trip-change-r1-finance-query'
KIND = 'assistant-finance-query-release-package'
INSTALLED_SOURCE = '4c5988874d9f2b206030f6cd42864013db62454b'
INSTALLED_TREE = '8647c0398949d063b3e1a8aef10647b6a69e3a74'
PARENT_IMAGE = 'sha256:5fc52d2cef49c1fa854bd1e34faf23dc661b8e4ed7822b5e6763bf5798f42dce'
OLD_MANIFEST = 'aa116533c6c725f8499f10bc6ac01c55645b69c659b1ae970a143eb1ae7b0696'
OLD_PACKAGE = 'e2ab1963fb5a5d013d7c2cce718d764273ee55ea8e3b622be7cf4b9222d4f035'
AUDIT_SHA256 = 'd9788b0434e49c45cfae59d065eedae7778383c341bcc7f05521bef6fd7ce2c3'
DOCKER_BEFORE = '5856bdc2ef145f133084c879d92714f9aaa48301b6af5c941abaab64ef6895bd'
DOCKER_AFTER = 'f68324febf8438eb7e0ed1277998e33510c948503a8cf9c633062ba8027cdefb'
COPY_BEFORE = b'COPY assistant_trip_intent.py assistant_trip_change_api.py ./\n'
COPY_AFTER = COPY_BEFORE + b'COPY assistant_finance_query.py ./\n'
RUNTIME_ADDITIONS = frozenset({'inventory_sources.py', 'finance_analysis.py', 'finance_fx.py',
                              'assistant_trip_intent.py', 'assistant_trip_change_api.py', 'assistant_finance_query.py'})
FRONTEND_TESTS = frozenset({'frontend/tests/inventoryFollowup.test.mjs', 'frontend/tests/inventorySources.test.mjs',
                          'frontend/tests/financeAnalysis.test.mjs', 'frontend/tests/assistantTripChange.test.mjs',
                          'frontend/tests/assistantFinanceQuery.test.mjs'})
CHANGED_ROOT_FILES = frozenset({'app.py', 'finance_hub.py', 'assistant_finance_query.py', 'Dockerfile', 'README.md'})
SCHEMA_BEFORE = SCHEMA_AFTER = (66, 9)
