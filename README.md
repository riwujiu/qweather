# 和风天气 Home Assistant 集成（weather/v1 适配分支）

基于 [cheny95/qweather](https://github.com/cheny95/qweather) 修改，保留原许可证。
本分支面向 Home Assistant 2026.9，使用独立 API Host 和新的 `/weather/v1/` API；不是仅替换旧公共域名。

## 安装与配置

复制 `custom_components/qweather` 到 HA 的 `/config/custom_components/`，重启 HA。在“设置 → 设备与服务 → 添加集成”中搜索“和风天气 QWeather”，填写 API Host、API Key 和经纬度即可。

集成卡片的“配置”可修改名称、预报范围、更新间隔和附加功能；菜单中的“重新配置”还可修改 Host、Key 和位置。已有 Key 不会回填到表单，重新配置时留空会保留原 Key。配置通过后自动重新加载，不需要重启 HA。界面支持中文及英文。

位置修改后保留原天气实体 ID；同一位置不能重复添加。每个配置条目注册一个天气设备。更新间隔为秒，允许 300–86400 秒，默认 1800 秒。

### 从旧版 YAML 迁移

0.3.0 会在首次启动时把原有 weather YAML 配置导入为可在界面管理的条目，并沿用原天气实体登记及 ID。确认集成和实体正常后，从 configuration.yaml 移除对应的 qweather weather 配置；不再需要其 secrets.yaml 条目时也可删除。原有屏幕模板仍需保留。后续 YAML 不会覆盖已保存的界面设置。

仍支持用以下配置首次导入：

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

首次使用 YAML 导入时，在服务器的 `secrets.yaml` 中设置个人 API Host（控制台→设置）和 API Key。Host 只填域名，不加 `https://` 或路径。不要上传 secrets.yaml 或 HA 的 .storage 目录；界面设置及凭据由 HA 的配置条目保存。
位置会四舍五入到两位小数，符合 v1 精度要求。不启用附加产品时每轮最多三个请求，默认每天约 144 次；全部启用时每轮最多六个，默认每天约 288 次。收费和额度以和风控制台为准。

### 免费额度与更新频率

2026-10-15 核对[官方定价](https://dev.qweather.com/docs/finance/pricing/)：天气和基础服务价格组每个自然月前 50,000 次请求免费。天气、分钟预报、预警、空气质量等合计计算，不能按每个接口分别享受 50,000 次。

单个位置启用全部三项附加功能时，每轮最多六次请求。按最长 31 天估算：

| 更新间隔 | 每天请求 | 每月请求（31 天） |
| --- | ---: | ---: |
| 5 分钟 | 1,728 | 53,568 |
| 10 分钟 | 864 | 26,784 |
| 30 分钟（推荐／默认） | 288 | 8,928 |

建议单位置使用 30 分钟并保留全部功能，天气、预警和分钟降雨提示的更新延迟也相应最多约 30 分钟。HA 预报服务和屏幕模板读取已取得的内存数据，不会因查看页面或模板刷新而额外请求和风接口。启动、重新加载和重新配置连接验证会增加请求；同账号其他项目／应用以及多个位置需一起计入，以上是正常持续运行估算，不是账单或账户硬性限额。修改“更新间隔”只改变轮询频率，不会自动在和风控制台设置费用上限。

新版接口：

- `/weather/v1/current/{latitude}/{longitude}`
- `/weather/v1/daily/{latitude}/{longitude}?days=7`
- `/weather/v1/hourly/{latitude}/{longitude}?hours=24`

支持 API Key 和 JWT 两种认证，请求只发送所选认证方式的标头。HTTPS 校验证书，禁止重定向转发凭据。每个请求最长 20 秒，核心天气一轮最长 60 秒；三个附加产品另各有 20 秒超时。

### JWT（推荐，0.4.0 起）

在 HA 容器持久化的 `/config/` 目录下生成 Ed25519 私钥和公钥，仅将公钥上传至和风控制台“项目管理 → 添加凭据 → JSON Web Token”。私钥文件应只允许 HA 运行用户读取，不应上传仓库或粘贴到聊天。可以使用官方文档中的 OpenSSL 命令生成密钥。

在新增集成或“重新配置”中选择 JWT，并填写：

- 凭据 ID（`kid`）：创建 JWT 凭据后显示的 ID。
- 开发者 ID（`iss`）：控制台设置中 Q 开头的开发者 ID。
- 项目 ID（`sub`）：凭据所属的项目 ID。
- HA 服务器私钥文件路径：容器内绝对路径，默认 `/config/.qweather-jwt/ed25519-private.pem`；文件必须是未加密的 Ed25519 PEM 私钥。

JWT 模式 API Key 可留空。保存前验证真实天气接口；切换成功后移除条目中另一种认证方式的参数，保留天气实体 ID。私钥在后台线程读取，不回填界面，不存入配置条目；配置条目只存私钥路径和三个 ID。替换私钥文件后需重新加载集成，并确保公钥已在控制台更新。

集成自动使用 EdDSA 签名，Header 仅含 `alg`、`kid`，Payload 含 `iss`、`sub`、`iat`、`exp`。签发时间回退 30 秒，过期时间为当前时间后 15 分钟，提前 60 秒续期，通过 `Authorization: Bearer` 发送。实时、预报和附加产品共用此认证。服务器需保持正确时间。旧配置默认继续使用 API Key，首次 YAML 导入仍使用 API Key；JWT 在界面配置。

官方文档说明从 2027-01-01 起将限制 API Key 每日请求数量，建议迁移 JWT，具体额度以控制台为准。

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

`tests/smoke_ui.py` 在隔离 HA 中验证界面添加、参数／连接错误、重复配置拦截、沿用 YAML 实体登记、选项自动重载、重新配置、Key 留空保留、位置修改后 ID 不变、定时刷新取消，以及 YAML 自动导入。0.3.0 已在 HA 2026.9.3 完成这些流程和真实接口验证。

参考：[天气 API](https://dev.qweather.com/docs/api/weather/)、[身份认证](https://dev.qweather.com/docs/configuration/authentication/)、[API Host](https://dev.qweather.com/docs/configuration/api-host/)。

0.4.0 已在 HA 2026.9.3 通过 18 项单元测试、两种认证的界面切换流程，以及真实 JWT 的六类产品和 daily 7 条／hourly 24 条预报服务验证。签名测试使用随机临时密钥，验证公钥验签、必要声明、缓存及续期、时钟回退和标头互斥；仓库不包含私钥或真实认证 ID。
