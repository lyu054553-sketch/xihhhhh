"""Import a validated synthetic scenario into an explicitly selected Store."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.hackathon_data import RetailFactService, migrate
from backend.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Explicit target SQLite path; no production default")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--branch")
    parser.add_argument("--as-of")
    args = parser.parse_args()
    store = Store(args.db)
    try:
        with store.transaction() as tx:
            migrate(tx)
            report = RetailFactService(store).import_scenario(args.tenant, args.scenario, args.branch, as_of=args.as_of, tx=tx)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        store.conn.close()


if __name__ == "__main__":
    main()
