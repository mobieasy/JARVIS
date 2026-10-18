"""Generate a private local config without copying credentials into source."""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--workspace', required=True, type=Path)
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
if args.output.exists():
    parser.error('Output already exists; review it instead of overwriting it')
root = Path(__file__).resolve().parents[1]
config = json.loads((root / 'config/openclaw.example.json').read_text())
config['agents']['defaults']['workspace'] = str(args.workspace.resolve())
args.workspace.mkdir(parents=True, exist_ok=True)
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
args.output.chmod(0o600)
print('Private local config created. Set provider and gateway secrets in your shell.')
