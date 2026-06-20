package com.lpr;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * 车牌识别系统 - SpringBoot 启动类
 */
@SpringBootApplication
@EnableAsync
@EnableScheduling    // 开启异步任务支持
public class LprApplication {
    public static void main(String[] args) {
        SpringApplication.run(LprApplication.class, args);
        System.out.println("========================================");
        System.out.println("  车牌识别后端服务启动成功！");
        System.out.println("  端口: 8080");
        System.out.println("========================================");
    }
}
