"""Fixed finance flow entry into the reviewed five-service 73/9 73-to-75 migrationr."""
from pathlib import Path
import sys
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy import media_video_release_controller as shared


class Controller(shared.Controller):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, mode='journey-finance-73-to-75')


def main(argv=None):
    return shared.main(argv, mode='journey-finance-73-to-75')


if __name__ == '__main__': main()
