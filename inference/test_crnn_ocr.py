"""
二阶段检测 + CRNN OCR 测试（对标 test_car_then_plate.py，换用新版CRNN识别）
用法: python test_crnn_ocr.py <图片路径>
"""
import sys, os, cv2, numpy as np
from PIL import Image
from ultralytics import YOLO
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
import torch

# ====== 路径配置 ======
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NEW_OCR_DIR = os.path.join(BASE_DIR, "改版")
sys.path.insert(0, NEW_OCR_DIR)

from nets.crnn import CRNN
from dataset import CHARS, LABEL2CHAR

# CRNN 模型权重（选一个）
CRNN_CHECKPOINT = os.path.join(NEW_OCR_DIR, "crnn_best.pth")
if not os.path.exists(CRNN_CHECKPOINT):
    # 试试checkpoint目录
    CKPT_DIR = os.path.join(NEW_OCR_DIR, "checkpoint")
    ckpts = sorted([f for f in os.listdir(CKPT_DIR) if f.endswith('.pth')], reverse=True) if os.path.exists(CKPT_DIR) else []
    CRNN_CHECKPOINT = os.path.join(CKPT_DIR, ckpts[0]) if ckpts else None

IMG_PATH = r"C:\Users\张开兴\Desktop\车牌识别\inference\298a70a9-90f4-4868-9cb4-4a964297c60d.png"
IMG_PATH = sys.argv[1] if len(sys.argv) > 1 else IMG_PATH

# ====== 加载模型 ======
print("加载 YOLO 车辆检测...")
yolo_car = YOLO("yolov8n.pt")
print("加载 YOLO 车牌检测...")
yolo_plate = YOLO(os.path.join(BASE_DIR, "yolo-best.pt"))
print(f"加载 CRNN OCR: {CRNN_CHECKPOINT}")
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
crnn = CRNN(input_c=3, input_h=32, num_classes=len(CHARS) + 1).to(device)
crnn.load_state_dict(torch.load(CRNN_CHECKPOINT, map_location=device))
crnn.eval()
print(f"设备: {device}")

# ====== CRNN 预处理 ======
def crnn_preprocess(img):
    """输入: BGR numpy → 输出: tensor [1,3,32,100]"""
    if len(img.shape) == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    else:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img = cv2.resize(img, (100, 32))
    img = img.astype('float32') / 255.0
    img = (img - 0.5) / 0.5
    img = np.transpose(img, (2, 0, 1))
    return torch.from_numpy(img).unsqueeze(0).to(device)

def crnn_recognize(crops):
    """批量 CRNN 识别，返回车牌号列表"""
    plates = []
    for crop in crops:
        inp = crnn_preprocess(crop)
        with torch.no_grad():
            output = crnn(inp)  # [W,1,C]
        pred = output.argmax(dim=2).squeeze(1).cpu().numpy()
        result, prev = [], -1
        for p in pred:
            if p != prev and p != 0:  # blank=0
                result.append(p)
            prev = p
        plates.append(''.join([LABEL2CHAR.get(c, '?') for c in result]))
    return plates

# ====== 加载图片 ======
image = cv2.imread(IMG_PATH)
if image is None:
    print(f"读图失败: {IMG_PATH}")
    sys.exit(1)
h, w = image.shape[:2]
print(f"图片: {w}x{h}")

# ====== 阶段1: 找车 ======
CAR_CLASSES = {2, 5, 7}
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

    car_crop_rgb = image_rgb[cy1:cy2, cx1:cx2]
    car_crop_bgr = cv2.cvtColor(car_crop_rgb, cv2.COLOR_RGB2BGR)
    print(f"车{i+1}: 裁剪 {cx2-cx1}x{cy2-cy1}")

    # 阶段2: 找车牌
    r2 = yolo_plate.predict(car_crop_bgr, imgsz=320, conf=0.15, verbose=False)
    pboxes = r2[0].boxes.xyxy.cpu().numpy() if r2[0].boxes is not None and len(r2[0].boxes) > 0 else []

    # CRNN 识别
    plates_text = []
    if len(pboxes) > 0:
        car_pil = Image.fromarray(car_crop_rgb)
        for pb in pboxes:
            px1, py1, px2, py2 = map(int, pb)
            plate_crop = car_crop_bgr[py1:py2, px1:px2]  # BGR 原尺寸，CRNN 自己 resize
            plates_text = crnn_recognize([plate_crop])
            print(f"  识别结果: {plates_text}")

    ax = axes[i + 1]
    ax.imshow(car_crop_rgb)
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
