"""
视频逐帧检测 + 画框测试 — 自动播放模式
用法: python test_video_draw.py <视频路径> [抽帧间隔] [播放速度]
示例: python test_video_draw.py test.mp4        # 每帧检测，10ms间隔
      python test_video_draw.py test.mp4 3      # 每3帧检测一次
      python test_video_draw.py test.mp4 1 50   # 每帧，50ms间隔
按 ESC 退出，按 S 保存当前帧，按 空格 暂停
"""
import sys
import os
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from inference_engine import InferenceEngine

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
YOLO_PATH = os.path.join(BASE_DIR, "yolo-best.pt")
LPRNET_PATH = os.path.join(BASE_DIR, "lprnet-best_model.pth")

if len(sys.argv) < 2:
    print("用法: python test_video_draw.py <视频路径> [抽帧间隔] [播放速度ms]")
    sys.exit(1)

VIDEO_PATH = sys.argv[1]
FRAME_SKIP = int(sys.argv[2]) if len(sys.argv) > 2 else 1   # 每N帧检测一次
SPEED = int(sys.argv[3]) if len(sys.argv) > 3 else 10        # 每帧显示ms
OUT_DIR = os.path.join(BASE_DIR, "test_frames")
os.makedirs(OUT_DIR, exist_ok=True)

_engine = InferenceEngine(YOLO_PATH, LPRNET_PATH)
font = _engine._get_chinese_font(size=22)

def draw_on_frame(frame, boxes, plates):
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(frame_rgb)
    draw = ImageDraw.Draw(pil_img)
    for box, plate in zip(boxes, plates):
        x1, y1, x2, y2 = map(int, box)
        label_w = len(plate) * 16 + 10
        draw.rectangle([x1, y1 - 28, x1 + label_w, y1], fill=(0, 255, 0))
        draw.text((x1 + 5, y1 - 26), plate, fill=(0, 0, 0), font=font)
    result = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    for box in boxes:
        x1, y1, x2, y2 = map(int, box)
        cv2.rectangle(result, (x1, y1), (x2, y2), (0, 255, 0), 2)
    return result

print(f"视频: {VIDEO_PATH}")
print(f"设备: {_engine.device}  |  每{FRAME_SKIP}帧检测  |  播放速度: {SPEED}ms")
print(f"空格=暂停  S=保存  ESC=退出")
print("-" * 50)

cap = cv2.VideoCapture(VIDEO_PATH)
fps = cap.get(cv2.CAP_PROP_FPS)
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
frame_idx, detect_count = 0, 0
paused = False

# 缩放到合适大小
cv2.namedWindow("逐帧检测", cv2.WINDOW_NORMAL)
cv2.resizeWindow("逐帧检测", 640, 480)

while True:
    ret, frame = cap.read()
    if not ret:
        print(f"\n结束，共 {frame_idx} 帧，检测到车牌 {detect_count} 帧")
        break

    # 缩放显示
    h, w = frame.shape[:2]
    display = cv2.resize(frame, (640, int(640 * h / w)))

    if frame_idx % FRAME_SKIP == 0:
        boxes = _engine.detect_plates(frame)
        plate_text = ""
        if len(boxes) > 0:
            cropped = _engine.crop_plates(frame, boxes)
            plates = _engine.recognize(cropped)
            plate_text = " | ".join(plates)
            detect_count += 1
            # 在原图和缩略图上都画框
            frame = draw_on_frame(frame, boxes, plates)
            display = cv2.resize(frame, (640, int(640 * h / w)))
            print(f"[{frame_idx}/{total}] {plate_text}  boxes={boxes.tolist() if hasattr(boxes, 'tolist') else boxes}")

    # 顶部信息条
    info = f"帧{frame_idx}/{total} 检测到{detect_count}帧"
    cv2.putText(display, info, (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

    cv2.imshow("逐帧检测", display)

    delay = 1 if not paused else 0
    key = cv2.waitKey(delay if not paused else 0) & 0xFF
    if not paused:
        cv2.waitKey(SPEED)

    if key == 27:
        break
    elif key == 32:
        paused = not paused
    elif key == ord('s'):
        path = os.path.join(OUT_DIR, f"frame_{frame_idx:04d}.jpg")
        cv2.imwrite(path, frame)
        print(f"  已保存: {path}")

    frame_idx += 1

cap.release()
cv2.destroyAllWindows()
print(f"\n标注帧保存目录: {OUT_DIR}")
