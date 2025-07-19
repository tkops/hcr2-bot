import subprocess
from datetime import datetime
from dateutil.relativedelta import relativedelta

START_SEASON = 1
TOTAL_SEASONS = 100
START_DATE = datetime(2021, 5, 1)
DIVISION = "DIV1"

def generate_season_data():
    for i in range(TOTAL_SEASONS):
        season_id = START_SEASON + i
        start = START_DATE + relativedelta(months=i)
        name = start.strftime("%b %y")  # z. B. "May 21"
        start_str = start.strftime("%Y-%m-%d")
        yield (season_id, name, start_str)

def add_seasons(dry_run=False):
    for sid, name, start in generate_season_data():
        cmd = ["python3", "hcr2.py", "season", "add", str(sid), name, start, DIVISION]
        if dry_run:
            print("DRY-RUN:", " ".join(cmd))
        else:
            result = subprocess.run(cmd, capture_output=True, text=True)
            print(result.stdout.strip())

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Show commands without executing")
    args = parser.parse_args()

    add_seasons(dry_run=args.dry_run)

