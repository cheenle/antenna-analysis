#!/usr/bin/env bash
# 合成成片：按 marks.json 的真实时间戳，把每段配音精确放到对应位置
# 思路：每段配音用 adelay 延迟到它的 start 时刻，再用 amix 叠加成完整音轨，
#       音轨总长 = 视频总长，声画逐段对齐，无累积漂移。
set -euo pipefail
cd "$(dirname "$0")"

[ -f marks.json ] || { echo "marks.json 不存在，先跑录屏"; exit 1; }

WEBM=raw_video/$(python3 -c "import json;print(json.load(open('marks.json'))['webm'])")
[ -f "$WEBM" ] || { echo "webm 不存在: $WEBM"; exit 1; }
VID=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$WEBM")
echo "video: $WEBM  (${VID}s)"

mkdir -p work
rm -f work/*.mp3

# 为每段配音生成「延迟到 start 时刻」的等长音轨，并构建 amix 输入
python3 - "$VID" <<'PY'
import json, subprocess, sys, os
vid = float(sys.argv[1])
data = json.load(open('marks.json'))
marks = data['marks']

inputs, filters, labels = [], [], []
for i, m in enumerate(marks):
    src = f"audio/{m['id']}.mp3"
    delay_ms = int(m['start'] * 1000)
    # 每段：延迟到 start，并 pad 到视频总长，保证所有支路等长
    filters.append(
        f"[{i}:a]adelay={delay_ms}|{delay_ms},apad,atrim=0:{vid:.3f},aresample=44100[a{i}]"
    )
    labels.append(f"[a{i}]")
    inputs += ['-i', src]

n = len(marks)
fc = ";".join(filters) + ";" + "".join(labels) + \
     f"amix=inputs={n}:normalize=0:dropout_transition=0[mix]"

cmd = ['ffmpeg','-y'] + inputs + \
      ['-filter_complex', fc, '-map', '[mix]',
       '-ar','44100','-ac','2', 'work/narration_full.mp3']
subprocess.run(cmd, check=True, capture_output=True)
print(f"narration track built: {n} segments over {vid:.1f}s")
PY

AUD=$(ffprobe -v error -show_entries format=duration -of csv=p=0 work/narration_full.mp3)
echo "narration_full=${AUD}s  video=${VID}s"

# webm → mp4 + 合并配音
ffmpeg -y -i "$WEBM" -i work/narration_full.mp3 \
  -map 0:v:0 -map 1:a:0 \
  -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p \
  -c:a aac -b:a 192k -shortest \
  -movflags +faststart \
  antenna_intro.mp4 2>/dev/null

OUT=$(ffprobe -v error -show_entries format=duration -of csv=p=0 antenna_intro.mp4)
echo "=== DONE: antenna_intro.mp4  (${OUT}s) ==="
ls -lh antenna_intro.mp4
