"""
车牌识别推理引擎
整合 YOLOv8（车牌检测） + LPRNet（字符识别）
"""
import os
import cv2
import torch
import numpy as np
from PIL import Image
from ultralytics import YOLO
from LPRNet import build_lprnet
from load_data import CHARS


# ==================== 图像预处理 ====================

def transform(img):
    """LPRNet 输入预处理：归一化到 [-1, 1] 并转为 CHW 格式"""
    img = img.astype('float32')
    img -= 127.5
    img *= 0.0078125          # 1/128
    img = np.transpose(img, (2, 0, 1))   # HWC → CHW
    return img


# ==================== 模型管理 ====================

class InferenceEngine:
    """推理引擎：加载 YOLO + LPRNet，对外提供统一的推理接口"""

    def __init__(self, yolo_path: str, lprnet_path: str,
                 lpr_max_len: int = 8, class_num: int = 68,
                 dropout_rate: float = 0.5):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"[InferenceEngine] 使用设备: {self.device}")

        # 加载 YOLOv8
        if not os.path.exists(yolo_path):
            raise FileNotFoundError(f"YOLO 模型文件不存在: {yolo_path}")
        self.yolo_model = YOLO(yolo_path)
        print("[InferenceEngine] YOLOv8 模型加载成功")

        # 加载 LPRNet
        if not os.path.exists(lprnet_path):
            raise FileNotFoundError(f"LPRNet 模型文件不存在: {lprnet_path}")
        self.lprnet = build_lprnet(lpr_max_len=lpr_max_len, phase=True,
                                   class_num=class_num, dropout_rate=dropout_rate)
        self.lprnet.to(self.device)
        self.lprnet.load_state_dict(torch.load(lprnet_path, map_location=self.device),
                                    strict=False)
        self.lprnet.eval()
        print("[InferenceEngine] LPRNet 模型加载成功")

    # ==================== 车牌检测 ====================

    def detect_plates(self, image: np.ndarray):
        """
        YOLOv8 检测车牌位置
        参数:
            image: BGR 格式的 numpy 数组 (H, W, 3)
        返回:
            boxes: [(x1, y1, x2, y2), ...]  边界框坐标列表
        """
        # YOLO 支持直接传 numpy 数组
        results = self.yolo_model.predict(image, imgsz=640, conf=0.3,
                                          device=self.device, verbose=False)
        if len(results[0].boxes) == 0:
            return []
        return results[0].boxes.xyxy.cpu().numpy()

    # ==================== 车牌裁剪 ====================

    def crop_plates(self, image: np.ndarray, boxes):
        """
        根据检测框裁剪车牌区域，resize 到 LPRNet 输入尺寸 (94, 24)
        参数:
            image: BGR 格式 (H, W, 3)
            boxes: 边界框数组
        返回:
            cropped: [np.ndarray, ...]  裁剪后的车牌图片列表
        """
        # BGR → RGB (PIL)
        pil_image = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        cropped = []
        for box in boxes:
            x1, y1, x2, y2 = map(int, box)
            crop = pil_image.crop((x1, y1, x2, y2)).resize((94, 24), Image.LANCZOS)
            cropped.append(np.array(crop))
        return cropped

    # ==================== 字符识别 ====================

    def recognize(self, cropped_images):
        """
        LPRNet 识别车牌字符（含 CTC 解码）
        参数:
            cropped_images: 裁剪后的车牌图片列表
        返回:
            plates: [str, ...]  识别出的车牌号列表
        """
        plates = []
        for img in cropped_images:
            # 预处理
            img = transform(img)
            img = img[np.newaxis, :]                    # 增加 batch 维度
            img_tensor = torch.Tensor(img).to(self.device)

            # 推理
            with torch.no_grad():
                prebs = self.lprnet(img_tensor)          # (1, class_num, seq_len)
            prebs = prebs.cpu().detach().numpy()

            # CTC 解码：去除重复和空白符
            for i in range(prebs.shape[0]):
                preb = prebs[i, :, :]                    # (class_num, seq_len)
                preb_label = []
                for j in range(preb.shape[1]):
                    preb_label.append(np.argmax(preb[:, j], axis=0))

                # 去除连续重复 和 blank（CHARS 最后一个字符 '-' 作为 blank）
                no_repeat_blank = []
                pre_c = preb_label[0]
                blank_idx = len(CHARS) - 1
                if pre_c != blank_idx:
                    no_repeat_blank.append(pre_c)
                for c in preb_label:
                    if pre_c == c or c == blank_idx:
                        if c == blank_idx:
                            pre_c = c
                        continue
                    no_repeat_blank.append(c)
                    pre_c = c

                plate = ''.join([CHARS[idx] for idx in no_repeat_blank])
                plates.append(plate)

        return plates

    # ==================== 标注绘图 ====================

    # 查找系统中文字体
    CHINESE_FONT_PATHS = [
        "C:/Windows/Fonts/simhei.ttf",      # 黑体
        "C:/Windows/Fonts/msyh.ttc",        # 微软雅黑
        "C:/Windows/Fonts/simsun.ttc",      # 宋体
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",  # Linux
    ]

    @classmethod
    def _get_chinese_font(cls, size=24):
        """获取中文字体，找不到则回退到默认（会有??问题但不崩溃）"""
        from PIL import ImageFont
        for path in cls.CHINESE_FONT_PATHS:
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
        return ImageFont.load_default()

    def draw_boxes(self, image_path: str, boxes, plates, output_dir: str = None):
        """
        在原图上绘制检测框和车牌号（PIL 支持中文）
        """
        image = cv2.imread(image_path)
        if image is None:
            return None

        # 先用 PIL 画中文标签（PIL 的 RGB 模式）
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(image_rgb)
        from PIL import ImageDraw
        draw = ImageDraw.Draw(pil_img)
        font = self._get_chinese_font(size=26)

        for box, plate in zip(boxes, plates):
            x1, y1, x2, y2 = map(int, box)
            label_w = len(plate) * 18 + 10
            # PIL 画绿色背景标签
            draw.rectangle([x1, y1 - 32, x1 + label_w, y1], fill=(0, 255, 0))
            draw.text((x1 + 5, y1 - 30), plate, fill=(0, 0, 0), font=font)

        # PIL → BGR
        result = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

        # 再画绿色检测框（在标注文字之后画，确保框在最上层）
        for box in boxes:
            x1, y1, x2, y2 = map(int, box)
            cv2.rectangle(result, (x1, y1), (x2, y2), (0, 255, 0), 3)

        # 保存
        base, ext = os.path.splitext(image_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            base = os.path.join(output_dir, os.path.basename(base))
        annotated_path = f"{base}_annotated{ext}"
        cv2.imwrite(annotated_path, result)
        return annotated_path

    def _draw_on_frame(self, frame, boxes, plates):
        """在帧上画检测框和中文标签，返回标注帧（BGR格式，用于写视频）"""
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(frame_rgb)
        from PIL import ImageDraw
        draw = ImageDraw.Draw(pil_img)
        font = self._get_chinese_font(size=22)
        for box, plate in zip(boxes, plates):
            x1, y1, x2, y2 = map(int, box)
            label_w = len(plate) * 15 + 10
            draw.rectangle([x1, y1 - 28, x1 + label_w, y1], fill=(0, 255, 0))
            draw.text((x1 + 5, y1 - 26), plate, fill=(0, 0, 0), font=font)
        result = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        for box in boxes:
            x1, y1, x2, y2 = map(int, box)
            cv2.rectangle(result, (x1, y1), (x2, y2), (0, 255, 0), 2)
        return result

    # ==================== 单张图片完整推理 ====================

    def predict_image(self, image_path: str):
        """
        对一张图片执行完整推理：检测 → 裁剪 → 识别 → 画框标注
        返回:
            {
                "plates": ["京A12345", ...],
                "count": 1,
                "boxes": [[x1,y1,x2,y2], ...],
                "annotated_path": "/path/to/xxx_annotated.jpg"
            }
        """
        image = cv2.imread(image_path)
        if image is None:
            raise ValueError(f"无法读取图片: {image_path}")

        boxes = self.detect_plates(image)
        if len(boxes) == 0:
            return {"plates": [], "count": 0, "boxes": [], "annotated_path": None}

        cropped = self.crop_plates(image, boxes)
        plates = self.recognize(cropped)

        # 画框标注
        annotated = self.draw_boxes(image_path, boxes, plates)

        return {
            "plates": plates,
            "count": len(plates),
            "boxes": boxes.tolist() if hasattr(boxes, 'tolist') else boxes,
            "annotated_path": annotated
        }

    # ==================== 视频推理 ====================

    def predict_video(self, video_path: str, frame_interval: int = 1):
        """
        视频推理：抽帧 → 检测 → 识别 → 只返回 JSON（前端 Canvas 实时画框）

        返回:
            {
                "total_frames": 200,
                "fps": 30,
                "frame_interval": 10,
                "sampled_frames": 20,
                "results": [
                    {"frame": 0,  "plates": ["京A12345"], "boxes": [[221,418,434,489]]},
                    {"frame": 10, "plates": [],            "boxes": []},
                    ...
                ]
            }
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"无法打开视频: {video_path}")

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        self._last_video_fps = fps

        results = []
        frame_idx = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % frame_interval == 0:
                boxes = self.detect_plates(frame)
                frame_result = {"frame": frame_idx, "plates": [], "boxes": []}
                if len(boxes) > 0:
                    cropped = self.crop_plates(frame, boxes)
                    plates = self.recognize(cropped)
                    frame_result["plates"] = plates
                    frame_result["boxes"] = boxes.tolist() if hasattr(boxes, 'tolist') else boxes
                results.append(frame_result)

            frame_idx += 1

        cap.release()

        return {
            "total_frames": total_frames,
            "fps": fps,
            "frame_interval": frame_interval,
            "sampled_frames": len(results),
            "results": results
        }
