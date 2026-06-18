package com.lpr.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.FileSystemResource;
import org.springframework.http.*;
import org.springframework.stereotype.Service;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestTemplate;

import javax.annotation.Resource;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.util.function.Consumer;

/**
 * Python 推理服务 HTTP 客户端
 *
 * 职责：用 RestTemplate 调 Flask 的 /inference/image 和 /inference/video 接口
 *
 * 数据流：
 * Java(本类) → HTTP POST multipart/form-data → Python Flask → 推理 → 返回 JSON
 */
@Service
public class PythonInferenceClient {

    private static final Logger log = LoggerFactory.getLogger(PythonInferenceClient.class);
    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Resource
    private RestTemplate restTemplate;

    @Value("${lpr.python.url}")
    private String pythonUrl;

    /**
     * 调用 Python 进行图片推理
     *
     * @param imagePath 本地图片路径
     * @return Flask 返回的 JSON 字符串
     */
    public JsonNode inferenceImage(String imagePath) {
        return inferenceImage(imagePath, "lprnet");
    }

    public JsonNode inferenceImage(String imagePath, String ocr) {
        String url = pythonUrl + "/inference/image?ocr=" + ocr;

        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        body.add("file", new FileSystemResource(imagePath));

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.MULTIPART_FORM_DATA);
        HttpEntity<MultiValueMap<String, Object>> requestEntity = new HttpEntity<>(body, headers);

        log.info("调用 Python 图片推理: {}", imagePath);
        ResponseEntity<String> response = restTemplate.postForEntity(url, requestEntity, String.class);

        try {
            return MAPPER.readTree(response.getBody());
        } catch (Exception e) {
            log.error("解析 Python 返回 JSON 失败", e);
            throw new RuntimeException("Python 服务返回异常", e);
        }
    }

    /**
     * 调用 Python 进行视频推理
     *
     * @param videoPath      本地视频路径
     * @param frameInterval  抽帧间隔
     * @return Flask 返回的 JSON 字符串
     */
    public JsonNode inferenceVideo(String videoPath, int frameInterval) {
        return inferenceVideo(videoPath, frameInterval, "lprnet");
    }

    public JsonNode inferenceVideo(String videoPath, int frameInterval, String ocr) {
        String url = pythonUrl + "/inference/video?ocr=" + ocr;
  

        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        body.add("file", new FileSystemResource(videoPath));
        body.add("frame_interval", String.valueOf(frameInterval));

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.MULTIPART_FORM_DATA);
        HttpEntity<MultiValueMap<String, Object>> requestEntity = new HttpEntity<>(body, headers);

        log.info("调用 Python 视频推理: {} (抽帧间隔={})", videoPath, frameInterval);
        ResponseEntity<String> response = restTemplate.postForEntity(url, requestEntity, String.class);

        try {
            return MAPPER.readTree(response.getBody());
        } catch (Exception e) {
            log.error("解析 Python 返回 JSON 失败", e);
            throw new RuntimeException("Python 服务返回异常", e);
        }
    }

    /**
     * 视频流式推理：逐帧推结果，通过 callback 回调每一帧
     */
    public void inferenceVideoStream(String videoPath, Consumer<JsonNode> onFrame) {
        String url = pythonUrl + "/inference/video/stream";

        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        body.add("file", new FileSystemResource(videoPath));

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.MULTIPART_FORM_DATA);

        log.info("调用 Python 视频流式推理: {}", videoPath);
        restTemplate.execute(url, HttpMethod.POST,
                request -> {
                    request.getHeaders().setContentType(MediaType.MULTIPART_FORM_DATA);
                    // 写 multipart body
                    org.springframework.http.converter.FormHttpMessageConverter converter =
                            new org.springframework.http.converter.FormHttpMessageConverter();
                    converter.write(body, MediaType.MULTIPART_FORM_DATA, request);
                },
                response -> {
                    try (BufferedReader reader = new BufferedReader(
                            new InputStreamReader(response.getBody()))) {
                        String line;
                        while ((line = reader.readLine()) != null) {
                            if (line.startsWith("data: ")) {
                                String json = line.substring(6);
                                onFrame.accept(MAPPER.readTree(json));
                            }
                        }
                    }
                    return null;
                });
    }

    /**
     * 健康检查
     */
    public boolean healthCheck() {
        try {
            String url = pythonUrl + "/health";
            ResponseEntity<String> response = restTemplate.getForEntity(url, String.class);
            return response.getStatusCode().is2xxSuccessful();
        } catch (Exception e) {
            log.error("Python 服务健康检查失败", e);
            return false;
        }
    }
}
