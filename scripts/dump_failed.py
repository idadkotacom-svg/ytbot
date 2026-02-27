import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.scheduler import Scheduler
from pprint import pprint

def main():
    s = Scheduler()
    manager = s.sheets
    
    failed = [row for row in manager.sheet.get_all_values()[1:] if len(row) > 6 and row[6].strip().lower() == 'failed']
    with open("failed_dump.txt", "w", encoding="utf-8") as f:
        pprint(failed, stream=f)
    print("Done")

if __name__ == "__main__":
    main()
