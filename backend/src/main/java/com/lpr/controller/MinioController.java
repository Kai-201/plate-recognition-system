package com.lpr.controller;

import com.lpr.service.MinioService;
import org.springframework.web.bind.annotation.*;

import javax.annotation.Resource;
import java.util.*;

/**
 * MinIO 直传接口 — 前端直接上传到 MinIO，不经过 Java 中转
 */
@RestController
@RequestMapping("/api/minio")
public class MinioController {

    @Resource
    private MinioService minioService;

    /**
     * 获取预签名上传 URL
     * 前端拿这个 URL 直接 PUT 文件到 MinIO，不限大小不限速
     */
    @GetMapping("/upload-url")
    public Map<String, Object> getUploadUrl(@RequestParam String fileName) {
        String ext = "";
        if (fileName.contains(".")) ext = fileName.substring(fileName.lastIndexOf("."));
        String taskId = UUID.randomUUID().toString().replace("-", "");
        String objectName = "uploads/" + taskId + ext;

        String presignedUrl = minioService.getPresignedUploadUrl(objectName);

        Map<String, Object> result = new HashMap<>();
        result.put("uploadUrl", presignedUrl);
        result.put("objectName", objectName);
        result.put("taskId", taskId);
        return result;
    }
}
