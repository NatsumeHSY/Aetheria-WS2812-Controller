# A 段参数与 F 段控制指令实施计划

> **执行方式：** Native inline execution。当前工作区没有 Git 仓库，使用计划勾选、失败/通过测试、编译检查和 SDD ledger 作为执行检查点。

**目标：** 将参数指令迁移到 `A0~AF`，将控制指令按 `F0` 起始递增重编码，并让亮度/节奏调整在不清空灯带、不重启效果的情况下实时生效；新增 F4 重启和 F5 清除保存状态后重启。

**架构：** 保持现有 UDP 普通包、CRC4、序号、防重放、重发和效果 `0x00~0x09` 不变。板端增加共享运行参数与参数指令处理，效果循环在帧边界读取参数；客户端将滑块改为发送独立参数包。F 段统一为 F0 握手、F1 health、F2 sync、F3 maintenance、F4 restart、F5 reset-saved-state。

**规格：** `docs/superpowers/specs/2026-10-09-command-layout-design.md`

## 全局约束

- `0x0A` 保持预留，不加入任何映射。
- `F0` 继续使用特殊握手帧结构，仅替换 opcode；`F1~F5` 使用普通协议包。
- 不保留旧 `FE/FD/FC/FF` 兼容别名，板端和客户端成对升级。
- 响应码 `0x01~0x04` 不变。
- `A0/A1` 必须经过现有 ACK、重发、防重放和 `FFFF -> 0000` 序号流程。
- F4 必须保留 `state.bin`；F5 只删除 `state.bin`，不删除固件和网络配置。
- F4/F5 只有在 ACK 已发送后才调用 `machine.reset()`；F5 删除文件失败时不得重启。
- 流光溢彩继续使用固件固定的平滑帧间隔，客户端节奏控件保持禁用。

---

### 任务 1：先更新协议测试并迁移编码常量

**文件：**

- 修改：`tests/test_client_protocol.py`
- 修改：`tests/test_client_maintenance.py`
- 修改：`tests/test_board_maintenance.py`
- 修改：`tests/test_controller_health.py`
- 视需要修改：`tests/test_board_protocol.py`

**实现内容：**

- 将测试期望迁移到 `F0~F5`。
- 增加 `A0/A1` 包构造、长度、payload 和 CRC4 测试。
- 增加 F4/F5 构造器及控制器调用测试。
- 增加握手实际字节为 `LD F0 00 00 00 00` 的断言。
- 保留响应码 `ACK/RESEND/HEALTH_RESPONSE/SYNC_RESPONSE` 的旧断言。

- [x] 编写失败测试。
- [x] 运行协议/维护相关测试，确认因为生产代码仍使用旧编码而失败。
- [x] 完成后续生产代码迁移并回跑，确认绿色。

### 任务 2：迁移板端 F 段控制指令

**文件：**

- 修改：`board/main.py`
- 修改：`client/protocol.py`
- 修改：`client/controller.py`

**实现内容：**

- 板端和客户端统一定义：`HANDSHAKE=F0`、health=`F1`、sync=`F2`、maintenance=`F3`、restart=`F4`、reset saved state=`F5`。
- 更新等待握手阶段的校验和响应。
- 保留 F1/F2 的会话恢复语义和 F3 的维护流程。
- 增加 F4/F5 普通包 builder 与控制器方法。
- F4：通过当前会话序号校验后停止效果、ACK、短暂让出执行时间，再调用 `machine.reset()`。
- F5：通过当前会话序号校验后停止效果，删除 `PERSISTENCE_PATH`；文件不存在视为成功，删除异常则不 ACK、不重启；成功后 ACK、短暂等待，再 `machine.reset()`。
- 控制器方法在设备重启后保留可识别的连接失败/超时行为，不把重启视为普通效果发送失败重试造成的重复破坏操作。

- [x] 增加 F4/F5 失败测试和序号测试。
- [x] 实现板端控制分派，确认维护指令不再走旧 `FC`。
- [x] 实现客户端 builder/controller。
- [x] 运行协议、维护、健康恢复和控制器测试。

### 任务 3：板端共享参数与实时亮度更新

**文件：**

- 修改：`board/main.py`
- 修改：`tests/test_board_effects.py`
- 修改：`tests/test_board_protocol.py`
- 修改：`tests/test_board_persistence.py`

**实现内容：**

- 增加受锁保护的运行参数：`global_brightness`、`global_timing_ms`。
- 默认帧间隔允许到 `1ms`；流光溢彩默认 `10ms`，其循环继续使用固定间隔和小色相步进。
- 将 LED 输出亮度应用拆成“效果基准亮度 × 全局亮度”，使现有效果循环下一帧自然读取新亮度。
- 对静态常亮和自定义矩阵，在 `A0` 更新后基于当前快照重新渲染并直接 `show()`，不先清空。
- 对动画效果，在帧边界读取全局亮度；不调用 `EFFECTOR.stop()`，不创建新效果线程。
- 将支持节奏的效果睡眠间隔改为读取 `global_timing_ms`；流光溢彩排除在外。
- 增加 `led_set_global_brightness()` 和 `led_set_global_timing()`，校验 payload 长度、范围并保存当前状态。
- 将共享参数纳入同步快照和持久化状态；读取旧版本状态时使用默认参数，不破坏已有 `state.bin`。
- 参数更新必须进入普通 `SOCKET_BUFFER`，先完成序号分类和 ACK，再由工作线程执行。

- [x] 编写 A0/A1 不清空、不重启线程、下一帧生效的失败测试。
- [x] 编写静态矩阵重新渲染和动画参数读取测试。
- [x] 编写持久化/同步参数恢复测试。
- [x] 实现共享参数锁、输出亮度缩放和参数 handler。
- [x] 将 A0/A1 加入普通命令映射，确认未知 A/F 指令不会进入效果队列。
- [x] 运行板端效果、协议、持久化、同步测试。

### 任务 4：客户端参数 API 与 WebUI 对齐

**文件：**

- 修改：`client/protocol.py`
- 修改：`client/controller.py`
- 修改：`client/webui/webui.py`
- 修改：`client/webui/scripts/index.js`
- 修改：`client/webui/scripts/runtime_const.js`
- 修改：`client/webui/templates/index.html`
- 修改：客户端相关测试

**实现内容：**

- 增加 `LEDController.set_brightness()` 与 `set_timing()`，分别发送 A0/A1。
- `JavaScriptBridge` 增加对应 bridge 方法，返回统一 `{ok, connected, sequence, error}` 结构。
- 亮度滑块输入改为调用 A0，不再调用 `apply()` 重新启动当前模式。
- 节奏滑块输入改为调用 A1，不再重新启动当前模式；流光溢彩保持禁用。
- 模式、颜色列表、矩阵发送仍使用原效果指令，保持显式模式切换语义。
- 保持本地 UI 状态保存，并确保同步回来的全局亮度/节奏正确刷新控件。
- 增加 F4/F5 的 Bridge API；本次不额外改变已有页面布局，除非现有维护入口需要展示重启/清除状态操作。

- [x] 编写客户端包、Bridge 映射和滑块不触发 `apply()` 的失败测试。
- [x] 实现参数 API 和 UI 调用。
- [x] 运行客户端协议、Bridge、WebUI 和同步恢复测试。

### 任务 5：文档、完整验证与交付审查

**文件：**

- 修改：`.superpowers/sdd/2026-10-09-command-layout/progress.md`
- 必要时更新：旧协议文档中的正式指令描述

**验证：**

- [x] 运行完整 Python 测试：`client\\.venv\\Scripts\\python.exe -m unittest discover -s tests -p "test_*.py"`
- [x] 运行 JavaScript 检查：`node --check client/webui/scripts/index.js`、`node --check client/webui/scripts/runtime_const.js`
- [x] 运行 Python 编译检查：`client\\.venv\\Scripts\\python.exe -m compileall -q board client tests`
- [x] 检查仓库中正式协议引用，不应残留旧 `FE/FD/FC/FF` 常量或旧握手发送路径。
- [x] 检查 F4/F5 不会误删非 `state.bin` 文件，不会在删除失败时重启。
- [x] 更新 SDD ledger，记录每项失败/通过结果和最终测试数量。
