import axios from 'axios'

/** 统一响应：{code, message, data}，code 非 0 视为失败 */
const http = axios.create({
  baseURL: '/api',
  timeout: 20000,
})

http.interceptors.response.use(
  (res) => {
    const body = res.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code !== 0) {
        return Promise.reject(new Error(body.message || '请求失败'))
      }
      return body.data
    }
    return body
  },
  (err) => {
    const msg =
      err?.response?.data?.message || err?.message || '网络请求失败'
    return Promise.reject(new Error(msg))
  },
)

export default http
