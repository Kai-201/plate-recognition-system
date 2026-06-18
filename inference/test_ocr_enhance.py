"""
两阶段检测提升 OCR 准确率：
  阶段1: YOLO 检测 → 取车牌中心 → 扩大 3 倍裁剪
  阶段2: 裁剪区域再次 YOLO → 精确位置 → LPRNet 识别

用法: python test_ocr_enhance.py <图片路径>
"""
import sys, os, time, cv2, numpy as np
from PIL import Image, ImageDraw, ImageFont
from ultralytics import YOLO
from LPRNet import build_lprnet
from load_data import CHARS
import torch

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

print("加载模型...")
yolo = YOLO(os.path.join(BASE_DIR, "yolo-best.pt"))
lprnet = build_lprnet(lpr_max_len=8, phase=True, class_num=68, dropout_rate=0.5)
lprnet.to(device)
lprnet.load_state_dict(torch.load(os.path.join(BASE_DIR, "lprnet-best_model.pth"), map_location=device), strict=False)
lprnet.eval()
print(f"设备: {device}")

def transform(img):
    img = img.astype('float32')
    img -= 127.5
    img *= 0.0078125
    return np.transpose(img, (2, 0, 1))

def ctc_decode(prebs_np):
    plates = []
    for i in range(prebs_np.shape[0]):
        preb = prebs_np[i, :, :]
        preb_label = [np.argmax(preb[:, j], axis=0) for j in range(preb.shape[1])]
        no_repeat = []
        pre_c = preb_label[0]
        blank = len(CHARS) - 1
        if pre_c != blank: no_repeat.append(pre_c)
        for c in preb_label:
            if pre_c == c or c == blank:
                if c == blank: pre_c = c
                continue
            no_repeat.append(c); pre_c = c
        plates.append(''.join([CHARS[idx] for idx in no_repeat]))
    return plates

def recognize(crops):
    plates = []
    for img in crops:
        img_t = transform(img)
        img_t = torch.Tensor(img_t[np.newaxis, :]).to(device)
        with torch.no_grad():
            prebs = lprnet(img_t)
        plates.extend(ctc_decode(prebs.cpu().detach().numpy()))
    return plates

def expand_box(box, w, h, scale=3.0):
    """以 box 为中心扩大 scale 倍，不超出图片边界"""
    x1, y1, x2, y2 = map(float, box)
    bw, bh = x2 - x1, y2 - y1
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    nw, nh = bw * scale, bh * scale
    nx1 = max(0, int(cx - nw / 2))
    ny1 = max(0, int(cy - nh / 2))
    nx2 = min(w, int(cx + nw / 2))
    ny2 = min(h, int(cy + nh / 2))
    return nx1, ny1, nx2, ny2

# ==================== 主流程 ====================
if len(sys.argv) < 2:
    print("用法: python test_ocr_enhance.py <图片路径>")
    sys.exit(1)

img_path = sys.argv[1]
image = cv2.imread(img_path)
h, w = image.shape[:2]
print(f"\n图片: {img_path} ({w}x{h})")

# 阶段1: 全图检测
results = yolo.predict(image, imgsz=640, conf=0.3, device=device, verbose=False)
boxes_s1 = results[0].boxes.xyxy.cpu().numpy() if len(results[0].boxes) > 0 else []

if len(boxes_s1) == 0:
    print("未检测到车牌")
    sys.exit(0)

print(f"\n阶段1: 检测到 {len(boxes_s1)} 个车牌")
pil_img = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))

for i, box in enumerate(boxes_s1):
    x1, y1, x2, y2 = map(int, box)
    bw, bh = x2 - x1, y2 - y1
    print(f"\n--- 车牌 {i+1}: ({x1},{y1})-({x2},{y2}) {bw}x{bh} ---")

    # === 传统方式: 直接裁剪原图 94x24 → LPRNet ===
    crop_old = pil_img.crop((x1, y1, x2, y2)).resize((94, 24), Image.LANCZOS)
    old_result = recognize([np.array(crop_old)])
    print(f"  传统方式: {old_result}")

    # === 增强方式: 扩大区域 → 二次检测 → 精确裁剪 → LPRNet ===
    ex1, ey1, ex2, ey2 = expand_box(box, w, h, scale=3.0)
    expanded = image[ey1:ey2, ex1:ex2]  # BGR 裁剪
    print(f"  扩大区域: ({ex1},{ey1})-({ex2},{ey2}) {ex2-ex1}x{ey2-ey1}")

    # 保存扩大图 + 在原图上画框
    cv2.imwrite(f"test_expanded_{i}.jpg", expanded)
    print(f"  扩大图已保存: test_expanded_{i}.jpg")

    # 在原图上画阶段1的框（红色）和扩大区域（蓝色虚线）
    cv2.rectangle(image, (x1, y1), (x2, y2), (0, 0, 255), 2)        # 红色=阶段1框
    cv2.rectangle(image, (ex1, ey1), (ex2, ey2), (255, 0, 0), 1)     # 蓝色=扩大区域
    cv2.imwrite("test_overview.jpg", image)
    print(f"  总览图已保存: test_overview.jpg (红框=检测, 蓝框=扩大区域)")

    # 阶段2: 扩大区域再次 YOLO
    results2 = yolo.predict(expanded, imgsz=640, conf=0.15, device=device, verbose=False)
    boxes_s2 = results2[0].boxes.xyxy.cpu().numpy() if len(results2[0].boxes) > 0 else []
    confs_s2 = results2[0].boxes.conf.cpu().numpy() if len(results2[0].boxes) > 0 else []
    print(f"  阶段2检测到: {len(boxes_s2)} 个车牌 (conf阈值0.15)")
    if len(confs_s2) > 0:
        print(f"  置信度: {confs_s2.tolist()}")

    # 在扩大图上画所有检测框，保存
    expanded_dbg = expanded.copy()
    for j, b2 in enumerate(boxes_s2):
        bx1, by1, bx2, by2 = map(int, b2)
        cv2.rectangle(expanded_dbg, (bx1, by1), (bx2, by2), (0, 255, 0), 2)
        cv2.putText(expanded_dbg, f"{confs_s2[j]:.2f}", (bx1, by1-5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    cv2.imwrite(f"test_expanded_dbg_{i}.jpg", expanded_dbg)
    print(f"  扩大图+检测框: test_expanded_dbg_{i}.jpg")

    if len(boxes_s2) > 0:
        # 取置信度最高的
        confs = results2[0].boxes.conf.cpu().numpy()
        best_idx = np.argmax(confs)
        b2 = boxes_s2[best_idx]
        bx1, by1, bx2, by2 = map(int, b2)
        # 坐标映射回扩大区域
        crop_exp = Image.fromarray(cv2.cvtColor(expanded, cv2.COLOR_BGR2RGB))
        crop_new = crop_exp.crop((bx1, by1, bx2, by2)).resize((94, 24), Image.LANCZOS)
        new_result = recognize([np.array(crop_new)])
        print(f"  增强方式: {new_result}")
        print(f"  对比: 传统={old_result}  增强={new_result}  {'✅' if new_result != old_result else '无变化'}")
    else:
        print(f"  阶段2未检测到，降级用传统结果")

print("\n完成！")
