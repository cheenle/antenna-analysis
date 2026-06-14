#!/usr/bin/env bash
# 逐段合成中文配音 (MiniMax Speech 2.8 HD)，下载并测量时长，输出 timing.json
set -euo pipefail
cd "$(dirname "$0")"
SB=storyboard.json
OUT=audio
mkdir -p "$OUT"
VOICE=$(python3 -c "import json;print(json.load(open('$SB'))['meta']['voice_id'])")

ids=$(python3 -c "import json;[print(s['id']) for s in json.load(open('$SB'))['segments']]")
texts=$(python3 -c "import json;[print(s['narration']) for s in json.load(open('$SB'))['segments']]")

echo "[" > timing.tmp
first=1
while IFS= read -r seg; do
  text=$(python3 -c "import json,sys;print([s['narration'] for s in json.load(open('$SB'))['segments'] if s['id']=='$seg'][0])")
  mp3="$OUT/$seg.mp3"
  if [ ! -f "$mp3" ]; then
    echo ">> TTS $seg ..."
    url=$(mulerun studio run minimax/speech-2.8-hd/generation \
      --voice-id "$VOICE" --extra language_boost=zh --extra output_format=url \
      --prompt "$text" --json --quiet \
      | python3 -c "import json,sys;print(json.load(sys.stdin)['audios'][0])")
    case "$url" in
      http*) curl -fsSL "$url" -o "$mp3" ;;
      *) echo "!! $seg: expected URL, got non-URL output" >&2; exit 1 ;;
    esac
  fi
  dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$mp3")
  [ $first -eq 1 ] && first=0 || echo "," >> timing.tmp
  printf '{"id":"%s","mp3":"%s","duration":%s}' "$seg" "$mp3" "$dur" >> timing.tmp
done <<< "$ids"
echo "]" >> timing.tmp
python3 -c "import json;d=json.load(open('timing.tmp'));json.dump(d,open('timing.json','w'),ensure_ascii=False,indent=2);print('total audio:',round(sum(x['duration'] for x in d),1),'s')"
rm -f timing.tmp
