"""
两阶段检测测试: 先找车 → 裁剪 → 再找车牌
用法: python test_car_then_plate.py <图片路径>
"""
import sys, os, cv2, numpy as np
from PIL import Image
from ultralytics import YOLO
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

print("加载模型...")
import torch
from LPRNet import build_lprnet
from load_data import CHARS

yolo_car = YOLO("yolov8n.pt")
yolo_plate = YOLO(os.path.join(BASE_DIR, "yolo-best.pt"))
CAR_CLASSES = {2, 5, 7}

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
lprnet = build_lprnet(lpr_max_len=8, phase=True, class_num=68, dropout_rate=0.5)
lprnet.to(device)
lprnet.load_state_dict(torch.load(os.path.join(BASE_DIR, "lprnet-best_model.pth"), map_location=device), strict=False)
lprnet.eval()
print(f"设备: {device}")

def transform(img):
    img = img.astype('float32'); img -= 127.5; img *= 0.0078125
    return np.transpose(img, (2, 0, 1))

def recognize(crops):
    plates = []
    for img in crops:
        img_t = transform(img)
        img_t = torch.Tensor(img_t[np.newaxis, :]).to(device)
        with torch.no_grad(): prebs = lprnet(img_t)
        prebs_np = prebs.cpu().detach().numpy()
        for b in range(prebs_np.shape[0]):
            preb = prebs_np[b, :, :]
            preb_label = [np.argmax(preb[:, j], axis=0) for j in range(preb.shape[1])]
            no_repeat, pre_c = [], preb_label[0]
            blank = len(CHARS) - 1
            if pre_c != blank: no_repeat.append(pre_c)
            for c in preb_label:
                if pre_c == c or c == blank:
                    if c == blank: pre_c = c
                    continue
                no_repeat.append(c); pre_c = c
            plates.append(''.join([CHARS[idx] for idx in no_repeat]))
    return plates

IMG_PATH = r"C:\Users\张开兴\Desktop\车牌识别\inference\test.jpg"
img_path = sys.argv[1] if len(sys.argv) > 1 else IMG_PATH

image = cv2.imread(img_path)
if image is None:
    print(f"读图失败: {img_path}")
    sys.exit(1)
h, w = image.shape[:2]
print(f"图片: {w}x{h}")

results = yolo_car.predict(image, imgsz=640, conf=0.3, classes=list(CAR_CLASSES), verbose=False)
car_boxes = results[0].boxes.xyxy.cpu().numpy() if results[0].boxes is not None and len(results[0].boxes) > 0 else []
print(f"检测到 {len(car_boxes)} 辆车")

image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
n = len(car_boxes)
fig, axes = plt.subplots(1, max(2, n + 1), figsize=(16, 6))
if not hasattr(axes, '__iter__'): axes = [axes]

axes[0].imshow(image_rgb)
axes[0].set_title("原图"); axes[0].axis('off')

for i, cbox in enumerate(car_boxes):
    cx1, cy1, cx2, cy2 = map(int, cbox)
    cw, ch = cx2 - cx1, cy2 - cy1
    cx1 = max(0, cx1 - int(cw * 0.1)); cx2 = min(w, cx2 + int(cw * 0.1))
    cy1 = max(0, cy1 - int(ch * 0.2)); cy2 = min(h, cy2 + int(ch * 0.2))

    car_crop = image_rgb[cy1:cy2, cx1:cx2]
    car_crop_bgr = cv2.cvtColor(car_crop, cv2.COLOR_RGB2BGR)
    print(f"车{i+1}: 裁剪 {cx2-cx1}x{cy2-cy1}")

    r2 = yolo_plate.predict(car_crop_bgr, imgsz=320, conf=0.15, verbose=False)
    pboxes = r2[0].boxes.xyxy.cpu().numpy() if r2[0].boxes is not None and len(r2[0].boxes) > 0 else []
    # LPRNet 识别
    plates_text = []
    if len(pboxes) > 0:
        car_pil = Image.fromarray(car_crop)
        crops_for_lpr = []
        for pb in pboxes:
            px1, py1, px2, py2 = map(int, pb)
            crops_for_lpr.append(np.array(car_pil.crop((px1, py1, px2, py2)).resize((94, 24), Image.LANCZOS)))
        plates_text = recognize(crops_for_lpr)
    print(f"  识别结果: {plates_text}")

    ax = axes[i + 1]
    ax.imshow(car_crop)
    for j, pb in enumerate(pboxes):
        px1, py1, px2, py2 = map(int, pb)
        ax.add_patch(plt.Rectangle((px1, py1), px2 - px1, py2 - py1,
                                    fill=False, color='lime', linewidth=2))
        if j < len(plates_text):
            ax.text(px1, py1 - 5, plates_text[j], color='lime', fontsize=10,
                    bbox=dict(facecolor='green', alpha=0.7))
    ax.set_title(f"车{i+1}: {plates_text}"); ax.axis('off')

plt.tight_layout()
plt.show()
print("完成")
