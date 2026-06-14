#!/usr/bin/env python3
# 生成与配音同步的中文 ASS 字幕
# 思路：读 marks.json(每段起始时刻+时长) 与 storyboard(文案)，
#   按标点把每段解说切成短句，在该段时间窗口内按字符数比例分配每句显示时长，
#   再整体减去 CUT(片头裁剪量)，得到裁剪后视频的字幕时间轴。
import json, re, sys

CUT = float(sys.argv[1]) if len(sys.argv) > 1 else 24.7  # 片头裁掉的秒数

marks = json.load(open('marks.json'))
board = {s['id']: s for s in json.load(open('storyboard.json'))['segments']}

def split_sentences(text):
    """按句末标点切句，长句再按逗号细分，合并过短片段。"""
    # 先按强标点断句
    parts = re.split(r'(?<=[。！？])', text)
    chunks = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) <= 24:
            chunks.append(p)
        else:
            # 长句按逗号/顿号/冒号细分
            sub = re.split(r'(?<=[，、：])', p)
            buf = ''
            for s in sub:
                if len(buf) + len(s) <= 22:
                    buf += s
                else:
                    if buf:
                        chunks.append(buf)
                    buf = s
            if buf:
                chunks.append(buf)
    # 合并过短(<6字)的尾巴到前一块
    merged = []
    for c in chunks:
        if merged and len(c) < 6:
            merged[-1] += c
        else:
            merged.append(c)
    return merged

def fmt(t):
    if t < 0:
        t = 0
    h = int(t // 3600); m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"

header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 800
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,PingFang SC,30,&H00FFFFFF,&H00000000,&H96000000,1,3,0,0,2,60,60,46,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, Effect, Text
"""

lines = []
for m in marks['marks']:
    seg = board[m['id']]
    dur = float(m.get('dur') or m.get('narr') or m.get('nar'))
    start = float(m['start']) - CUT
    chunks = split_sentences(seg['narration'])
    total_chars = sum(len(c) for c in chunks) or 1
    t = start
    for c in chunks:
        span = dur * (len(c) / total_chars)
        s0, s1 = t, t + span
        t = s1
        if s1 <= 0:
            continue
        txt = c.replace('\n', ' ')
        lines.append(f"Dialogue: 0,{fmt(s0)},{fmt(s1)},Sub,,0,0,0,,{txt}")

open('subtitles.ass', 'w').write(header + "\n".join(lines) + "\n")
print(f"subtitles.ass written: {len(lines)} cues, CUT={CUT}s")
