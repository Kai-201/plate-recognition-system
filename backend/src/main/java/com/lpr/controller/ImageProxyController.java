package com.lpr.controller;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestTemplate;

import javax.annotation.Resource;
import javax.servlet.http.HttpServletRequest;

/**
 * 图片代理 —— 前端通过 8080 访问 Python Flask 的标注图
 */
@RestController
public class ImageProxyController {

    private static final Logger log = LoggerFactory.getLogger(ImageProxyController.class);

    @Resource
    private RestTemplate restTemplate;

    @Value("${lpr.python.url}")
    private String pythonUrl;

    @GetMapping("/api/images/**")
    public ResponseEntity<byte[]> proxyImage(HttpServletRequest request) {
        String filename = request.getRequestURI().substring("/api/images/".length());
        try {
            String url = pythonUrl + "/uploads/" + filename;
            ResponseEntity<byte[]> response = restTemplate.getForEntity(url, byte[].class);
            if (response.getStatusCode().is2xxSuccessful() && response.getBody() != null) {
                HttpHeaders headers = new HttpHeaders();
                String lower = filename.toLowerCase();
                if (lower.endsWith(".png")) {
                    headers.setContentType(MediaType.IMAGE_PNG);
                } else if (lower.endsWith(".mp4")) {
                    headers.setContentType(MediaType.valueOf("video/mp4"));
                } else if (lower.endsWith(".webm")) {
                    headers.setContentType(MediaType.valueOf("video/webm"));
                } else {
                    headers.setContentType(MediaType.IMAGE_JPEG);
                }
                headers.setCacheControl("max-age=3600");
                return new ResponseEntity<>(response.getBody(), headers, HttpStatus.OK);
            }
        } catch (Exception e) {
            log.error("代理图片失败: {}", filename, e);
        }
        return ResponseEntity.notFound().build();
    }
}
