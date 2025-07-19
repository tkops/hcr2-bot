import csv
import sys
import subprocess
from collections import defaultdict
from datetime import datetime

INPUT_FILE = "all.tsv"
DEFAULT_DIVISION = "DIV1"

def parse_seasons_from_tsv(file_path):
    seasons = {}

    with open(file_path, encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        for row in reader:
            if len(row) < 15:
                continue

            try:
                date_str = row[13].strip()
                season = int(row[14].strip())
                if not date_str:
                    continue

                date = datetime.strptime(date_str, "%Y-%m-%d")
                month_start = date.replace(day=1)
                if season not in seasons:
                    seasons[season] = month_start.strftime("%Y-%m-%d")
            except Exception:
                continue

    return seasons


def main():
    dry_run = "--dry-run" in sys.argv
    seasons = parse_seasons_from_tsv(INPUT_FILE)

    for number in sorted(seasons):
        name = datetime.strptime(seasons[number], "%Y-%m-%d").strftime("%b %y")
        cmd = ["python3", "hcr2.py", "season", "add", str(number), name, seasons[number], DEFAULT_DIVISION]

        if dry_run:
            print("🔸 " + " ".join(cmd))
        else:
            subprocess.run(cmd)

if __name__ == "__main__":
    main()

