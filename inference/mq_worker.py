"""
RabbitMQ 消费者：接收 Java 的推理任务，处理完发回结果
启动: python mq_worker.py
"""
import os, sys, json, time, cv2, numpy as np, pika, traceback
from minio import Minio

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from inference_engine import InferenceEngine
sys.path.insert(0, os.path.join(BASE_DIR, "改版"))

# ===== MQ 配置 =====
MQ_HOST = "dog-01.lmq.cloudamqp.com"
MQ_PORT = 5672
MQ_USER = "pusvskws"
MQ_PASS = "r-2Rb9_m8n0nt-nrW6DYDwufRCN2AC1r"
MQ_VHOST = "pusvskws"
TASK_QUEUE = "lpr.tasks"
RESULT_QUEUE = "lpr.results"

# ===== MinIO =====
minio_client = Minio("127.0.0.1:9000", access_key="minioadmin", secret_key="minioadmin", secure=False)
MINIO_BUCKET = "lpr-files"
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ===== 加载模型 =====
print("加载推理模型...")
engine = InferenceEngine(
    yolo_path=os.path.join(BASE_DIR, "yolo-best.pt"),
    lprnet_path=os.path.join(BASE_DIR, "lprnet-best_model.pth"),
    lpr_max_len=8, class_num=68, dropout_rate=0.5
)
print(f"设备: {engine.device}")
print("等待任务...")

# ===== MQ 回调 =====
def on_task(ch, method, properties, body):
    task = json.loads(body)
    task_id = task["taskId"]
    minio_obj = task["minioObject"]
    ocr = task.get("ocr", "lprnet")
    frame_interval = task.get("frameInterval", 1)
    print(f"\n[MQ] 收到任务: {task_id}")

    try:
        # 1. 从 MinIO 下载
        local_name = f"{task_id}.mp4"
        local_path = os.path.join(UPLOAD_DIR, local_name)
        minio_client.fget_object(MINIO_BUCKET, minio_obj, local_path)

        # 2. 开视频
        cap = cv2.VideoCapture(local_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        temp_video = os.path.join(UPLOAD_DIR, f"{task_id}_temp.mp4")
        writer = cv2.VideoWriter(temp_video, cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))

        from app import detect_plates_with_fallback, ocr_recognize
        results, last_boxes, last_plates = [], [], []
        frame_idx = 0

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
            results.append(fr)
            writer.write(frame)
            frame_idx += 1

        cap.release(); writer.release()

        # 3. ffmpeg 合成
        annotated_name = f"{task_id}_annotated.mp4"
        annotated_path = os.path.join(UPLOAD_DIR, annotated_name)
        os.system(f'ffmpeg -y -i {temp_video} -i {local_path} '
                  f'-c:v libx264 -preset fast -crf 23 -c:a aac -map 0:v -map 1:a -shortest '
                  f'{annotated_path} 2>nul')

        # 4. 上传标注视频到 MinIO
        minio_video_obj = f"videos/{annotated_name}"
        minio_client.fput_object(MINIO_BUCKET, minio_video_obj, annotated_path)
        annotated_url = minio_client.presigned_get_object(MINIO_BUCKET, minio_video_obj)

        # 5. 发结果回 Java
        result = {"taskId": task_id, "status": "SUCCESS", "data": {
            "fps": fps, "total_frames": total, "results": results,
            "annotated_video_url": annotated_url
        }}
        ch.basic_publish(exchange='', routing_key=RESULT_QUEUE,
                         body=json.dumps(result, default=str),
                         properties=pika.BasicProperties(delivery_mode=2))
        print(f"[MQ] 任务完成: {task_id}")

        # 清理本地
        for f in [local_path, temp_video, annotated_path]:
            try: os.remove(f)
            except: pass

    except Exception as e:
        traceback.print_exc()
        err = {"taskId": task_id, "status": "FAILED", "error": str(e)}
        ch.basic_publish(exchange='', routing_key=RESULT_QUEUE,
                         body=json.dumps(err),
                         properties=pika.BasicProperties(delivery_mode=2))

    ch.basic_ack(delivery_tag=method.delivery_tag)

# ===== 启动消费者 =====
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
print("MQ 消费者就绪，等待任务...")
ch.start_consuming()
