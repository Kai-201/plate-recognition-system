package com.lpr.service;

import io.minio.*;
import io.minio.http.Method;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import javax.annotation.PostConstruct;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.TimeUnit;

/**
 * MinIO 对象存储服务 — 统一管理所有文件的上传和访问
 */
@Service
public class MinioService {

    @Value("${minio.endpoint}")
    private String endpoint;

    @Value("${minio.access-key}")
    private String accessKey;

    @Value("${minio.secret-key}")
    private String secretKey;

    @Value("${minio.bucket}")
    private String bucket;

    private MinioClient client;

    @PostConstruct
    public void init() {
        client = MinioClient.builder()
                .endpoint(endpoint)
                .credentials(accessKey, secretKey)
                .region("us-east-1")
                .build();
        try {
            if (!client.bucketExists(BucketExistsArgs.builder().bucket(bucket).build())) {
                client.makeBucket(MakeBucketArgs.builder().bucket(bucket).build());
            }
        } catch (Exception e) {
            throw new RuntimeException("MinIO 初始化失败", e);
        }
    }

    /** 上传 MultipartFile 到 MinIO */
    public String upload(MultipartFile file, String objectName) throws Exception {
        client.putObject(PutObjectArgs.builder()
                .bucket(bucket)
                .object(objectName)
                .stream(file.getInputStream(), file.getSize(), -1)
                .contentType(file.getContentType())
                .build());
        return objectName;
    }

    /** 上传本地文件到 MinIO */
    public String uploadFromFile(java.io.File file, String objectName) throws Exception {
        client.putObject(PutObjectArgs.builder()
                .bucket(bucket)
                .object(objectName)
                .stream(new java.io.FileInputStream(file), file.length(), -1)
                .contentType(objectName.endsWith(".mp4") ? "video/mp4" : "image/jpeg")
                .build());
        return objectName;
    }

    /** 生成预签名上传 URL（前端直传用，有效期 10 分钟） */
    public String getPresignedUploadUrl(String objectName) {
        try {
            return client.getPresignedObjectUrl(GetPresignedObjectUrlArgs.builder()
                    .bucket(bucket)
                    .object(objectName)
                    .method(io.minio.http.Method.PUT)
                    .expiry(10, TimeUnit.MINUTES)
                    .build());
        } catch (Exception e) {
            throw new RuntimeException("生成上传 URL 失败", e);
        }
    }

    /** 获取文件访问 URL（有效期 1 小时） */
    public String getUrl(String objectName) {
        try {
            return client.getPresignedObjectUrl(GetPresignedObjectUrlArgs.builder()
                    .bucket(bucket)
                    .object(objectName)
                    .method(Method.GET)
                    .expiry(1, TimeUnit.HOURS)
                    .build());
        } catch (Exception e) {
            return null;
        }
    }

    /** 下载文件到流 */
    public InputStream download(String objectName) throws Exception {
        return client.getObject(GetObjectArgs.builder()
                .bucket(bucket)
                .object(objectName)
                .build());
    }

    /** 写空对象（幂等标记用） */
    public void putEmptyObject(String objectName) {
        try {
            client.putObject(PutObjectArgs.builder().bucket(bucket).object(objectName)
                .stream(new java.io.ByteArrayInputStream(new byte[0]), 0, -1).build());
        } catch (Exception e) { /* ignore */ }
    }

    public String getBucket() { return bucket; }
}
