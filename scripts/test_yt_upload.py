import logging
logging.basicConfig(level=logging.INFO)
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.scheduler import Scheduler

def reproduce():
    s = Scheduler()
    manager = s.sheets
    
    all_rows = manager.sheet.get_all_values()
    
    target_row = None
    for i, row in enumerate(all_rows[1:], start=2):
        print(i, row[1], row[6])
        if len(row) > 6 and row[6].strip().lower() == "failed":
            target_row = i
            break
            
    if not target_row:
        print("No failed rows found.")
        return
        
    print(f"Testing video at row {target_row}.")
    
    # Just grab the video data directly instead of changing it to pending, or just build the dict
    video = {
        "row": target_row,
        "filename": all_rows[target_row-1][1],
        "drive_link": all_rows[target_row-1][2],
        "title": all_rows[target_row-1][3],
        "description": all_rows[target_row-1][4],
        "tags": all_rows[target_row-1][5],
        "status": all_rows[target_row-1][6],
        "channel": all_rows[target_row-1][9] if len(all_rows[target_row-1]) > 9 else "default",
    }
    
    # We will test downloading and uploading
    res = s._process_single(video, "youtube")
    print("Result:", res)

if __name__ == "__main__":
    reproduce()
