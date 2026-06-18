package com.lpr.model;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 返回给前端的识别结果 VO
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class RecognitionResultVO {

    private String taskId;
    private String fileName;
    private String fileType;
    private String status;
    private Object plates;
    private String errorMsg;
    private String createTime;
    private String completeTime;
    private String imageUrl;           // 原图 URL
    private String annotatedImageUrl;  // 标注图 URL（图片）
    private String annotatedVideoUrl;  // 标注视频 URL
    private String videoUrl;           // 原视频 URL（前端 Canvas 实时画框用）
    private Double fps;                // 视频帧率
}
