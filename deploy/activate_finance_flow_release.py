"""Fixed finance flow entry into the reviewed five-service 73/9 source updater."""
from pathlib import Path
import sys
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy import media_video_release_controller as shared


class Controller(shared.Controller):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, mode='finance-flow-source-update')


def main(argv=None):
    return shared.main(argv, mode='finance-flow-source-update')


if __name__ == '__main__': main()
