package com.lpr.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestTemplate;

/**
 * RestTemplate 配置 —— Java 调用 Python Flask 的 HTTP 客户端
 *
 * RestTemplate 是 Spring 提供的同步 HTTP 客户端。
 * 企业里也常用 WebClient（Spring 5+，响应式，性能更好），
 * 这里用 RestTemplate 因为它简单、适合学习。
 *
 * 面试点：RestTemplate 默认使用 JDK 的 HttpURLConnection，
 * 生产环境通常换 Apache HttpClient 或 OkHttp 作为底层实现，
 * 以获得连接池、超时控制等能力。
 */
@Configuration
public class RestTemplateConfig {

    @Bean
    public RestTemplate restTemplate() {
        return new RestTemplate();
    }
}
