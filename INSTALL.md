# HTTPS代理服务安装指南

## 文件说明

- `https-proxy.sh` - 服务启停脚本（可直接使用）
- `https-proxy.service` - systemd服务文件
- `install.sh` - 安装脚本（安装systemd服务）
- `uninstall.sh` - 卸载脚本（卸载systemd服务）

## 方法一：使用启停脚本（推荐用于测试）

### 1. 设置执行权限

```bash
chmod +x https-proxy.sh
```

### 2. 使用脚本管理服务

```bash
# 启动服务
./https-proxy.sh start

# 停止服务
./https-proxy.sh stop

# 重启服务
./https-proxy.sh restart

# 查看状态
./https-proxy.sh status

# 查看日志（实时）
./https-proxy.sh logs
```

### 3. 自定义配置

编辑 `https-proxy.sh` 文件，修改以下变量：

```bash
HOST="0.0.0.0"                    # 监听地址
PORT="8888"                       # 监听端口
MAX_CONNECTIONS="10000"           # 最大连接数
QUEUE_SIZE="50000"                # 队列大小
WORKER_THREADS="100"              # 工作线程数
QUEUE_TIMEOUT="30.0"              # 队列超时（秒）
REQUEST_TIMEOUT="30.0"            # 请求超时（秒）
KEEPALIVE_TIMEOUT="60.0"          # Keepalive超时（秒）
CLOSE_AFTER_RESPONSE="true"       # 响应后关闭连接
```

## 方法二：安装为系统服务（推荐用于生产环境）

### 1. 设置执行权限

```bash
chmod +x install.sh uninstall.sh
```

### 2. 安装服务

```bash
sudo ./install.sh
```

安装脚本会：
- 复制服务文件到 `/etc/systemd/system/`
- 更新服务文件中的路径
- 启用服务（开机自启动）
- 重新加载systemd

### 3. 管理服务

```bash
# 启动服务
sudo systemctl start https-proxy

# 停止服务
sudo systemctl stop https-proxy

# 重启服务
sudo systemctl restart https-proxy

# 查看状态
sudo systemctl status https-proxy

# 查看日志（实时）
sudo journalctl -u https-proxy -f

# 查看最近100行日志
sudo journalctl -u https-proxy -n 100

# 查看今天的日志
sudo journalctl -u https-proxy --since today
```

### 4. 自定义配置

编辑 `https-proxy.service` 文件，修改 `ExecStart` 行：

```ini
ExecStart=/usr/bin/python3 /root/https_proxy/server.py \
    8888 \           # 端口
    0.0.0.0 \        # 监听地址
    10000 \          # 最大连接数
    50000 \          # 队列大小
    100 \            # 工作线程数
    30.0 \           # 队列超时
    30.0 \           # 请求超时
    60.0 \           # Keepalive超时
    true             # 响应后关闭
```

修改后需要：

```bash
# 重新加载配置
sudo systemctl daemon-reload

# 重启服务
sudo systemctl restart https-proxy
```

### 5. 卸载服务

```bash
sudo ./uninstall.sh
```

## 日志文件位置

### 使用启停脚本
- 日志文件: `/var/log/https-proxy.log`

### 使用systemd服务
- 日志由systemd的journald管理，使用 `journalctl` 查看
- 日志存储在 `/var/log/journal/` 目录（持久化）或 `/run/log/journal/` 目录（临时）

## 日志管理（systemd journald）

### 默认日志限制

当服务通过systemd运行时，日志由journald管理。默认情况下：

1. **存储限制**：
   - `SystemMaxUse`: 默认值为文件系统的10%
   - `SystemKeepFree`: 默认值为文件系统的15%
   - journald会使用两者中较小的值

2. **日志轮转**：
   - 默认每个日志文件最大 `SystemMaxFileSize`（默认未设置，使用系统默认值）
   - 默认保留最多100个日志文件（`SystemMaxFiles=100`）
   - 默认每个日志文件保留1个月（`MaxFileSec=1month`）

3. **自动清理**：
   - 当日志达到限制时，journald会自动删除最旧的日志文件
   - 确保不会填满磁盘空间

### 查看日志使用情况

```bash
# 查看journal日志占用的磁盘空间
journalctl --disk-usage

# 查看当前日志文件数量
ls -lh /var/log/journal/*/ | wc -l
```

### 配置日志限制（可选）

如果需要自定义日志限制，可以创建journald配置文件：

1. **创建配置目录**（如果不存在）：
```bash
sudo mkdir -p /etc/systemd/journald.conf.d
```

2. **创建配置文件** `/etc/systemd/journald.conf.d/https-proxy.conf`：
```ini
[Journal]
# 限制journal日志最多使用2GB磁盘空间
SystemMaxUse=2G

# 确保至少保留1GB的可用空间
SystemKeepFree=1G

# 每个日志文件最大100MB
SystemMaxFileSize=100M

# 最多保留50个日志文件
SystemMaxFiles=50

# 日志文件保留时间（30天）
MaxRetentionSec=30day

# 启用压缩（节省空间）
Compress=yes
```

3. **应用配置**：
```bash
# 重新加载journald配置
sudo systemctl restart systemd-journald

# 注意：重启journald会短暂中断日志记录，但不影响正在运行的服务
```

### 手动清理日志

如果需要立即清理旧日志：

```bash
# 清理7天前的日志
sudo journalctl --vacuum-time=7d

# 清理日志，只保留最近500MB
sudo journalctl --vacuum-size=500M

# 清理日志，只保留最近10个文件
sudo journalctl --vacuum-files=10
```

### 查看服务日志

```bash
# 实时查看日志
sudo journalctl -u https-proxy -f

# 查看最近100行
sudo journalctl -u https-proxy -n 100

# 查看今天的日志
sudo journalctl -u https-proxy --since today

# 查看指定时间范围的日志
sudo journalctl -u https-proxy --since "2024-01-01 00:00:00" --until "2024-01-02 00:00:00"

# 查看错误日志
sudo journalctl -u https-proxy -p err

# 导出日志到文件
sudo journalctl -u https-proxy > /tmp/https-proxy.log
```

### 高并发场景下的日志建议

在高并发场景下（每秒10万请求），日志量会非常大。建议：

1. **调整日志级别**：在生产环境中将日志级别设置为 `WARNING` 或 `ERROR`，减少INFO级别日志
2. **限制日志大小**：设置合理的 `SystemMaxUse` 和 `MaxRetentionSec`
3. **定期清理**：设置定时任务定期清理旧日志
4. **使用日志聚合**：考虑使用ELK、Loki等日志聚合系统，将日志导出到外部存储

## 常见问题

### 1. 服务启动失败

检查：
- Python3是否安装
- 端口是否被占用
- 文件权限是否正确
- 查看日志文件或journalctl

### 2. 修改配置后不生效

使用systemd服务时，修改配置后需要：
```bash
sudo systemctl daemon-reload
sudo systemctl restart https-proxy
```

### 3. 查看详细错误信息

```bash
# systemd服务
sudo journalctl -u https-proxy -n 50 --no-pager

# 启停脚本
tail -n 50 /var/log/https-proxy.log
```

### 4. 服务无法开机自启动

确保服务已启用：
```bash
sudo systemctl enable https-proxy
sudo systemctl is-enabled https-proxy  # 应该显示 enabled
```

## 性能调优建议

根据服务器配置调整以下参数：

### 小型服务器（1-2核，2-4GB内存）
```bash
MAX_CONNECTIONS="5000"
QUEUE_SIZE="25000"
WORKER_THREADS="50"
```

### 中型服务器（4-8核，8-16GB内存）
```bash
MAX_CONNECTIONS="20000"
QUEUE_SIZE="100000"
WORKER_THREADS="200"
```

### 大型服务器（16+核，32+GB内存）
```bash
MAX_CONNECTIONS="100000"
QUEUE_SIZE="500000"
WORKER_THREADS="500"
```

## 安全建议

1. **修改服务用户**：不要使用root用户运行服务
   ```ini
   User=your-user
   Group=your-group
   ```

2. **限制资源**：服务文件中已包含资源限制
   ```ini
   LimitNOFILE=65535
   LimitNPROC=4096
   ```

3. **防火墙配置**：只开放必要的端口
   ```bash
   sudo ufw allow 8888/tcp
   ```

4. **日志轮转**：配置日志轮转避免日志文件过大

## 监控建议

1. **健康检查**：定期检查服务状态
   ```bash
   systemctl is-active https-proxy
   ```

2. **性能监控**：监控CPU、内存、网络使用情况

3. **日志监控**：设置日志告警，及时发现错误

