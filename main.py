import mido, sys, json, os.path, math
import argparse
from pydub import AudioSegment
from PIL import Image, ImageDraw, ImageFont
import zipfile
import random, os
import struct
import shutil
import numpy as np

def get_time(time, track):
    sec = 0.0
    beat = time
    for i, e in enumerate(bpm_list[track]):
        bpmv = e["bpm"]
        if i != len(bpm_list[track]) - 1:
            et_beat = bpm_list[track][i + 1]["time"] - e["time"]
            if beat >= et_beat:
                sec += et_beat / tpb * (60 / bpmv)
                beat -= et_beat
            else:
                sec += beat / tpb * (60 / bpmv)
                break
        else:
            sec += beat / tpb * (60 / bpmv)
    return sec

# -h, --help
parser = argparse.ArgumentParser(description='mid2phi')
parser.add_argument('input_midi', type=str, help='input midi')
parser.add_argument('output_dir', type=str, help='output dir')
parser.add_argument('--audio', type=str, help='audio', default=None)
parser.add_argument('--image', type=str, help='image', default=None)
parser.add_argument('--title', type=str, help='title', default='UK')
parser.add_argument('--composer', type=str, help='composer', default='UK')
parser.add_argument('--charter', type=str, help='charter', default='Python')
parser.add_argument('--level', type=str, help='level', default='SP Lv.?')
parser.add_argument('--hold-threshold', type=int, help='tohold(ms)', default=200)
parser.add_argument('--velocity-threshold', type=int, help='velocity', default=30)
parser.add_argument('--drag-threshold', type=int, help='todrag', default=60)
parser.add_argument('--dedup-window', type=float, help='deletewindow(ms)', default=10.0)

args = parser.parse_args()
os.makedirs(args.output_dir, exist_ok=True)
with open(args.input_midi, 'rb') as f:
    data = f.read(14)
data = struct.unpack(">4sI3H", data)
mid = mido.MidiFile(args.input_midi, type=data[2], ticks_per_beat=data[4])
chart = {
        "formatVersion": 3,
        "offset": 0.0,
        "judgeLineList": [
            {
                "bpm": 1875,
                "judgeLineMoveEvents": [
                    {
                        "startTime": -999999,
                        "endTime": 100000000,
                        "start": 0.5,
                        "start2": 0.1,
                        "end": 0.5,
                        "end2": 0.1
                    }
                ],
                "judgeLineRotateEvents": [
                    {
                        "startTime": -999999,
                        "endTime": 100000000,
                        "start": 0,
                        "end": 0
                    }
                ],
                "judgeLineDisappearEvents": [
                    {
                        "startTime": -999999,
                        "endTime": 100000000,
                        "start": 1,
                        "end": 1,
                    }
                ],
                "speedEvents": [
                    {
                        "startTime": 0,
                        "endTime": 100000000,
                        "value": 2.2
                    }
                ],
                "notesAbove": [],
                "notesBelow": []
            }
        ]
    }

tpb = mid.ticks_per_beat
tempo = 100000000
notes = []
active_notes = {}
max_length = 0
current_time_s = 0
bpm_dict = {}
current_time = 0.
ticks_per_beat = mid.ticks_per_beat
bpm_list = []
print("geting bpm...")
for track in mid.tracks:
    for msg in track:
        current_time += msg.time
        if msg.type == "set_tempo":
            bpm = 60000000 / msg.tempo
            if current_time not in bpm_dict:
                bpm_dict[current_time] = bpm
    if mid.type == 2:
        bpm_list.append([{"time": time, "bpm": bpm} for time, bpm in bpm_dict.items()])

if mid.type != 2:
    bpm_list = [[{"time": time, "bpm": bpm} for time, bpm in bpm_dict.items()] for _ in mid.tracks]

print("geting notes...")
for i, track in enumerate(mid.tracks):
    current_time = 0.
    for msg in track:
        current_time += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            if msg.note not in active_notes:
                active_notes[msg.note] = {
                    "startTime": get_time(current_time, i)*1000,
                    "note": msg.note,
                    "velocity": msg.velocity
                }
        elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            if msg.note in active_notes:
                note = active_notes.pop(msg.note)
                duration = get_time(current_time, i)*1000 - note["startTime"]
                if duration > 0:
                    notes.append({
                        "startTime": note["startTime"],
                        "endTime": get_time(current_time, i)*1000,
                        "note": note["note"],
                        "duration": duration,
                        "velocity": note["velocity"]
                    })
        current_time_s = get_time(current_time, i)
        max_length = max(current_time_s*1000+1000, max_length)
print(f"length：{max_length/1000:.2f}s")
# 按开始时间排序
notes.sort(key=lambda x: x["startTime"])

# 轨道
min_note = min(note["note"] for note in notes) if notes else 0
max_note = max(note["note"] for note in notes) if notes else 127
note_range = max(1, max_note - min_note)

print(f"min: {min_note}, max: {max_note}, range: {note_range}")

max_tracks = 100
total_width = 12.0  # -6 到 6
track_spacing = total_width / (max_tracks - 1)

print(f"using{max_tracks}tracks. spacing: {track_spacing:.4f}")

# 计算音符位置
for note in notes:
    track = min(max_tracks-1, max(0, int(max_tracks * (note["note"] - min_note) / note_range)))
    note["positionX"] = -6.0 + track * track_spacing

# 去重
print("del repeated notes...")
dedup_notes = []
dedup_count = 0

# 按位置和时间分组
note_groups = {}
for note in notes:
    # 四舍五入，用于分组
    time_key = round(note["startTime"] / args.dedup_window) * args.dedup_window
    pos_key = round(note["positionX"], 2)
    group_key = f"{time_key}_{pos_key}"
    
    if group_key not in note_groups:
        note_groups[group_key] = []
    note_groups[group_key].append(note)

# 每个组内保留velocity最大的音符
for group_key, group_notes in note_groups.items():
    if group_notes:
        max_velocity_note = max(group_notes, key=lambda x: x["velocity"])
        dedup_notes.append(max_velocity_note)
        if len(group_notes) > 1:
            dedup_count += len(group_notes) - 1

print(f"deleted {dedup_count} repeated notes")

# 生成音符
drag_count = 0
filtered_count = 0
for i, note in enumerate(dedup_notes):
    print(f"creating {i+1}/{len(dedup_notes)}{' '*100}", end="\r")
    
    # 决定是否过滤
    if note["velocity"] < args.velocity_threshold:
        filtered_count += 1
        continue
    
    # 决定音符类型、
    if note["velocity"] < args.drag_threshold:
        # 转为drag音符 (type=2)
        note_type = 2
        drag_count += 1
    elif note["duration"] < args.hold_threshold:
        # tap音符 (type=1)
        note_type = 1
    else:
        # hold音符 (type=3)
        note_type = 3
    
    # 音符对象
    note_obj = {
        "type": note_type,
        "time": note["startTime"],
        "positionX": note["positionX"],
        "speed": 1,
        "floorPosition": 2.2 * note["startTime"] / 1000
    }
    
    # hold，添加holdTime
    # 卧槽我错了 啥都得加holdTime
    if True:
        note_obj["holdTime"] = note["duration"]
    
    chart["judgeLineList"][0]["notesAbove"].append(note_obj)

print("\nhandling additional resources...")

rand = random.randint(100000000, 999999999)

# 处理音频
if args.audio:
    # 直接使用自定义音频
    audio_ext = os.path.splitext(args.audio)[1].lower()
    audio_target = os.path.join(args.output_dir, f"music{rand}{audio_ext}")
    shutil.copyfile(args.audio, audio_target)
    audio_filename = f"music{rand}{audio_ext}"
else:
    # 生成音频
    music = AudioSegment.silent(duration=int(max_length))
    audio_target = os.path.join(args.output_dir, f"music{rand}.wav")
    music.export(audio_target, format="wav")
    audio_filename = f"music{rand}.wav"

# 处理曲绘 同上
if args.image:
    img_ext = os.path.splitext(args.image)[1].lower()
    img_target = os.path.join(args.output_dir, f"bg{rand}{img_ext}")
    shutil.copyfile(args.image, img_target)
    img_filename = f"bg{rand}{img_ext}"
else:
    img = Image.new("RGBA", (1920, 1080), (0, 0, 0, 255))
    try:
        font = ImageFont.truetype("font.ttf", size=56)
    except:
        font = ImageFont.load_default()
    draw = ImageDraw.Draw(img)
    draw.text((960, 540), "this is a chart created by py", (255, 255, 255), font=font, anchor="mm")
    img_target = os.path.join(args.output_dir, f"bg{rand}.png")
    img.save(img_target)
    img_filename = f"bg{rand}.png"

# 写入谱面
chart_file = os.path.join(args.output_dir, "chart.pez")
with zipfile.ZipFile(chart_file, "w", zipfile.ZIP_DEFLATED) as f:
    f.writestr("0.json", json.dumps(chart, indent=2))
    f.write(audio_target, "0.wav")
    f.write(img_target, "0.png")
    f.writestr("info.txt", f"""#
Name: {args.title}
Path: 0
Song: 0.wav
Picture: 0.png
Chart: 0.json
Level: {args.level}
Composer: {args.composer}
Charter: {args.charter}
""")

# 清理临时文件
if os.path.exists(audio_target):
    os.remove(audio_target)
if os.path.exists(img_target):
    os.remove(img_target)

# 统计音符
tap_count = sum(1 for note in dedup_notes if note["duration"] < args.hold_threshold and note["velocity"] >= args.drag_threshold)
hold_count = sum(1 for note in dedup_notes if note["duration"] >= args.hold_threshold and note["velocity"] >= args.drag_threshold)

print(f"done! saved to: {chart_file}")
print(f"title: {args.title} | composer: {args.composer} | charter: {args.charter} | level: {args.level}")
print(f"count: {tap_count} taps, {hold_count} holds, {drag_count} drags ")
print(f"filtered {filtered_count} notes, deleted {dedup_count} repeated noted")
print(f"range: {min(note['positionX'] for note in dedup_notes):.2f}to{max(note['positionX'] for note in dedup_notes):.2f}")

'''
phi2mid ver 1.0.1
why am i doing this?
by desivr
2025.7.5
使用过ai 帮我润色代码
'''
