package com.lpr.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.lpr.model.RecognitionTask;
import org.apache.ibatis.annotations.Mapper;

/**
 * MyBatis-Plus Mapper 接口
 * 继承 BaseMapper 后自动拥有 CRUD 方法，无需写 XML
 */
@Mapper
public interface RecognitionTaskMapper extends BaseMapper<RecognitionTask> {
}
