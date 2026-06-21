# 智识车牌 — 基于 YOLOv8 + LPRNet/CRNN 的车牌识别系统

Java + Python 异构协作的车牌识别系统，支持图片/视频上传、秒传去重、标注结果展示与历史记录查询。

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3 + Vite + Axios |
| 后端 | SpringBoot 2.7 + MyBatis-Plus + MySQL |
| 消息队列 | RabbitMQ（死信队列 + TTL + 指数退避重试） |
| 实时推送 | SSE（Server-Sent Events） |
| 推理服务 | Flask + PyTorch + YOLOv8 + LPRNet/CRNN |
| 对象存储 | MinIO（直传 + 预签名 URL） |
| 视频处理 | OpenCV + FFmpeg（H.264 编码） |

## 项目结构

```
├── frontend/         # Vue 3 前端
├── backend/          # Java SpringBoot 后端
├── inference/        # Python Flask 推理服务
│   ├── app.py                    # Flask 主入口 + MQ 消费者
│   ├── inference_engine.py       # 推理引擎（YOLO + LPRNet）
│   ├── ocr_crnn/                 # CRNN OCR 模型
│   └── requirements.txt
├── sql/              # 数据库初始化
└── start.bat         # 一键启动脚本
```

## 注意事项

- **消息队列**：项目使用 CloudAMQP，需自行在 `application.yml` 配置 RabbitMQ 连接信息（`spring.rabbitmq.*`），Python 端在 `app.py` 中修改 `MQ_HOST` 等参数
- **MinIO**：启动后需手动创建 bucket `lpr-files`
- **模型限制**：YOLO 车牌检测 + LPRNet 字符识别模型基于 **CCPD 绿牌数据集**训练，训练数据多为 **皖** 车牌。因此对**蓝牌**及其他省份车牌的识别准确率**较低**，仅供学习参考

## 快速启动

### 环境要求

- JDK 8+、Maven 3.6+
- Python 3.10+、PyTorch（GPU 可选）
- MySQL 8.0、MinIO、RabbitMQ（或 CloudAMQP）
- Node.js 16+

### 1. 数据库

```sql
source sql/init.sql
```

### 2. MinIO

```powershell
minio.exe server D:\minio-data --console-address :9001
# 创建 bucket: lpr-files
```

### 3. Python 推理服务

```bash
cd inference
pip install -r requirements.txt
python app.py    # 启动 Flask + MQ 消费者
```

### 4. Java 后端

```bash
cd backend
mvn spring-boot:run
# 端口: 8080
# 配置文件: application.yml（修改 MySQL/MQ/MinIO 连接信息）
```

### 5. 前端

```bash
cd frontend
npm install
npm run dev
# 访问: http://localhost:3000
```

## 核心架构

```
前端 → MinIO 直传 → Java 接收通知 → RabbitMQ 异步解耦
                                           ↓
                                    Python 消费推理
                                           ↓
                              YOLOv8 检测 → LPRNet/CRNN 识别
                                           ↓
                              标注视频/图片 → MinIO → 前端直连加载
                                           ↓
                              SSE 实时推送结果 → 前端展示
```

## 主要特性

- **秒传去重**：采样 SHA-256 文件指纹 + 唯一索引防并发
- **异步解耦**：RabbitMQ 持久队列 + 生产者/消费者双端确认 + 死信队列
- **双阶段检测**：直接检测 + 车辆检测 + IoU 合并去重保底
- **双模型 OCR**：LPRNet / CRNN 可切换，CTC 解码
- **SSE 推送**：多客户端同时订阅同一任务结果，轮询兜底
- **全链路 MinIO**：前端直传、推理端下载/上传、前端直连，后端不碰文件
- **幂等保障**：消费者查 DB 状态机，已处理消息直接跳过
