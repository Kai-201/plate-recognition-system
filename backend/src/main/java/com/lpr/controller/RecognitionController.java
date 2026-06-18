package com.lpr.controller;

import com.lpr.model.RecognitionResultVO;
import com.lpr.service.RecognitionService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import javax.annotation.Resource;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 车牌识别 REST API
 *
 * 接口设计：
 * - POST /api/recognition/upload     上传文件，立即返回 taskId
 * - GET  /api/recognition/task/{id}  根据 taskId 查询结果
 * - GET  /api/recognition/history    查询历史记录
 *
 * RESTful 设计原则：
 * - 资源用名词（/recognition，不是 /doRecognition）
 * - 操作对应 HTTP 方法（POST 创建，GET 查询）
 * - 统一返回格式（code + data + message）
 */
@RestController
@RequestMapping("/api/recognition")
@CrossOrigin(origins = "*")   // 允许前端跨域（生产环境应限制域名）
public class RecognitionController {

    private static final Logger log = LoggerFactory.getLogger(RecognitionController.class);

    @Resource
    private RecognitionService recognitionService;

    /**
     * 秒传检查：根据文件 MD5 查询是否已有识别结果
     */
    @GetMapping("/check")
    public ResponseEntity<Map<String, Object>> check(@RequestParam String hash) {
        RecognitionResultVO existing = recognitionService.checkByHash(hash);
        if (existing != null) {
            return ResponseEntity.ok(success("已存在（秒传）", existing));
        }
        Map<String, Object> notFound = new HashMap<>();
        notFound.put("code", 404);
        notFound.put("message", "未找到");
        notFound.put("data", null);
        return ResponseEntity.ok(notFound);
    }

    /**
     * MinIO 直传完成后通知 Java 开始推理
     */
    @PostMapping("/notify")
    public ResponseEntity<Map<String, Object>> notify(@RequestBody Map<String, String> body) {
        String taskId = body.get("taskId");
        String objectName = body.get("objectName");
        String fileType = body.get("fileType");
        log.info("MinIO 直传完成: taskId={}, object={}", taskId, objectName);
        try {
            if ("image".equals(fileType)) {
                RecognitionResultVO result = recognitionService.processFromMinio(taskId, objectName);
                return ResponseEntity.ok(success("识别完成", result));
            } else {
                String tid = recognitionService.submitFromMinio(taskId, objectName);
                Map<String, Object> data = new HashMap<>();
                data.put("taskId", tid);
                return ResponseEntity.ok(success("任务已创建", data));
            }
        } catch (Exception e) {
            return ResponseEntity.internalServerError().body(error(e.getMessage()));
        }
    }

    /**
     * 上传文件并识别
     *
     * 图片：同步处理，HTTP 响应直接返回结果（推理通常 < 1 秒）
     * 视频：异步处理，返回 taskId，前端通过 WebSocket 或轮询获取结果
     */
    @PostMapping("/upload")
    public ResponseEntity<Map<String, Object>> upload(@RequestParam("file") MultipartFile file,
                                                       @RequestParam(value = "ocr", defaultValue = "lprnet") String ocr) {
        if (file.isEmpty()) {
            return ResponseEntity.badRequest().body(error("文件为空"));
        }

        long t0 = System.currentTimeMillis();
        log.info("收到上传请求: fileName={}, size={}", file.getOriginalFilename(), file.getSize());

        try {
            String fileType = recognitionService.getFileTypeText(file.getOriginalFilename());

            if ("image".equals(fileType)) {
                RecognitionResultVO result = recognitionService.processImageSync(file, ocr);
                log.info("[总耗时] 图片上传到返回结果: {}ms  OCR={}", System.currentTimeMillis() - t0, ocr);
                return ResponseEntity.ok(success("识别完成", result));
            } else {
                // 视频：异步处理，返回 taskId
                String taskId = recognitionService.submitTask(file, ocr);
                Map<String, Object> data = new HashMap<>();
                data.put("taskId", taskId);
                data.put("fileName", file.getOriginalFilename());
                return ResponseEntity.ok(success("任务已创建，请通过 WebSocket 获取结果", data));
            }
        } catch (Exception e) {
            log.error("上传处理失败", e);
            return ResponseEntity.internalServerError().body(error(e.getMessage()));
        }
    }

    /**
     * 重新识别：用已有文件路径走最新推理逻辑
     */
    @PostMapping("/retry/{taskId}")
    public ResponseEntity<Map<String, Object>> retry(@PathVariable String taskId) {
        RecognitionResultVO result = recognitionService.retryTask(taskId);
        if (result == null) {
            return ResponseEntity.ok(error("任务不存在或文件已删除"));
        }
        return ResponseEntity.ok(success("重新识别完成", result));
    }

    /**
     * 查询任务结果
     */
    @GetMapping("/task/{taskId}")
    public ResponseEntity<Map<String, Object>> getTaskResult(@PathVariable String taskId) {
        RecognitionResultVO result = recognitionService.getTaskResult(taskId);
        if (result == null) {
            return ResponseEntity.ok(error("任务不存在"));
        }
        return ResponseEntity.ok(success("查询成功", result));
    }

    /**
     * 查询历史记录
     */
    @GetMapping("/history")
    public ResponseEntity<Map<String, Object>> getHistory() {
        List<RecognitionResultVO> history = recognitionService.getHistory();
        return ResponseEntity.ok(success("查询成功", history));
    }

    // ==================== 统一返回格式 ====================

    private Map<String, Object> success(String message, Object data) {
        Map<String, Object> result = new HashMap<>();
        result.put("code", 200);
        result.put("message", message);
        result.put("data", data);
        return result;
    }

    private Map<String, Object> error(String message) {
        Map<String, Object> result = new HashMap<>();
        result.put("code", 500);
        result.put("message", message);
        result.put("data", null);
        return result;
    }
}
