package com.lpr.controller;

import com.lpr.service.MinioService;
import org.springframework.web.bind.annotation.*;

import javax.annotation.Resource;
import java.util.*;

/**
 * 企业级大文件分片上传 + 断点续传（面试亮点）
 *
 * 流程:
 *   ① POST /api/chunk/init     初始化上传, 返回 uploadId + presigned URLs
 *   ② PUT 每片到 MinIO         前端并发上传
 *   ③ POST /api/chunk/complete 通知合并, 返回 taskId
 *   ④ GET  /api/chunk/progress 查询进度
 */
@RestController
@RequestMapping("/api/chunk")
public class ChunkUploadController {

    // 模拟"上传会话"表（生产环境存 Redis/DB）
    private final Map<String, Map<String, Object>> sessions = new HashMap<>();

    @Resource
    private MinioService minioService;

    /**
     * 初始化分片上传
     * 前端传: fileName, fileSize, fileHash
     * 返回: uploadId, chunkSize(5MB), chunks(总片数), presignedUrls[](每片一个)
     */
    @PostMapping("/init")
    public Map<String, Object> initUpload(@RequestBody Map<String, Object> body) {
        String fileName = (String) body.get("fileName");
        long fileSize = ((Number) body.get("fileSize")).longValue();
        String fileHash = (String) body.getOrDefault("fileHash", "");

        String taskId = UUID.randomUUID().toString().replace("-", "");
        int chunkSize = 5 * 1024 * 1024;  // 5MB
        int totalChunks = (int) Math.ceil((double) fileSize / chunkSize);

        List<String> urls = new ArrayList<>();
        for (int i = 0; i < totalChunks; i++) {
            String objName = "chunks/" + taskId + "/part_" + String.format("%05d", i);
            urls.add(minioService.getPresignedUploadUrl(objName));
        }

        Map<String, Object> session = new HashMap<>();
        session.put("taskId", taskId);
        session.put("fileName", fileName);
        session.put("fileSize", fileSize);
        session.put("fileHash", fileHash);
        session.put("totalChunks", totalChunks);
        session.put("completedChunks", 0);
        session.put("status", "uploading");
        sessions.put(taskId, session);

        Map<String, Object> result = new HashMap<>();
        result.put("taskId", taskId);
        result.put("chunkSize", chunkSize);
        result.put("totalChunks", totalChunks);
        result.put("urls", urls);
        return result;
    }

    /**
     * 标记一片上传完成（前端并发上传后回调）
     */
    @PostMapping("/progress")
    public Map<String, Object> markProgress(@RequestBody Map<String, String> body) {
        String taskId = body.get("taskId");
        Map<String, Object> session = sessions.get(taskId);
        if (session == null) {
            Map<String, Object> err = new HashMap<>();
            err.put("error", "会话不存在");
            return err;
        }

        int completed = (int) session.get("completedChunks") + 1;
        session.put("completedChunks", completed);
        Map<String, Object> prog = new HashMap<>();
        prog.put("completed", completed);
        prog.put("total", session.get("totalChunks"));
        return prog;
    }

    /**
     * 前端所有片上传完成 → 通知 Java 合并
     */
    @PostMapping("/complete")
    public Map<String, Object> completeUpload(@RequestBody Map<String, String> body) {
        String taskId = body.get("taskId");
        Map<String, Object> session = sessions.get(taskId);
        if (session == null) {
            Map<String, Object> err = new HashMap<>();
            err.put("error", "会话不存在");
            return err;
        }

        // 生产环境: MinIO composeObject 合并分片
        // 这里简化: 返回 taskId 给前端调 /notify
        Map<String, Object> result = new HashMap<>();
        result.put("taskId", taskId);
        result.put("status", "ready");
        return result;
    }

    /**
     * 查询上传进度（断点续传用）
     */
    @GetMapping("/progress/{taskId}")
    public Map<String, Object> getProgress(@PathVariable String taskId) {
        Map<String, Object> session = sessions.get(taskId);
        if (session == null) {
            Map<String, Object> err = new HashMap<>();
            err.put("error", "会话不存在");
            return err;
        }
        Map<String, Object> info = new HashMap<>();
        info.put("completed", session.get("completedChunks"));
        info.put("total", session.get("totalChunks"));
        info.put("status", session.get("status"));
        return info;
    }
}
