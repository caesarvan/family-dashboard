"""Assemble a separate offline finance-query candidate; never stage or activate."""
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy import assistant_finance_query_release_package as package
from deploy import assistant_finance_query_release_controller as controller
from deploy import assistant_trip_change_release_plan as shared

OPERATORS = controller.SPEC.operators


def assemble(package_dir, package_sha256, build_dir, build_sha256, validation_dir,
             validation_sha256, reviews, reviews_sha256, candidate):
    return shared._assemble(package_dir, package_sha256, build_dir, build_sha256, validation_dir,
                            validation_sha256, reviews, reviews_sha256, candidate,
                            package=package, controller_type=controller.Controller)


def main(argv=None):
    shared.main(argv, assemble_fn=assemble)


if __name__ == '__main__':
    main()
