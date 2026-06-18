package com.lpr.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.lpr.mapper.RecognitionTaskMapper;
import com.lpr.model.RecognitionResultVO;
import com.lpr.model.RecognitionTask;
import com.lpr.websocket.RecognitionWebSocketHandler;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import javax.annotation.Resource;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Collectors;

/**
 * 识别业务 Service —— 核心业务逻辑
 *
 * 流程：
 * 1. 接收文件 → 生成 taskId → 保存文件到磁盘 → 创建数据库记录(状态=PENDING) → 返回 taskId
 * 2. @Async 异步执行 → 调 Python 推理 → 更新数据库 → WebSocket 推送结果
 *
 * 设计思考：
 * - 为什么不用消息队列（RabbitMQ/RocketMQ）？
 *   当前是单机小项目，@Async 足够。企业高并发场景下，改为 MQ 解耦，
 *   实现"上传服务"和"推理消费"独立部署。
 */
@Service
public class RecognitionService {

    private static final Logger log = LoggerFactory.getLogger(RecognitionService.class);

    @Resource
    private RecognitionTaskMapper taskMapper;

    @Resource
    private PythonInferenceClient pythonClient;

    @Resource
    private RecognitionWebSocketHandler wsHandler;

    @Resource
    private MinioService minioService;

    @org.springframework.context.annotation.Lazy
    @Resource
    private RecognitionService self;  // 注入自己的代理，让 @Async 生效

    @Value("${file.upload.path}")
    private String uploadPath;

    // ==================== 秒传检查 ====================

    /**
     * 根据文件 MD5 检查是否已有识别记录（秒传）
     * 如果已存在 → 返回历史结果
     * 如果不存在 → 返回 null
     */
    public RecognitionResultVO checkByHash(String fileHash) {
        if (fileHash == null || fileHash.isEmpty()) return null;
        RecognitionTask existing = taskMapper.selectOne(
                new LambdaQueryWrapper<RecognitionTask>()
                        .eq(RecognitionTask::getFileHash, fileHash)
                        .eq(RecognitionTask::getStatus, "SUCCESS")
                        .orderByDesc(RecognitionTask::getCreateTime)
                        .last("LIMIT 1"));
        return existing != null ? toVO(existing) : null;
    }

    /**
     * 计算文件 MD5
     */
    public String computeHash(InputStream inputStream) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] buffer = new byte[8192];
            int read;
            while ((read = inputStream.read(buffer)) != -1) {
                md.update(buffer, 0, read);
            }
            byte[] digest = md.digest();
            StringBuilder sb = new StringBuilder();
            for (byte b : digest) sb.append(String.format("%02x", b));
            return sb.toString();
        } catch (Exception e) {
            return null;
        }
    }

    // ==================== 文件上传与任务创建 ====================

    /**
     * 接收上传文件，创建识别任务
     *
     * @param file 上传的文件（图片或视频）
     * @return taskId 供前端建立 WebSocket 连接和查询结果
     */
    public String submitTask(MultipartFile file, String ocr) {
        // 1. 生成任务ID + 计算 Hash
        String taskId = UUID.randomUUID().toString().replace("-", "");
        String originalName = file.getOriginalFilename();
        String fileType = getFileType(originalName);
        String fileHash = computeFileHash(file);

        // 2. 保存文件到磁盘
        String savedPath = saveFile(file, taskId, originalName);

        // 3. 创建数据库记录
        RecognitionTask task = new RecognitionTask();
        task.setTaskId(taskId);
        task.setFileName(originalName);
        task.setFileType(fileType);
        task.setFileHash(fileHash);
        task.setFilePath(savedPath);
        task.setStatus("PENDING");
        task.setCreateTime(LocalDateTime.now());
        taskMapper.insert(task);

        log.info("任务创建成功: taskId={}, type={}, file={}, ocr={}", taskId, fileType, originalName, ocr);

        // 4. 异步执行推理
        if ("image".equals(fileType)) {
            self.processImageAsync(task);
        } else {
            self.processVideoAsync(task, ocr);
        }

        return taskId;
    }

    /**
     * 同步处理图片——直接返回结果，不用异步+WebSocket
     *
     * 图片推理通常 < 1 秒，异步反而增加复杂度（WebSocket 握手比推理还慢）。
     * 视频推理可能需要几十秒，必须异步。
     */
    public RecognitionResultVO processImageSync(MultipartFile file, String ocr) {
        String taskId = UUID.randomUUID().toString().replace("-", "");
        String originalName = file.getOriginalFilename();
        String fileHash = computeFileHash(file);
        String savedPath = saveFile(file, taskId, originalName);

        RecognitionTask task = new RecognitionTask();
        task.setTaskId(taskId);
        task.setFileName(originalName);
        task.setFileType("image");
        task.setFileHash(fileHash);
        task.setFilePath(savedPath);
        task.setStatus("PROCESSING");
        task.setCreateTime(LocalDateTime.now());
        taskMapper.insert(task);

        try {
            JsonNode response = pythonClient.inferenceImageByMinio(savedPath, ocr);
            JsonNode data = response.get("data");

            task.setStatus("SUCCESS");
            task.setPlatesJson(data.toString());
            task.setCompleteTime(LocalDateTime.now());
            taskMapper.updateById(task);

            log.info("图片同步识别完成: taskId={}, plates={}", taskId, data.get("plates"));
            RecognitionResultVO vo = toVO(task);
            // Python 已直传 MinIO，URL 直接用
            if (data.has("annotated_url") && !data.get("annotated_url").isNull())
                vo.setAnnotatedImageUrl(data.get("annotated_url").asText());
            return vo;

        } catch (Exception e) {
            log.error("图片同步识别失败: taskId={}", taskId, e);
            task.setStatus("FAILED");
            task.setErrorMsg(e.getMessage());
            task.setCompleteTime(LocalDateTime.now());
            taskMapper.updateById(task);
            return toVO(task);
        }
    }

    /**
     * 重新识别：取已有任务的本地文件，用最新推理逻辑重新跑
     */
    public RecognitionResultVO retryTask(String taskId) {
        RecognitionTask task = taskMapper.selectOne(
                new LambdaQueryWrapper<RecognitionTask>().eq(RecognitionTask::getTaskId, taskId));
        if (task == null) return null;
        File file = new File(task.getFilePath());
        if (!file.exists()) return null;

        if ("video".equals(task.getFileType())) {
            // 视频：异步重新处理
            self.processVideoAsync(task);
            return toVO(task);
        } else {
            try {
                String fp = task.getFilePath();
                JsonNode response;
                if (fp.startsWith("uploads/")) {
                    response = pythonClient.inferenceImageByMinio(fp, "lprnet");
                } else {
                    response = pythonClient.inferenceImage(fp);  // 旧本地路径
                }
                JsonNode data = response.get("data");
                task.setStatus("SUCCESS");
                task.setPlatesJson(data.toString());
                task.setCompleteTime(LocalDateTime.now());
                taskMapper.updateById(task);
                return toVO(task);
            } catch (Exception e) {
                task.setStatus("FAILED");
                task.setErrorMsg(e.getMessage());
                taskMapper.updateById(task);
                return toVO(task);
            }
        }
    }

    /** MinIO 直传后，下载并同步识别图片 */
    public RecognitionResultVO processFromMinio(String taskId, String objectName) {
        try {
            RecognitionTask task = new RecognitionTask();
            task.setTaskId(taskId);
            task.setFileName(objectName.substring(objectName.lastIndexOf('/') + 1));
            task.setFileType("image");
            task.setFilePath(objectName);  // 存 MinIO 对象名
            task.setStatus("PROCESSING");
            task.setCreateTime(LocalDateTime.now());
            taskMapper.insert(task);

            JsonNode response = pythonClient.inferenceImageByMinio(objectName, "lprnet");
            JsonNode data = response.get("data");
            task.setStatus("SUCCESS");
            task.setPlatesJson(data.toString());
            task.setCompleteTime(LocalDateTime.now());
            taskMapper.updateById(task);

            RecognitionResultVO vo = toVO(task);
            // 上传标注图到 MinIO
            if (data.has("annotated_url") && !data.get("annotated_url").isNull()) {
                String flaskPath = data.get("annotated_url").asText();
                String filename = flaskPath.substring(flaskPath.lastIndexOf('/') + 1);
                java.io.File annotatedFile = new java.io.File(
                    "C:/Users/张开兴/Desktop/车牌识别/inference/uploads", filename);
                if (annotatedFile.exists()) {
                    String minioName = "images/" + taskId + "_annotated.jpg";
                    minioService.uploadFromFile(annotatedFile, minioName);
                    vo.setAnnotatedImageUrl(minioService.getUrl(minioName));
                }
            }
            return vo;
        } catch (Exception e) {
            throw new RuntimeException("MinIO 处理失败", e);
        }
    }

    /** MinIO 直传后，下载并异步处理视频 */
    public String submitFromMinio(String taskId, String objectName) {
        RecognitionTask task = new RecognitionTask();
        task.setTaskId(taskId);
        task.setFileName(objectName.substring(objectName.lastIndexOf('/') + 1));
        task.setFileType("video");
        task.setFilePath(objectName);  // 存 MinIO 对象名
        task.setStatus("PENDING");
        task.setCreateTime(LocalDateTime.now());
        taskMapper.insert(task);

        self.processVideoAsync(task);
        return taskId;
    }

    /** 公开文件类型判断，Controller 也需要用 */
    public String getFileTypeText(String fileName) {
        return getFileType(fileName);
    }

    private String computeFileHash(MultipartFile file) {
        try (InputStream is = file.getInputStream()) {
            return computeHash(is);
        } catch (IOException e) {
            return null;
        }
    }

    // ==================== 异步推理（@Async） ====================

    /**
     * 异步处理图片识别
     *
     * @Async 注解会让该方法在一个独立的线程中执行，
     * 不阻塞 Controller 的 HTTP 响应线程。
     */
    @Async("recognitionExecutor")
    public void processImageAsync(RecognitionTask task) {
        try {
            // 更新状态：处理中
            task.setStatus("PROCESSING");
            taskMapper.updateById(task);

            // 调 Python 推理
            JsonNode response = pythonClient.inferenceImage(task.getFilePath());
            JsonNode data = response.get("data");

            // 更新状态：成功
            task.setStatus("SUCCESS");
            task.setPlatesJson(data.toString());
            task.setCompleteTime(LocalDateTime.now());
            taskMapper.updateById(task);

            // WebSocket 推送结果
            pushResult(task, data);

            log.info("图片识别完成: taskId={}, plates={}", task.getTaskId(), data.get("plates"));

        } catch (Exception e) {
            log.error("图片识别失败: taskId={}", task.getTaskId(), e);
            task.setStatus("FAILED");
            task.setErrorMsg(e.getMessage());
            task.setCompleteTime(LocalDateTime.now());
            taskMapper.updateById(task);
            Map<String, Object> errResult = new HashMap<>();
            errResult.put("status", "FAILED");
            errResult.put("error", e.getMessage());
            wsHandler.pushResult(task.getTaskId(), errResult);
        }
    }

    /**
     * 异步处理视频识别
     */
    @Async("recognitionExecutor")
    public void processVideoAsync(RecognitionTask task) {
        processVideoAsync(task, "lprnet");
    }

    @Async("recognitionExecutor")
    public void processVideoAsync(RecognitionTask task, String ocr) {
        try {
            task.setStatus("PROCESSING");
            taskMapper.updateById(task);

            // Python 直接从 MinIO 下载原始视频
            long pyStart = System.currentTimeMillis();
            JsonNode response = pythonClient.inferenceVideoByMinio(task.getFilePath(), 1, ocr);
            long pyEnd = System.currentTimeMillis();
            log.info("[耗时] Python推理+合成: {}ms", pyEnd - pyStart);
            JsonNode data = response.get("data");

            // 只存摘要，不存全量帧数据
            java.util.Map<String, Object> summary = new HashMap<>();
            summary.put("fps", data.has("fps") ? data.get("fps").asDouble() : 0);
            summary.put("total_frames", data.has("total_frames") ? data.get("total_frames").asInt() : 0);
            if (data.has("annotated_video_url") && !data.get("annotated_video_url").isNull())
                summary.put("annotated_video_url", data.get("annotated_video_url").asText());
            if (data.has("video_url") && !data.get("video_url").isNull())
                summary.put("video_url", data.get("video_url").asText());
            // 只保留有车牌的关键帧
            JsonNode results = data.get("results");
            if (results != null && results.isArray()) {
                java.util.List<Map<String, Object>> keyframes = new java.util.ArrayList<>();
                for (JsonNode fr : results) {
                    if (fr.has("plates") && fr.get("plates").size() > 0) {
                        Map<String, Object> kf = new HashMap<>();
                        kf.put("frame", fr.get("frame").asInt());
                        kf.put("plates", fr.get("plates").toString());
                        keyframes.add(kf);
                    }
                }
                summary.put("plates_detected", keyframes.size());
                summary.put("keyframes", keyframes);
            }
            task.setPlatesJson(new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(summary));

            task.setStatus("SUCCESS");
            task.setCompleteTime(LocalDateTime.now());
            taskMapper.updateById(task);

            RecognitionResultVO vo = toVO(task);
            wsHandler.pushResult(task.getTaskId(), vo);
            long totalTime = java.time.Duration.between(task.getCreateTime(), LocalDateTime.now()).toMillis();
            log.info("[总耗时] 视频上传到结果就绪: {}ms ({}s)", totalTime, totalTime / 1000);
            log.info("视频识别完成: taskId={}, platesJson已存储", task.getTaskId());

        } catch (Exception e) {
            log.error("视频识别失败: taskId={}", task.getTaskId(), e);
            task.setStatus("FAILED");
            task.setErrorMsg(e.getMessage());
            task.setCompleteTime(LocalDateTime.now());
            taskMapper.updateById(task);
            Map<String, Object> errResult = new HashMap<>();
            errResult.put("status", "FAILED");
            errResult.put("error", e.getMessage());
            wsHandler.pushResult(task.getTaskId(), errResult);
        }
    }

    // ==================== 查询接口 ====================

    /**
     * 根据 taskId 查询任务状态和结果
     */
    public RecognitionResultVO getTaskResult(String taskId) {
        RecognitionTask task = taskMapper.selectOne(
                new LambdaQueryWrapper<RecognitionTask>().eq(RecognitionTask::getTaskId, taskId));
        if (task == null) {
            return null;
        }
        return toVO(task);
    }

    /**
     * 查询历史记录（最新10条）
     */
    public List<RecognitionResultVO> getHistory() {
        List<RecognitionTask> tasks = taskMapper.selectList(
                new LambdaQueryWrapper<RecognitionTask>()
                        .orderByDesc(RecognitionTask::getCreateTime)
                        .last("LIMIT 10"));
        if (tasks == null || tasks.isEmpty()) {
            return Collections.emptyList();
        }
        return tasks.stream().map(this::toVO).collect(Collectors.toList());
    }

    // ==================== 内部方法 ====================

    private void pushResult(RecognitionTask task, JsonNode data) {
        RecognitionResultVO vo = toVO(task);
        wsHandler.pushResult(task.getTaskId(), vo);
    }

    private RecognitionResultVO toVO(RecognitionTask task) {
        RecognitionResultVO vo = RecognitionResultVO.builder()
                .taskId(task.getTaskId())
                .fileName(task.getFileName())
                .fileType(task.getFileType())
                .status(task.getStatus())
                .plates(task.getPlatesJson())
                .errorMsg(task.getErrorMsg())
                .createTime(formatTime(task.getCreateTime()))
                .completeTime(formatTime(task.getCompleteTime()))
                .build();
        // 从存储的 JSON 中提取图片 URL（历史记录也需要显示标注图）
        try {
            if (task.getPlatesJson() != null) {
                com.fasterxml.jackson.databind.ObjectMapper mapper = new com.fasterxml.jackson.databind.ObjectMapper();
                JsonNode json = mapper.readTree(task.getPlatesJson());
                if (json.has("image_url") && !json.get("image_url").isNull()) {
                    vo.setImageUrl(proxyUrl(json.get("image_url").asText()));
                }
                // Py 直传 MinIO，URL 直接用
                if (json.has("annotated_url") && !json.get("annotated_url").isNull())
                    vo.setAnnotatedImageUrl(json.get("annotated_url").asText());
                if (json.has("annotated_video_url") && !json.get("annotated_video_url").isNull())
                    vo.setAnnotatedVideoUrl(json.get("annotated_video_url").asText());
                if (json.has("video_url") && !json.get("video_url").isNull()) {
                    vo.setVideoUrl(proxyUrl(json.get("video_url").asText()));
                }
                if (json.has("fps") && !json.get("fps").isNull()) {
                    vo.setFps(json.get("fps").asDouble());
                }
            }
        } catch (Exception e) {
            // 旧数据可能格式不同，忽略
        }
        return vo;
    }

    private String formatTime(LocalDateTime time) {
        if (time == null) return null;
        return time.format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"));
    }

    /**
     * 将 Python Flask 路径 (/uploads/xxx.jpg) 转为后端代理 URL (/api/images/xxx.jpg)
     * 前端通过 Java 代理访问 Python 的文件，避免直接暴露 Python 端口
     */
    private String proxyUrl(String pythonPath) {
        if (pythonPath == null) return null;
        int idx = pythonPath.indexOf("/uploads/");
        if (idx >= 0) return "/api/images" + pythonPath.substring(idx + 8);
        String filename = pythonPath.substring(pythonPath.lastIndexOf('/') + 1);
        return "/api/images/" + filename;
    }

    private String getFileType(String fileName) {
        if (fileName == null) return "image";
        String lower = fileName.toLowerCase();
        if (lower.endsWith(".mp4") || lower.endsWith(".avi") ||
            lower.endsWith(".mov") || lower.endsWith(".mkv") ||
            lower.endsWith(".flv") || lower.endsWith(".wmv")) {
            return "video";
        }
        return "image";
    }

    private String saveFile(MultipartFile file, String taskId, String originalName) {
        // 只存 MinIO，不存本地
        String ext = "";
        if (originalName != null && originalName.contains(".")) {
            ext = originalName.substring(originalName.lastIndexOf("."));
        }
        String minioObj = "uploads/" + taskId + ext;
        try {
            minioService.upload(file, minioObj);
            return minioObj;
        } catch (Exception e) {
            throw new RuntimeException("文件保存失败", e);
        }
    }
}
