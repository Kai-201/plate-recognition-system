"""
Flask 推理服务 —— 提供 HTTP API 供 Java 后端调用
"""
import os
import sys
import traceback
import cv2
import numpy as np
import threading
from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
import json
from werkzeug.utils import secure_filename
from inference_engine import InferenceEngine

app = Flask(__name__)

# ==================== 配置 ====================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
YOLO_MODEL_PATH = os.path.join(BASE_DIR, "yolo-best.pt")
LPRNET_MODEL_PATH = os.path.join(BASE_DIR, "lprnet-best_model.pth")
CRNN_MODEL_PATH = os.path.join(BASE_DIR, "改版", "crnn_best.pth")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
ALLOWED_IMAGE = {'.jpg', '.jpeg', '.png', '.bmp', '.gif'}
ALLOWED_VIDEO = {'.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv'}
os.makedirs(UPLOAD_DIR, exist_ok=True)

# MinIO 客户端（Python 直接读写 MinIO）
from minio import Minio as MinioClientPy
minio_client = MinioClientPy("127.0.0.1:9000", access_key="minioadmin", secret_key="minioadmin", secure=False)
MINIO_BUCKET = "lpr-files"
if not minio_client.bucket_exists(MINIO_BUCKET):
    minio_client.make_bucket(MINIO_BUCKET)
print("[MinIO] 连接成功")

# 全局变量，启动时赋值
crnn_model = None
crnn_device = None

# ==================== 启动时加载模型 ====================

print("=" * 50)
print("正在加载模型，请稍候...")
print("=" * 50)

engine = InferenceEngine(
    yolo_path=YOLO_MODEL_PATH,
    lprnet_path=LPRNET_MODEL_PATH,
    lpr_max_len=8,
    class_num=68,
    dropout_rate=0.5
)

# 加载 YOLO 车辆检测模型（车牌检测不到时保底用）
from ultralytics import YOLO as YOLO_Class
yolo_car = YOLO_Class("yolov8n.pt")
print("[CarDetect] 车辆检测模型加载成功")

# 加载 CRNN（可选，切换 OCR 引擎用）
try:
    sys.path.insert(0, os.path.join(BASE_DIR, "改版"))
    from nets.crnn import CRNN
    from dataset import CHARS as CRNN_CHARS, LABEL2CHAR
    import torch as crnn_torch
    crnn_device = crnn_torch.device("cuda" if crnn_torch.cuda.is_available() else "cpu")
    crnn_model = CRNN(input_c=3, input_h=32, num_classes=len(CRNN_CHARS) + 1).to(crnn_device)
    if os.path.exists(CRNN_MODEL_PATH):
        crnn_model.load_state_dict(crnn_torch.load(CRNN_MODEL_PATH, map_location=crnn_device))
        crnn_model.eval()
        print("[CRNN] OCR 模型加载成功")
    else:
        print(f"[CRNN] 权重文件不存在: {CRNN_MODEL_PATH}")
except Exception as e:
    print(f"[CRNN] 加载失败（继续使用 LPRNet）: {e}")

print("=" * 50)
print("模型加载完成，服务就绪！")
print("=" * 50)


# ==================== MQ 消费者（后台线程） ====================

def start_mq_consumer():
    """后台线程：监听 RabbitMQ 视频推理任务，崩了自动重启"""
    import pika, time as _time

    MQ_HOST = "dog-01.lmq.cloudamqp.com"
    MQ_PORT = 5672
    MQ_USER = "pusvskws"; MQ_PASS = "r-2Rb9_m8n0nt-nrW6DYDwufRCN2AC1r"
    MQ_VHOST = "pusvskws"
    TASK_QUEUE = "lpr.tasks"; RESULT_QUEUE = "lpr.results"

    def consumer_loop():
        while True:
            try:
                params = pika.ConnectionParameters(
                    host=MQ_HOST, port=MQ_PORT, virtual_host=MQ_VHOST,
                    credentials=pika.PlainCredentials(MQ_USER, MQ_PASS),
                    heartbeat=600, blocked_connection_timeout=300)
                conn = pika.BlockingConnection(params)
                ch = conn.channel()
                ch.queue_declare(queue=TASK_QUEUE, durable=True)
                ch.queue_declare(queue=RESULT_QUEUE, durable=True)
                ch.basic_qos(prefetch_count=1)
                ch.basic_consume(queue=TASK_QUEUE, on_message_callback=on_task)
                print("[MQ] 视频推理消费者已启动")
                ch.start_consuming()
                break  # 正常退出
            except Exception as e:
                print(f"[MQ] 连接断开/异常: {e}, 5秒后重连...")
                _time.sleep(5)

    def on_task(ch, method, properties, body):
        task = json.loads(body)
        task_id = task["taskId"]
        minio_obj = task["minioObject"]
        ocr = task.get("ocr", "lprnet")
        frame_interval = task.get("frameInterval", 1)
        print(f"\n[MQ] 收到任务: {task_id}")

        try:
            # 下载 → 推理 → ffmpeg → 上传 MinIO
            local_path = os.path.join(UPLOAD_DIR, f"{task_id}.mp4")
            minio_client.fget_object(MINIO_BUCKET, minio_obj, local_path)

            cap = cv2.VideoCapture(local_path)
            fps = cap.get(cv2.CAP_PROP_FPS)
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            temp_video = os.path.join(UPLOAD_DIR, f"{task_id}_temp.mp4")
            writer = cv2.VideoWriter(temp_video, cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))

            results, last_boxes, last_plates = [], [], []
            frame_idx = 0
            import time
            t_start = time.time()
            while True:
                ret, frame = cap.read()
                if not ret: break
                fr = {"frame": frame_idx, "plates": [], "boxes": []}
                if frame_idx % frame_interval == 0:
                    boxes, crops, _ = detect_plates_with_fallback(frame, run_fallback=True)
                    if len(boxes) > 0:
                        plates = ocr_recognize(crops, ocr)
                        fr["plates"] = plates
                        fr["boxes"] = boxes.tolist() if hasattr(boxes, 'tolist') else list(boxes)
                        last_boxes, last_plates = fr["boxes"], plates
                        frame = engine._draw_on_frame(frame, boxes, plates)
                elif last_boxes:
                    fr["plates"] = last_plates; fr["boxes"] = last_boxes
                    frame = engine._draw_on_frame(frame,
                        np.array([list(map(float, b)) for b in last_boxes]), last_plates)
                results.append(fr); writer.write(frame); frame_idx += 1
            cap.release(); writer.release()
            print(f"[MQ] 推理完成: {task_id} {time.time()-t_start:.1f}s")

            # ffmpeg
            annotated_name = f"{task_id}_annotated.mp4"
            annotated_path = os.path.join(UPLOAD_DIR, annotated_name)
            ffmpeg = "ffmpeg"
            for p in [r"C:/Users/张开兴/AppData/Local/Microsoft/WinGet/Links/ffmpeg.exe",
                      r"D:/Free Download Manager/ffmpeg.exe"]:
                if os.path.exists(p): ffmpeg = p; break
            import subprocess as sp
            sp.run([ffmpeg, '-y', '-i', temp_video, '-i', local_path,
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                    '-c:a', 'aac', '-map', '0:v', '-map', '1:a', '-shortest',
                    annotated_path], capture_output=True)

            # 上传 MinIO
            minio_video_obj = f"videos/{annotated_name}"
            minio_client.fput_object(MINIO_BUCKET, minio_video_obj, annotated_path)
            annotated_url = minio_client.presigned_get_object(MINIO_BUCKET, minio_video_obj)

            # 返回结果（MQ 只传状态+URL，详细数据存 DB）
            result = {"taskId": task_id, "status": "SUCCESS",
                      "annotatedVideoUrl": annotated_url,
                      "fps": fps, "totalFrames": total}
            ch.basic_publish(exchange='', routing_key=RESULT_QUEUE,
                             body=json.dumps(result, default=str),
                             properties=pika.BasicProperties(delivery_mode=2))
            print(f"[MQ] 结果已发送: {task_id}")
            ch.basic_ack(delivery_tag=method.delivery_tag)  # 成功才确认

            for f in [local_path, temp_video, annotated_path]:
                try: os.remove(f)
                except: pass

        except Exception as e:
            traceback.print_exc()
            err = {"taskId": task_id, "status": "FAILED", "error": str(e)}
            ch.basic_publish(exchange='', routing_key=RESULT_QUEUE,
                             body=json.dumps(err),
                             properties=pika.BasicProperties(delivery_mode=2))
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)  # 失败不重回队列，避免死循环

    consumer_loop()

threading.Thread(target=start_mq_consumer, daemon=True).start()


# ==================== OCR 引擎切换 ====================

CAR_CLASSES = {2, 5, 7}

def iou(box_a, box_b):
    """计算两个框的 IoU"""
    x1 = max(box_a[0], box_b[0]); y1 = max(box_a[1], box_b[1])
    x2 = min(box_a[2], box_b[2]); y2 = min(box_a[3], box_b[3])
    if x2 <= x1 or y2 <= y1: return 0
    inter = (x2 - x1) * (y2 - y1)
    area_a = (box_a[2] - box_a[0]) * (box_a[3] - box_a[1])
    area_b = (box_b[2] - box_b[0]) * (box_b[3] - box_b[1])
    return inter / (area_a + area_b - inter + 1e-6)

def detect_plates_full(frame):
    """
    全量检测：直接检测 + 车辆检测 → IoU 去重合并
    返回: (plate_boxes, plate_crops, car_boxes)
    """
    h, w = frame.shape[:2]

    # 1. 直接检测
    direct_boxes = engine.detect_plates(frame)
    direct_boxes = direct_boxes.tolist() if len(direct_boxes) > 0 else []

    # 2. 车辆检测 → 裁剪 → 找车牌
    car_results = yolo_car.predict(frame, imgsz=640, conf=0.3, classes=[2,5,7], verbose=False)
    car_boxes = car_results[0].boxes.xyxy.cpu().numpy() if car_results[0].boxes is not None and len(car_results[0].boxes) > 0 else []
    car_plate_boxes = []

    for cbox in car_boxes:
        cx1, cy1, cx2, cy2 = map(int, cbox)
        cw, ch = cx2 - cx1, cy2 - cy1
        cx1 = max(0, cx1 - int(cw * 0.1)); cx2 = min(w, cx2 + int(cw * 0.1))
        cy1 = max(0, cy1 - int(ch * 0.2)); cy2 = min(h, cy2 + int(ch * 0.2))
        car_crop = frame[cy1:cy2, cx1:cx2]
        pboxes = engine.detect_plates(car_crop)
        for pb in pboxes:
            px1, py1, px2, py2 = pb
            car_plate_boxes.append([cx1 + px1, cy1 + py1, cx1 + px2, cy1 + py2])

    # 3. IoU 合并去重
    all_candidate = direct_boxes + car_plate_boxes
    merged = []
    used = set()
    for i, a in enumerate(all_candidate):
        if i in used: continue
        for j, b in enumerate(all_candidate):
            if j <= i or j in used: continue
            if iou(a, b) > 0.5:  # 重叠度高 → 同一车牌，跳过
                used.add(j)
        merged.append(a)

    if len(merged) > len(direct_boxes):
        print(f"[全量] 直接{len(direct_boxes)}+车辆{len(car_plate_boxes)} → 合并去重{len(merged)}")

    all_boxes = np.array(merged) if merged else []
    all_crops = engine.crop_plates(frame, all_boxes) if len(all_boxes) > 0 else []
    return all_boxes, all_crops, car_boxes

def detect_plates_with_fallback(frame, run_fallback=True):
    """直接检测 → (仅全量帧)找不到则车辆检测+IoU合并"""
    boxes = engine.detect_plates(frame)
    if len(boxes) > 0:
        return boxes, engine.crop_plates(frame, boxes), []
    if run_fallback:
        return detect_plates_full(frame)
    return [], [], []

def ocr_recognize(cropped_images, model='lprnet'):
    """统一 OCR 入口，支持切换引擎"""
    if model == 'crnn' and crnn_model is not None:
        return _crnn_recognize(cropped_images)
    return engine.recognize(cropped_images)  # 默认 LPRNet

def _crnn_recognize(cropped_images):
    """CRNN OCR：100×32 RGB 输入，blank=0"""
    plates = []
    for img in cropped_images:
        if len(img.shape) == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
        else:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, (100, 32))
        img = img.astype('float32') / 255.0
        img = (img - 0.5) / 0.5
        img = np.transpose(img, (2, 0, 1))
        inp = crnn_torch.from_numpy(img).unsqueeze(0).to(crnn_device)
        with crnn_torch.no_grad():
            output = crnn_model(inp)
        pred = output.argmax(dim=2).squeeze(1).cpu().numpy()
        result, prev = [], -1
        for p in pred:
            if p != prev and p != 0:
                result.append(p)
            prev = p
        plates.append(''.join([LABEL2CHAR.get(c, '?') for c in result]))
    return plates


# ==================== 辅助函数 ====================

def allowed_file(filename: str, allowed_set: set) -> bool:
    """检查文件扩展名是否合法"""
    _, ext = os.path.splitext(filename)
    return ext.lower() in allowed_set


# ==================== API 路由 ====================

@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    """提供上传文件和标注图的访问"""
    return send_from_directory(UPLOAD_DIR, filename)


@app.route('/health', methods=['GET'])
def health():
    """健康检查"""
    return jsonify({
        "status": "ok",
        "device": str(engine.device)
    })


@app.route('/inference/image', methods=['POST'])
def inference_image():
    """
    单张图片推理
    请求: multipart/form-data, 字段名 "file"
    返回: {"success": true, "data": {"plates": [...], "count": N, "boxes": [...], "annotated_path": "..."}}
    """
    # 支持两种方式：multipart 或 MinIO 对象名
    import uuid
    minio_obj = request.form.get('minio_object', '')
    if minio_obj:
        safe_name = minio_obj.replace('\\', '/').split('/')[-1]
        saved_name = f"{uuid.uuid4().hex}_{safe_name}"
        saved_path = os.path.join(UPLOAD_DIR, saved_name)
        minio_client.fget_object(MINIO_BUCKET, minio_obj, saved_path)
    elif 'file' in request.files:
        file = request.files['file']
        if file.filename == '' or not allowed_file(file.filename, ALLOWED_IMAGE):
            return jsonify({"success": False, "error": "不支持的文件格式"}), 400
        safe_name = secure_filename(file.filename)
        saved_name = f"{uuid.uuid4().hex}_{safe_name}"
        saved_path = os.path.join(UPLOAD_DIR, saved_name)
        file.save(saved_path)
    else:
        return jsonify({"success": False, "error": "缺少文件或minio_object"}), 400

    try:
        image = cv2.imread(saved_path)
        if image is None:
            return jsonify({"success": False, "error": "无法读取图片"}), 400

        # 保底检测：直接检测 → 找不到则先找车再找车牌
        boxes, crops, _ = detect_plates_with_fallback(image, run_fallback=True)
        plates = ocr_recognize(crops, request.args.get('ocr', 'lprnet')) if len(boxes) > 0 else []

        # 画框
        annotated_path = None
        if len(boxes) > 0:
            annotated = engine.draw_boxes(saved_path, boxes, plates)
            annotated_path = annotated

        result = {
            "plates": plates, "count": len(plates),
            "boxes": boxes.tolist() if hasattr(boxes, 'tolist') else boxes if len(boxes) > 0 else [],
        }
        # 上传标注图到 MinIO
        if annotated_path:
            img_obj = f"images/{os.path.basename(annotated_path)}"
            minio_client.fput_object(MINIO_BUCKET, img_obj, annotated_path)
            result["annotated_url"] = minio_client.presigned_get_object(MINIO_BUCKET, img_obj)
        # 清理本地文件
        try: os.remove(saved_path)
        except: pass
        if annotated_path:
            try: os.remove(annotated_path)
            except: pass
        return jsonify({"success": True, "data": result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/inference/video', methods=['POST'])
def inference_video():
    """
    视频推理（批处理）：逐帧检测识别 + 画框 + 合成标注 MP4
    返回: {"success": true, "data": {"fps":30, "results":[...], "annotated_video_url":"/uploads/xxx.mp4"}}
    """
    # 支持两种方式：multipart 上传 或 MinIO 对象名
    import uuid
    minio_obj = request.form.get('minio_object', '')
    if minio_obj:
        # 从 MinIO 下载（兼容 Windows 路径→提取文件名）
        safe_name = minio_obj.replace('\\', '/').split('/')[-1]
        saved_name = f"{uuid.uuid4().hex}_{safe_name}"
        saved_path = os.path.join(UPLOAD_DIR, saved_name)
        minio_client.fget_object(MINIO_BUCKET, minio_obj, saved_path)
    elif 'file' in request.files:
        file = request.files['file']
        if file.filename == '' or not allowed_file(file.filename, ALLOWED_VIDEO):
            return jsonify({"success": False, "error": "不支持的文件格式"}), 400
        safe_name = secure_filename(file.filename)
        saved_name = f"{uuid.uuid4().hex}_{safe_name}"
        saved_path = os.path.join(UPLOAD_DIR, saved_name)
        file.save(saved_path)
    else:
        return jsonify({"success": False, "error": "缺少文件或minio_object"}), 400

    try:
        cap = cv2.VideoCapture(saved_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        detect_interval = int(request.form.get('frame_interval', 1))
        ocr_model = request.args.get('ocr', 'lprnet')

        import time
        t_start = time.time()

        temp_video = os.path.join(UPLOAD_DIR, os.path.splitext(saved_name)[0] + "_temp.mp4")
        writer = cv2.VideoWriter(temp_video, cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))

        results = []
        frame_idx = 0
        last_boxes, last_plates = [], []
        t_detect, t_recognize, t_draw, t_write, t_read = 0.0, 0.0, 0.0, 0.0, 0.0
        detect_count, total_boxes = 0, 0

        while True:
            t0 = time.time()
            ret, frame = cap.read()
            t_read += time.time() - t0
            if not ret: break
            fr = {"frame": frame_idx, "plates": [], "boxes": []}

            if frame_idx % detect_interval == 0:
                detect_count += 1
                t0 = time.time()
                boxes, crops, car_boxes = detect_plates_with_fallback(frame, run_fallback=True)
                t_detect += time.time() - t0
                if len(boxes) > 0:
                    total_boxes += 1
                    t0 = time.time()
                    plates = ocr_recognize(crops, ocr_model)
                    t_recognize += time.time() - t0
                    fr["plates"] = plates
                    fr["boxes"] = boxes.tolist() if hasattr(boxes, 'tolist') else boxes
                    last_boxes = fr["boxes"]
                    last_plates = plates
                    t0 = time.time()
                    frame = engine._draw_on_frame(frame, boxes, plates)
                    t_draw += time.time() - t0
            elif last_boxes:
                fr["plates"] = last_plates
                fr["boxes"] = last_boxes
                t0 = time.time()
                frame = engine._draw_on_frame(frame,
                    np.array([list(map(float, b)) for b in last_boxes]), last_plates)
                t_draw += time.time() - t0

            if frame_idx % detect_interval == 0:
                for cb in car_boxes:
                    cv2.rectangle(frame, tuple(map(int, cb[:2])), tuple(map(int, cb[2:])), (255, 0, 0), 1)

            results.append(fr)
            t0 = time.time()
            writer.write(frame)
            t_write += time.time() - t0
            frame_idx += 1

        cap.release()
        writer.release()
        t_total = time.time() - t_start
        print(f"[耗时明细][{ocr_model}] 总{t_total:.1f}s | 读帧{t_read:.1f}s | "
              f"检测({detect_count}次){t_detect:.1f}s | 识别({total_boxes}次){t_recognize:.1f}s | "
              f"画框{t_draw:.1f}s | 写视频{t_write:.1f}s | "
              f"({frame_idx}帧, 间隔{detect_interval})")

        # ffmpeg 合成 → 上传 MinIO
        annotated_name = os.path.splitext(saved_name)[0] + "_annotated.mp4"
        annotated_video = os.path.join(UPLOAD_DIR, annotated_name)
        # 自动找 ffmpeg（winget/PATH/手动下载）
        ffmpeg_exe = "ffmpeg"
        for possible in [
            r"C:/Users/张开兴/AppData/Local/Microsoft/WinGet/Links/ffmpeg.exe",
            r"D:/Free Download Manager/ffmpeg.exe",
        ]:
            if os.path.exists(possible):
                ffmpeg_exe = possible; break
        ffmpeg_cmd = (
            f'"{ffmpeg_exe}" -y '
            f'-i "{temp_video}" -i "{saved_path}" '
            f'-c:v libx264 -preset fast -crf 23 '
            f'-c:a aac -map 0:v -map 1:a -shortest '
            f'"{annotated_video}"'
        )
        import subprocess
        t_ff = time.time()
        print(f"[FFmpeg] 合成视频: {annotated_video}")
        proc = subprocess.run(ffmpeg_cmd, shell=True, capture_output=True, text=True)
        print(f"[耗时] FFmpeg合成: {time.time() - t_ff:.1f}s")
        if proc.returncode != 0:
            print(f"[FFmpeg] 失败: {proc.stderr[:500]}")

        # 上传标注视频到 MinIO
        minio_video_obj = f"videos/{annotated_name}"
        minio_client.fput_object(MINIO_BUCKET, minio_video_obj, annotated_video)
        minio_video_url = minio_client.presigned_get_object(MINIO_BUCKET, minio_video_obj)
        # 清理本地文件
        try: os.remove(saved_path)
        except: pass
        try: os.remove(temp_video)
        except: pass
        try: os.remove(annotated_video)
        except: pass

        return jsonify({"success": True, "data": {
            "fps": fps, "total_frames": total,
            "results": results,
            "annotated_video_url": minio_video_url,
            "video_url": f"/uploads/{saved_name}"
        }})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/inference/video/stream', methods=['POST'])
def inference_video_stream():
    """
    视频流式推理：逐帧检测，SSE 实时推送
    请求: multipart/form-data, 字段名 "file"
    返回: text/event-stream，每帧一个 data: {json}\n\n
    """
    if 'file' not in request.files:
        return jsonify({"error": "缺少文件"}), 400
    file = request.files['file']
    if file.filename == '' or not allowed_file(file.filename, ALLOWED_VIDEO):
        return jsonify({"error": "不支持的文件格式"}), 400

    import uuid
    safe_name = secure_filename(file.filename)
    saved_name = f"{uuid.uuid4().hex}_{safe_name}"
    saved_path = os.path.join(UPLOAD_DIR, saved_name)
    file.save(saved_path)

    def generate():
        cap = cv2.VideoCapture(saved_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frame_idx = 0

        # 输出标注视频
        annotated_name = os.path.splitext(saved_name)[0] + "_annotated.mp4"
        annotated_path = os.path.join(UPLOAD_DIR, annotated_name)
        writer = cv2.VideoWriter(annotated_path, cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))

        yield f"data: {json.dumps({'type': 'meta', 'total_frames': total_frames, 'fps': fps})}\n\n"

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            full_detect = (frame_idx % 10 == 0)
            run_fb = (frame_idx % 10 == 0)
            boxes, crops, car_boxes = detect_plates_with_fallback(frame, run_fallback=run_fb)
            plates = []
            if len(boxes) > 0:
                plates = ocr_recognize(crops, request.args.get('ocr', 'lprnet'))
                frame = engine._draw_on_frame(frame, boxes, plates)
            for cb in car_boxes:
                cv2.rectangle(frame, tuple(map(int, cb[:2])), tuple(map(int, cb[2:])), (255, 0, 0), 1)

            writer.write(frame)

            # 每10帧推一次进度
            if frame_idx % 10 == 0:
                yield f"data: {json.dumps({'type': 'progress', 'frame': frame_idx, 'plates': plates})}\n\n"

            frame_idx += 1

        cap.release()
        writer.release()
        yield f"data: {json.dumps({'type': 'done', 'fps': fps, 'video_url': f'/uploads/{saved_name}', 'annotated_video_url': f'/uploads/{annotated_name}'})}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


# ==================== 启动 ====================

if __name__ == '__main__':
    port = int(os.environ.get('INFERENCE_PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
