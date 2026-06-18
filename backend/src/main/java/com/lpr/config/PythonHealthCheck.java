package com.lpr.config;

import com.lpr.service.PythonInferenceClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.stereotype.Component;

import javax.annotation.Resource;

/**
 * Python 推理服务健康检查
 *
 * 把 Python 的存活状态暴露到 Java 的 /actuator/health 里
 * Spring Boot Admin 或 Kubernetes 就能统一监控
 */
@Component
public class PythonHealthCheck implements HealthIndicator {

    private static final Logger log = LoggerFactory.getLogger(PythonHealthCheck.class);

    @Resource
    private PythonInferenceClient pythonClient;

    @Override
    public Health health() {
        try {
            if (pythonClient.healthCheck()) {
                return Health.up().withDetail("python", "running").build();
            }
        } catch (Exception e) {
            log.warn("Python 服务健康检查失败: {}", e.getMessage());
        }
        return Health.down().withDetail("python", "unreachable").build();
    }
}
