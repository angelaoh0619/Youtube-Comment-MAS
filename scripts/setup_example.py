"""Install the bundled public example without model calls or overwriting local data."""
import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from recorded_example import RecordedData
from web_data import DEFAULT_DATA

FILES = (
    '01_filter/filtered.json',
    '02_group/groups.json',
    '03_agents/agents.json',
    '04_web/catalog.json',
    '04_web/translations.json',
    '04_web/example_journey.json',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=DEFAULT_DATA,
                        help='Destination analysis folder (defaults to the built-in example location)')
    args = parser.parse_args()
    source = ROOT / 'examples/sample-analysis'
    # Validate the bundle, source links, exact quotes and prepared conversations.
    # RecordedData uses NoModel, so setup cannot make a paid model request.
    RecordedData(source).catalog()
    conflicts = [name for name in FILES if (args.data/name).exists()
                 and (args.data/name).read_bytes() != (source/name).read_bytes()]
    if conflicts:
        raise SystemExit('Existing analysis files differ: ' + ', '.join(conflicts)
                         + '. Choose a different --data folder to preserve your local work.')
    for name in FILES:
        target = args.data/name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source/name, target)
    print(f'Public example ready at {args.data}. No API calls were made.')


if __name__ == '__main__':
    main()
