"""Installed journey-routes release -> trip-items source-only 69/9 update."""
from deploy.build_journey_routes_release import RUNTIME_ADDITIONS, FRONTEND_TESTS as ROUTE_TESTS

BASELINE = 'journey-routes-r1-assistant-trip-items'
KIND = 'assistant-trip-items-release-package'
INSTALLED_SOURCE = 'a9d3261116a5ad83fafb28ebda168bcd628367b4'
INSTALLED_TREE = 'c82b4e24a4e8093290611ac5e09701cb7f406c83'
PARENT_IMAGE = 'sha256:9a966634bb220e7ce2a071fa130f011414b4c413eeecac0f9b3d3eccd5fb5bbc'
OLD_MANIFEST = '0ec456641fc66d9e5a71c067e7731479fa5fd6fb7a05aa4ee84b1b27b5e7b070'
OLD_PACKAGE = 'c54dec688fbe99fef64b00ec92344d599259e134f328dbe49f0315b397dd22ef'
AUDIT_SHA256 = 'a7742fb97173fcf3024c4a81ea85cfc433067af6939ade507a66447c9d147e61'
DOCKER_BEFORE = DOCKER_AFTER = '36f5d699823890c26dbc243010f584c5aa5d44c109bd6e63b705e9e025a2a90b'
COPY_BEFORE = COPY_AFTER = b'COPY journey_routes.py ./\n'
FRONTEND_TESTS = ROUTE_TESTS | {'frontend/tests/journeyBriefItems.test.mjs'}
CHANGED_ROOT_FILES = frozenset({'home_assistant.py', 'README.md'})
SCHEMA_BEFORE = SCHEMA_AFTER = (69, 9)
