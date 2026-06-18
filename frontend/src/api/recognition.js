import axios from 'axios'

const API_BASE = '/api/recognition'

/**
 * 获取 MinIO 预签名上传 URL
 */
export function getUploadUrl(fileName) {
  return axios.get('/api/minio/upload-url', { params: { fileName } }).then(res => res.data)
}

/**
 * 直接上传文件到 MinIO（前端直传，不走 Java）
 * 不发额外 header，只发纯文件体，避免签名校验失败
 */
export function uploadToMinio(uploadUrl, file) {
  return fetch(uploadUrl, {
    method: 'PUT',
    body: file
  })
}

/**
 * 通知 Java 文件已上传到 MinIO，开始推理
 */
export function notifyUpload(taskId, objectName, fileType) {
  return axios.post(`${API_BASE}/notify`, { taskId, objectName, fileType }).then(res => res.data)
}

/**
 * 计算文件 SHA-256（秒传用）
 */
export function computeFileHash(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = async (e) => {
      const buffer = e.target.result
      const hashBuffer = await crypto.subtle.digest('SHA-256', buffer)
      const hashArray = Array.from(new Uint8Array(hashBuffer))
      resolve(hashArray.map(b => b.toString(16).padStart(2, '0')).join(''))
    }
    reader.onerror = reject
    reader.readAsArrayBuffer(file)
  })
}

/**
 * 重新识别
 */
export function retryTask(taskId) {
  return axios.post(`${API_BASE}/retry/${taskId}`).then(res => res.data)
}

/**
 * 秒传检查
 */
export function checkFileHash(hash) {
  return axios.get(`${API_BASE}/check`, { params: { hash } }).then(res => res.data)
}


/**
 * 上传文件，创建识别任务
 */
export function uploadFile(file, ocr = 'lprnet') {
  const formData = new FormData()
  formData.append('file', file)
  return axios.post(`${API_BASE}/upload?ocr=${ocr}`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  }).then(res => res.data)
}

/**
 * 查询任务结果（用于刷新/轮询）
 * @param {string} taskId
 */
export function getTaskResult(taskId) {
  return axios.get(`${API_BASE}/task/${taskId}`).then(res => res.data)
}

/**
 * 查询历史记录
 */
export function getHistory() {
  return axios.get(`${API_BASE}/history`).then(res => res.data)
}

/**
 * 建立 WebSocket 连接
 * @param {string} taskId
 * @param {function} onMessage 收到消息的回调
 * @returns {WebSocket}
 */
export function connectWebSocket(taskId, onMessage) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  const url = `${protocol}//${host}/ws/recognition/${taskId}`
  const ws = new WebSocket(url)
  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      onMessage(data)
    } catch (e) {
      console.error('WebSocket 消息解析失败', e)
    }
  }
  ws.onerror = (err) => console.error('WebSocket 错误:', err)
  return ws
}
