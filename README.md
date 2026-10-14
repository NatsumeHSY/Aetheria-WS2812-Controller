# Aetheria Desktop/Cloud LED

基于 ESP32-C3 与 WS2812 灯带的矩阵灯效控制项目，包含 MicroPython 板端固件、Python 桌面客户端和主题化 WebView 控制界面。

GitHub：<https://github.com/NatsumeHSY/Aetheria-WS2812-Controller>

## 功能概览

- 144 × 6 WS2812 矩阵编辑与发送
- 快捷颜色、渐变/单色调色板和可保存矩阵预设
- 静态常亮、扫描线、呼吸、彩虹等板端效果
- `transition()` 平滑过渡，支持 RGB 与亮度作为目标状态
- 全局亮度、节奏和白平衡参数
- 白平衡在板端输出层校正，并随板端状态保存
- 健康检查、握手恢复和状态同步
- 板端状态掉电保存，下次通电后独立恢复
- 维护/上传模式、设备重启和状态重置
- 客户端状态栏显示设备在线状态与最近心跳信息

## 项目结构

```text
board/      ESP32-C3 MicroPython 固件
client/     Python 桌面客户端与 WebView UI
docs/       设计文档、协议规划和功能方案
tests/      板端协议、客户端协议和 UI 测试
```

### 板端模块

- `board/main.py`：启动流程、UDP 服务、命令分发和效果调度
- `board/protocol.py`：数据包校验、序号和会话恢复
- `board/state.py`：运行时灯光状态、全局参数和快照
- `board/persistence.py`：`state.bin` 的编码、读取和原子保存
- `board/effects.py`：灯效和颜色插值
- `board/led_driver.py`：WS2812 输出驱动

### 客户端模块

- `client/main.py`：桌面客户端入口
- `client/controller.py`：控制器连接、握手、健康检查、同步和效果 API
- `client/protocol.py`：客户端数据包构造与响应解析
- `client/webui/`：HTML、CSS、JavaScript 和 WebView 桥接
- `client/matrix_shapes.py`：预设矩阵形状与自定义形状管理
- `client/ui_state.py`：客户端 UI 状态持久化

## 通信协议摘要

数据包格式：

```text
LD | command(1) | length(2) | sequence(2) | payload | CRC4(1)
```

命令分段如下：

| 范围 | 用途 |
| --- | --- |
| `0x00`–`0x09` | 灯效与画布控制 |
| `0x0A` | 保留，供后续效果扩充 |
| `0xF0` | 握手 |
| `0xF1` | Health 心跳/会话恢复 |
| `0xF2` | Sync 状态同步 |
| `0xF3` | 进入维护/上传模式 |
| `0xF4` | 重启设备，保留状态 |
| `0xF5` | 重置状态、删除 `state.bin` 后重启 |
| `0xA0` | 全局亮度 |
| `0xA1` | 全局节奏/帧间隔 |
| `0xA2` | RGB 白平衡 |

响应码：`0x01` ACK、`0x02` RESEND、`0x03` HEALTH、`0x04` SYNC。

## 板端部署

1. 使用 Thonny、`mpremote` 或其他 MicroPython 工具连接 ESP32-C3。
2. 将 `board/` 下的 `.py` 文件上传到板端根目录。
3. 重启设备。固件会启动 UDP 服务，默认端口为 `7807`。
4. 板端状态会保存到 `state.bin`；不要手动删除该文件，除非需要恢复默认状态。

默认硬件配置位于 `board/config.py`，当前 WS2812 输出引脚为 GPIO4，矩阵为 6 行 × 144 点。

## 客户端安装与运行

在项目根目录执行：

```powershell
py -m venv client\.venv
client\.venv\Scripts\python.exe -m pip install -r client\requirements.txt
client\.venv\Scripts\python.exe client\main.py
```

客户端默认连接 ESP32-C3 AP 地址 `192.168.4.1:7807`。启动时会优先进行 Health 检查；如果板端仍记得上一次会话，则恢复会话并通过 Sync 同步当前灯效、颜色、亮度、节奏和白平衡，否则执行完整握手。

## 测试与检查

```powershell
python -m compileall -q board client tests
python -m unittest discover -s tests -p "test_*.py"
node --check client/webui/scripts/index.js
git diff --check
```

`client/configs/ui_state.json` 是本地运行时 UI 状态文件，不属于源代码提交内容。

## 安全提示

- 不要把 GitHub PAT、Wi-Fi 密码或设备密钥写入源代码、README 或提交历史。
- 如果密钥曾经出现在聊天、日志或提交中，应立即撤销并重新生成。
- 将仓库改为公开前，请检查完整 Git 历史，而不只是当前工作树。
