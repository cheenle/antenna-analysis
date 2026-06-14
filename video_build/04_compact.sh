#!/usr/bin/env bash
# 紧凑成片：按段切片重拼，压掉片头加载与段间长 loading 等待
# 每段只保留 [画面就绪前 LEAD 秒 → 解说 dur → 后 TAIL 秒缓冲]
# 然后重建对齐音轨 + 生成紧凑时间轴字幕 + 烧录
set -euo pipefail
cd "$(dirname "$0")"

LEAD=1.2   # 每段解说前保留的画面引入时间
TAIL=1.3   # 每段解说后保留的缓冲

WEBM=raw_video/$(python3 -c "import json;print(json.load(open('marks.json'))['webm'])")
[ -f "$WEBM" ] || { echo "webm 不存在: $WEBM"; exit 1; }
echo "source video: $WEBM"

mkdir -p work/clips
rm -f work/clips/*.mp4 work/clip_list.txt work/*.mp3

# 1) 切出每段视频片段 [start-LEAD, start+dur+TAIL]，生成紧凑时间轴 compact.json
python3 - "$LEAD" "$TAIL" <<'PY'
import json, subprocess, sys, os
LEAD, TAIL = float(sys.argv[1]), float(sys.argv[2])
data = json.load(open('marks.json'))
marks = data['marks']
webm = 'raw_video/' + data['webm']

vdur = float(subprocess.run(['ffprobe','-v','error','-show_entries','format=duration',
    '-of','csv=p=0', webm], capture_output=True, text=True).stdout.strip())

compact = []
t_out = 0.0
for i, m in enumerate(marks):
    dur = float(m.get('dur') or m.get('narr') or m.get('nar'))
    seg_start = max(0.0, m['start'] - LEAD)
    seg_end = min(vdur, m['start'] + dur + TAIL)
    seg_len = seg_end - seg_start
    clip = f"work/clips/clip_{i:02d}.mp4"
    subprocess.run(['ffmpeg','-y','-ss',f'{seg_start:.3f}','-to',f'{seg_end:.3f}',
        '-i', webm,'-c:v','libx264','-preset','medium','-crf','20',
        '-pix_fmt','yuv420p','-an', clip], check=True, capture_output=True)
    nar_start = t_out + (m['start'] - seg_start)
    compact.append({'id': m['id'], 'clip': clip, 'nar_start': round(nar_start, 3),
                    'dur': dur, 'clip_len': round(seg_len, 3)})
    t_out += seg_len

json.dump({'segments': compact, 'total': round(t_out, 3)}, open('compact.json','w'),
          ensure_ascii=False, indent=2)
with open('work/clip_list.txt','w') as f:
    for c in compact:
        f.write(f"file '{os.path.abspath(c['clip'])}'\n")
print(f"clips: {len(compact)}  total={t_out:.1f}s")
PY

# 2) 拼接所有片段为紧凑视频（无声）
ffmpeg -y -f concat -safe 0 -i work/clip_list.txt -c copy work/compact_video.mp4 2>/dev/null

# 3) 按 compact.json 的 nar_start 重建对齐音轨
python3 - <<'PY'
import json, subprocess
data = json.load(open('compact.json'))
segs = data['segments']; total = data['total']
inputs, filters, labels = [], [], []
for i, s in enumerate(segs):
    delay_ms = int(s['nar_start'] * 1000)
    filters.append(f"[{i}:a]adelay={delay_ms}|{delay_ms},apad,atrim=0:{total:.3f},aresample=44100[a{i}]")
    labels.append(f"[a{i}]")
    inputs += ['-i', f"audio/{s['id']}.mp3"]
fc = ";".join(filters) + ";" + "".join(labels) + \
     f"amix=inputs={len(segs)}:normalize=0:dropout_transition=0[mix]"
subprocess.run(['ffmpeg','-y'] + inputs + ['-filter_complex', fc, '-map','[mix]',
    '-ar','44100','-ac','2','work/narration_compact.mp3'], check=True, capture_output=True)
print("narration rebuilt")
PY

# 4) 生成紧凑时间轴字幕
python3 gen_subtitles_compact.py

# 5) 烧录字幕 + 合并音轨
ffmpeg -y -i work/compact_video.mp4 -i work/narration_compact.mp3 \
  -filter_complex "[0:v]ass=subtitles_compact.ass[v]" \
  -map '[v]' -map '1:a:0' \
  -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p \
  -c:a aac -b:a 192k -shortest -movflags +faststart \
  antenna_intro_compact.mp4 2>/dev/null

echo "=== DONE ==="
OUT=$(ffprobe -v error -show_entries format=duration -of csv=p=0 antenna_intro_compact.mp4)
echo "antenna_intro_compact.mp4  (${OUT}s)"
ls -lh antenna_intro_compact.mp4
