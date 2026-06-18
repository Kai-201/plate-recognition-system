"""
推理耗时测试：YOLO检测 → 裁剪 → LPRNet识别，分段计时
用法: python benchmark.py <图片路径>
"""
import sys
import os
import time
import cv2
import numpy as np
from PIL import Image
from ultralytics import YOLO
from LPRNet import build_lprnet
from load_data import CHARS
import torch

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 加载模型
print("加载模型...")
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"设备: {device}")

t0 = time.time()
yolo = YOLO(os.path.join(BASE_DIR, "yolo-best.pt"))
print(f"  YOLO: {time.time()-t0:.1f}s")

t0 = time.time()
lprnet = build_lprnet(lpr_max_len=8, phase=True, class_num=68, dropout_rate=0.5)
lprnet.to(device)
lprnet.load_state_dict(torch.load(os.path.join(BASE_DIR, "lprnet-best_model.pth"), map_location=device), strict=False)
lprnet.eval()
print(f"  LPRNet: {time.time()-t0:.1f}s")

def transform(img):
    img = img.astype('float32')
    img -= 127.5
    img *= 0.0078125
    img = np.transpose(img, (2, 0, 1))
    return img

def ctc_decode(prebs_np):
    """CTC 贪婪解码"""
    plates = []
    for i in range(prebs_np.shape[0]):
        preb = prebs_np[i, :, :]
        preb_label = [np.argmax(preb[:, j], axis=0) for j in range(preb.shape[1])]
        no_repeat = []
        pre_c = preb_label[0]
        blank = len(CHARS) - 1
        if pre_c != blank:
            no_repeat.append(pre_c)
        for c in preb_label:
            if pre_c == c or c == blank:
                if c == blank: pre_c = c
                continue
            no_repeat.append(c)
            pre_c = c
        plates.append(''.join([CHARS[idx] for idx in no_repeat]))
    return plates

if len(sys.argv) < 2:
    print("用法: python benchmark.py <图片路径> [次数]")
    print("示例: python benchmark.py test.jpg 10")
    sys.exit(1)

img_path = sys.argv[1]
n_runs = int(sys.argv[2]) if len(sys.argv) > 2 else 1

print(f"\n测试图片: {img_path}")
print(f"重复次数: {n_runs}")
print("=" * 60)

# 预热（第一帧通常慢，GPU warmup）
image = cv2.imread(img_path)
_ = yolo.predict(image, imgsz=640, conf=0.5, device=device, verbose=False)

times_detect = []
times_crop = []
times_lprnet = []
times_decode = []

for run in range(n_runs):
    image = cv2.imread(img_path)
    h, w = image.shape[:2]

    # 1. YOLO 检测
    t0 = time.time()
    results = yolo.predict(image, imgsz=640, conf=0.5, device=device, verbose=False)
    boxes = results[0].boxes.xyxy.cpu().numpy() if len(results[0].boxes) > 0 else []
    t_detect = time.time() - t0
    times_detect.append(t_detect)

    if len(boxes) == 0:
        print(f"[{run+1}] 未检测到车牌")
        continue

    # 2. 裁剪
    t0 = time.time()
    pil_img = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    crops = []
    for box in boxes:
        x1, y1, x2, y2 = map(int, box)
        crop = pil_img.crop((x1, y1, x2, y2)).resize((94, 24), Image.LANCZOS)
        crops.append(np.array(crop))
    t_crop = time.time() - t0
    times_crop.append(t_crop)

    # 3. LPRNet 推理
    t0 = time.time()
    plates_result = []
    for img in crops:
        img_t = transform(img)
        img_t = torch.Tensor(img_t[np.newaxis, :]).to(device)
        with torch.no_grad():
            prebs = lprnet(img_t)
        plates_result.append(prebs.cpu().detach().numpy())
    t_lprnet = time.time() - t0
    times_lprnet.append(t_lprnet)

    # 4. CTC 解码
    t0 = time.time()
    all_plates = []
    for prebs_np in plates_result:
        all_plates.extend(ctc_decode(prebs_np))
    t_decode = time.time() - t0
    times_decode.append(t_decode)

    print(f"[{run+1}] 检测{t_detect*1000:.0f}ms | 裁剪{t_crop*1000:.1f}ms | "
          f"LPRNet{t_lprnet*1000:.0f}ms | 解码{t_decode*1000:.2f}ms | "
          f"车牌: {all_plates} | 图片: {w}x{h}")

# 平均
if times_detect:
    print("=" * 60)
    print(f"平均({n_runs}次): 检测{np.mean(times_detect)*1000:.0f}ms | "
          f"裁剪{np.mean(times_crop)*1000:.1f}ms | "
          f"LPRNet{np.mean(times_lprnet)*1000:.0f}ms | "
          f"解码{np.mean(times_decode)*1000:.2f}ms | "
          f"单帧合计{np.mean(times_detect)+np.mean(times_crop)+np.mean(times_lprnet)+np.mean(times_decode):.3f}s")
