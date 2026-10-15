# 和风天气 Home Assistant 集成（weather/v1 适配分支）

基于 [cheny95/qweather](https://github.com/cheny95/qweather) 修改，保留原许可证。
本分支面向 Home Assistant 2026.9，使用独立 API Host 和新的 `/weather/v1/` API；不是仅替换旧公共域名。

## 安装与配置

复制 `custom_components/qweather` 到 HA 的 `/config/custom_components/`，合并以下配置并重启 HA：

```yaml
weather:
  - platform: qweather
    name: 和风天气
    api_host: !secret qweather_api_host
    api_key: !secret qweather_api_key
    location: "112.94,28.23"  # 经度,纬度；内部调用 v1 时按纬度/经度排序
    default: 7              # 1–10 天
    hours: 24               # 1–240 小时
    extras: [air, alerts, minutely] # 可选，默认不查询附加产品
    scan_interval: 1800     # 秒，默认 30 分钟
```

在服务器的 `secrets.yaml` 中设置个人 API Host（控制台→设置）和 API Key。Host 只填域名，不加 `https://` 或路径。不要上传 secrets.yaml。
位置会四舍五入到两位小数，符合 v1 精度要求。不启用附加产品时每轮最多三个请求，默认每天约 144 次；全部启用时每轮最多六个，默认每天约 288 次。收费和额度以和风控制台为准。

新版接口：

- `/weather/v1/current/{latitude}/{longitude}`
- `/weather/v1/daily/{latitude}/{longitude}?days=7`
- `/weather/v1/hourly/{latitude}/{longitude}?hours=24`

通过 `X-QW-Api-Key` 请求头鉴权；HTTPS 校验证书，禁止重定向转发凭据。每个请求最长 20 秒，核心天气一轮最长 60 秒；三个附加产品另各有 20 秒超时。
当前实现支持 API Key，不生成 JWT。新版 API Key 是否可用需要个人 Host、凭据及服务权限实测。

## 使用预报

使用 HA 原生天气卡片及 `weather.get_forecasts`，支持 `daily` 和 `hourly`。不再依赖已移除的 `forecast` 状态属性。

```yaml
action: weather.get_forecasts
target:
  entity_id: weather.he_feng_tian_qi  # 以实际实体 ID 为准
data:
  type: daily
```

温度 °C、风速 m/s、能见度 m、气压 hPa、降水 mm。HA 根据用户单位系统转换显示。
湿度、云量和小时降雨概率从 0–1 转为百分比；日预报使用全天高低温，降水量为白天与夜间之和，不拼造全天降雨概率。日预报天气、风、湿度和云量采用白天数据。保留带时区的完整预报时间。
数据失败时实体标记不可用并清除预报，恢复后正常发布。返回缺失测量值时不填零。

## 功能边界与迁移

0.2.0 增加可选空气质量、天气预警和分钟降雨，作为天气实体属性提供，便于 HA 模板使用。生活指数尚未迁移。

- `air` 使用 `/airquality/v1/current/纬度/经度`，提供 `pm25`、`air_available` 及来源信息。
- `alerts` 使用 `/weatheralert/v1/current/纬度/经度`，提供 `alerts`、`alerts_available` 及来源信息。每条包含标题、正文（含防御指南）、颜色和屏幕兼容等级代码；过滤取消、被替代及已过期预警。请求失败时 `alerts` 为 `null`，成功且无有效预警时才为 `[]`。
- `minutely` 使用官方当前仍指定的 `/v7/minutely/5m` 路径及个人 API Host，提供 `minutely_summary`、`minutely_available` 及来源信息。此产品的官方路径仍为 v7，不应猜测一个 v1 替代路径。

各附加产品独立失败，清除本轮对应值，不影响核心天气；未启用的产品不请求。`precipitation_1h` 为过去一小时实时降水，`precipitation_next_24h` 为未来连续 24 小时预报降水总和，仅完整取得 24 小时数据时提供。

独立安装不会自动迁移原有集成。先备份，再调整依赖实体和屏幕模板，验证新数据有效后删除旧集成。模板应同时检查天气实体可用性和对应产品的 `*_available`，避免把失败误认为无预警、零污染或零降雨。
旧版的天气状态名称已修正为 HA 支持的状态；修正了雪天气误映射为雨和湿度误作降雨概率的问题。

## 验证

在装有 Home Assistant 的 Python 环境，从仓库根目录运行：

```sh
python -m unittest discover -s tests -v
```

`tests/fixtures` 为 2026-10-15 长沙近似坐标的真实 v1 响应样本，不含凭据。测试覆盖单位、经纬度次序、时区、HTTP 错误、缺失数据与失败后恢复。

2026-10-15（Asia/Shanghai）验证：Home Assistant 2026.9.3 中 16 项测试全部通过；隔离 HA 使用真实服务加载实体成功，六个产品均可用，`weather.get_forecasts` 返回 7 天与 24 小时预报。HA 将原生 m/s 和 m 按公制显示设置转换为 km/h 和 km。21:08 正式 HA 已确认天气、PM2.5、预警、未来 24 小时降水和七日预报模板有效。

`tests/smoke_ha.py` 使用响应样本验证完整 HA 加载、附加产品和预报服务；加 `--live` 时从标准输入接收仅含 `api_host`、`api_key` 的 JSON，供私下验证。测试创建临时独立 HA 配置目录，结束后删除，不读取正式配置。

参考：[天气 API](https://dev.qweather.com/docs/api/weather/)、[身份认证](https://dev.qweather.com/docs/configuration/authentication/)、[API Host](https://dev.qweather.com/docs/configuration/api-host/)。
