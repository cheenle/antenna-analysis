#!/usr/bin/env python3
# 紧凑版字幕：读 compact.json(重排后的时间轴) + storyboard 文案，
# 按标点切句，在每段窗口内按字符数比例分配显示时长。输出 subtitles_compact.ass
import json, re

segs = json.load(open('compact.json'))['segments']
board = {s['id']: s for s in json.load(open('storyboard.json'))['segments']}

def split_sentences(text):
    parts = re.split(r'(?<=[。！？])', text)
    chunks = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) <= 24:
            chunks.append(p)
        else:
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
    h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
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
for s in segs:
    seg = board[s['id']]
    dur = float(s['dur'])
    start = float(s['nar_start'])
    chunks = split_sentences(seg['narration'])
    total_chars = sum(len(c) for c in chunks) or 1
    t = start
    for c in chunks:
        span = dur * (len(c) / total_chars)
        s0, s1 = t, t + span
        t = s1
        lines.append(f"Dialogue: 0,{fmt(s0)},{fmt(s1)},Sub,,0,0,0,,{c}")

open('subtitles_compact.ass', 'w').write(header + "\n".join(lines) + "\n")
print(f"subtitles_compact.ass written: {len(lines)} cues")
