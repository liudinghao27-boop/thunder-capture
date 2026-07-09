# 住宅 IP 代理池配置与使用指南

## 一、支持的代理服务商

代理池 `docs/qa/proxy_pool.py` 已内置适配以下住宅代理服务商：

1. **Bright Data**（推荐）
2. **Oxylabs**
3. **静态代理**（本地 Clash/V2Ray/其他代理出口）

## 二、Bright Data 配置示例

1. 登录 [Bright Data 控制台](https://brightdata.com/)
2. 创建 Residential Zone，记录：
   - Customer ID
   - Zone Name
   - Zone Password
3. 编辑 `docs/qa/proxy_pool_config.json`：

```json
{
  "providers": [
    {
      "name": "brightdata",
      "enabled": true,
      "type": "brightdata",
      "customer_id": "your_customer_id",
      "zone": "residential",
      "zone_password": "your_zone_password",
      "country": "cn",
      "session_id": "thunder_session_1",
      "rotation_seconds": 300
    }
  ]
}
```

生成的代理 URL 格式：
```
http://brd-customer-<customer_id>-zone-residential-country-cn-session-thunder_session_1:<zone_password>@brd.superproxy.io:22225
```

## 三、Oxylabs 配置示例

```json
{
  "providers": [
    {
      "name": "oxylabs",
      "enabled": true,
      "type": "oxylabs",
      "username": "your_username",
      "password": "your_password",
      "country": "cn",
      "session_id": "thunder_session_1",
      "rotation_seconds": 300
    }
  ]
}
```

## 四、静态代理配置示例（本地 Clash/V2Ray）

```json
{
  "providers": [
    {
      "name": "local_clash",
      "enabled": true,
      "type": "static",
      "proxy_url": "http://127.0.0.1:7890",
      "rotation_seconds": 0
    }
  ]
}
```

## 五、启动代理池

```bash
python docs/qa/proxy_pool.py
```

服务启动后监听：`http://127.0.0.1:3128`

## 六、配置 MediaCrawler 使用代理池

设置环境变量：

```bash
# PowerShell
$env:THUNDER_MEDIACRAWLER_PROXY_URL = "http://127.0.0.1:3128"

# Bash
export THUNDER_MEDIACRAWLER_PROXY_URL="http://127.0.0.1:3128"
```

`adapters/mediacrawler/runner.py` 中的 `configure_mediacrawler` 会自动注入：
- `ENABLE_IP_PROXY = True`
- `STATIC_PROXY_URL = http://127.0.0.1:3128`

## 七、请求频率控制

在 `proxy_pool_config.json` 中配置：

```json
"request_interval": {
  "min_seconds": 3,
  "max_seconds": 8
}
```

每次转发请求前会随机等待 3-8 秒，降低风控概率。

## 八、健康检查与监控

代理池会定期执行：
- 从服务商拉取新代理
- 对 `https://www.douyin.com/passport/web/login` 执行健康检查
- 连续失败 3 次的代理会被自动剔除

日志输出示例：
```
2026-07-05 18:00:00 INFO: Added proxy from brightdata
2026-07-05 18:01:00 INFO: Pool: 1 proxies, health 1/1
```

## 九、运行采集测试

1. 启动 Chrome CDP：
   ```bash
   python docs/qa/launch_chrome_cdp.py
   ```

2. 启动代理池：
   ```bash
   python docs/qa/proxy_pool.py
   ```

3. 设置代理环境变量：
   ```bash
   $env:THUNDER_MEDIACRAWLER_PROXY_URL = "http://127.0.0.1:3128"
   ```

4. 运行端到端测试：
   ```bash
   python docs/qa/e2e_verify.py
   ```

5. 运行稳定性测试：
   ```bash
   python docs/qa/stability_test.py --count 10
   ```

## 十、注意事项

1. **必须配置真实住宅代理**：当前框架没有内置免费代理，免费代理通常已被抖音风控。
2. **代理地理位置**：建议与目标业务场景匹配，如国内抖音使用 `country: cn`。
3. **请求频率**：即使使用住宅代理，也建议保持合理间隔，避免被平台限制。
4. **Cookie 有效性**：定期更新 `data/douyin_cookies.json`，避免账号过期。

## 十一、当前环境状态

由于本环境没有真实住宅代理 API Key，代理池启动后没有可用代理。

要继续推进上线，请完成：
1. 购买并配置真实住宅代理
2. 重新运行端到端采集测试
3. 重新运行稳定性测试，确认成功率 ≥ 95%

