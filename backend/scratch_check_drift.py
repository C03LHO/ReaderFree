import json
import sys
from pathlib import Path

def parse_vtt_end_time(vtt_path):
    with open(vtt_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    # Find the last timestamp line
    last_timestamp = ""
    for line in reversed(lines):
        if "-->" in line:
            last_timestamp = line
            break
    if not last_timestamp:
        return 0.0
    
    end_str = last_timestamp.split("-->")[1].strip()
    # Format: HH:MM:SS.mmm
    h, m, s = end_str.split(":")
    seconds = float(h) * 3600 + float(m) * 60 + float(s)
    return seconds

def main():
    json_path = Path(sys.argv[1])
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    out_dir = json_path.parent
    
    print(f"Verificando drift em {json_path}")
    for chapter in data['chapters']:
        mp3 = chapter['mp3_path']
        vtt = chapter['vtt_path']
        duration = chapter['duration_seconds']
        
        vtt_end = parse_vtt_end_time(out_dir / vtt)
        drift = abs(duration - vtt_end) * 1000  # in ms
        
        print(f"{mp3}:")
        print(f"  MP3 Duration: {duration:.3f}s")
        print(f"  VTT End Time: {vtt_end:.3f}s")
        print(f"  Drift:        {drift:.1f} ms")
        if drift < 150:
            print("  Status:       [PASS] < 150ms")
        else:
            print("  Status:       [FAIL] >= 150ms")
        print()

if __name__ == '__main__':
    main()
