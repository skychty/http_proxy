# HTTPS代理服务 - 高并发生产版本

## 项目说明

这是一个高性能的HTTPS代理服务，支持高并发请求处理。服务端使用异步IO（asyncio）实现高并发，通过请求队列和工作线程池来处理真实的HTTPS请求。

## 架构特点

### 1. 异步高并发
- 使用 `asyncio` 实现异步IO，支持大量并发连接
- 每个客户端连接都是异步处理，不会阻塞其他连接

### 2. 请求队列机制
- 使用 `asyncio.Queue` 作为请求队列
- 客户端请求先进入队列，由工作线程池异步处理
- 队列大小可配置，队列满时直接拒绝新请求

### 3. 工作线程池
- 使用 `ThreadPoolExecutor` 处理真实的HTTPS请求
- 工作线程数可根据服务器性能配置
- 避免阻塞事件循环

### 4. 超时机制
- **队列等待超时**：客户端在队列中等待的时间限制
- **请求处理超时**：HTTPS请求的总处理时间限制
- 超时后自动返回错误响应

### 5. 连接数限制
- 使用信号量限制最大并发连接数
- 连接数满时直接拒绝新连接
- 防止服务器过载

### 6. 统计监控
- 实时统计请求数、成功率、错误类型等
- 定期打印统计信息（每60秒）
- 支持查看平均响应时间、QPS等指标

## 配置参数

服务端启动参数（按顺序）：

```bash
python3 server.py [端口] [地址] [最大连接数] [队列大小] [工作线程数] [队列超时] [请求超时]
```

参数说明：
- **端口** (默认: 8888): 监听端口
- **地址** (默认: 0.0.0.0): 监听地址
- **最大连接数** (默认: 10000): 最大并发连接数
- **队列大小** (默认: 50000): 请求队列最大大小
- **工作线程数** (默认: 100): 处理HTTPS请求的工作线程数
- **队列超时** (默认: 30.0): 队列等待超时时间（秒）
- **请求超时** (默认: 30.0): HTTPS请求超时时间（秒）

### 示例

```bash
# 使用默认配置
python3 server.py

# 自定义端口和地址
python3 server.py 9999 0.0.0.0

# 完整配置（支持10万并发）
python3 server.py 8888 0.0.0.0 100000 500000 500 30.0 30.0
```

## 性能优化建议

### 1. 工作线程数配置
- **CPU密集型**：工作线程数 = CPU核心数
- **IO密集型**：工作线程数 = CPU核心数 × 2-4
- **网络请求**：建议设置为 100-500，根据实际网络延迟调整

### 2. 队列大小配置
- 队列大小应该大于最大连接数
- 建议：队列大小 = 最大连接数 × 5-10
- 过大的队列会占用内存，过小会导致频繁拒绝请求

### 3. 连接数限制
- 根据服务器内存和网络带宽设置
- 每个连接大约占用几KB到几十KB内存
- 建议从10000开始，根据实际情况调整

### 4. 超时时间配置
- **队列超时**：建议设置为平均请求处理时间的2-3倍
- **请求超时**：根据目标服务器的响应时间设置，建议20-60秒

## 生产环境部署

### 1. 使用systemd管理（推荐）

创建 `/etc/systemd/system/https-proxy.service`:

```ini
[Unit]
Description=HTTPS Proxy Server
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/https_proxy
ExecStart=/usr/bin/python3 /path/to/https_proxy/server.py 8888 0.0.0.0 100000 500000 500 30.0 30.0
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务：
```bash
sudo systemctl enable https-proxy
sudo systemctl start https-proxy
sudo systemctl status https-proxy
```

### 2. 使用supervisor管理

创建 `/etc/supervisor/conf.d/https-proxy.conf`:

```ini
[program:https-proxy]
command=/usr/bin/python3 /path/to/https_proxy/server.py 8888 0.0.0.0 100000 500000 500 30.0 30.0
directory=/path/to/https_proxy
user=your-user
autostart=true
autorestart=true
stderr_logfile=/var/log/https-proxy.err.log
stdout_logfile=/var/log/https-proxy.out.log
```

### 3. 性能调优

#### 系统级优化
```bash
# 增加文件描述符限制
ulimit -n 1000000

# 优化TCP参数
echo 'net.core.somaxconn = 65535' >> /etc/sysctl.conf
echo 'net.ipv4.tcp_max_syn_backlog = 65535' >> /etc/sysctl.conf
sysctl -p
```

#### Python优化
- 使用 PyPy 可以提升性能（需要测试兼容性）
- 考虑使用 uvloop 替代默认事件循环（需要安装）

## 监控和日志

### 统计信息

服务器每60秒自动打印统计信息，包括：
- 运行时间
- 总请求数、成功数、错误数
- 超时数、拒绝数
- 当前活跃连接数、工作线程数、队列大小
- 每秒请求数（QPS）
- 平均请求处理时间
- 错误类型统计

### 日志级别

可以通过修改代码中的日志级别来调整日志详细程度：
```python
logging.basicConfig(level=logging.INFO)  # INFO, DEBUG, WARNING, ERROR
```

## 客户端使用

客户端使用方式不变：

```bash
# GET请求
python3 client.py https://www.example.com

# POST请求
python3 client.py https://www.example.com POST

# 指定服务器地址和端口
python3 client.py https://www.example.com GET server.example.com 8888
```

## 故障排查

### 1. 连接被拒绝
- 检查服务器是否启动
- 检查防火墙设置
- 检查连接数是否已满

### 2. 请求超时
- 检查目标服务器是否可访问
- 检查网络延迟
- 调整超时时间配置

### 3. 队列已满
- 增加队列大小
- 增加工作线程数
- 检查是否有慢请求阻塞队列

### 4. 性能问题
- 检查系统资源（CPU、内存、网络）
- 调整工作线程数
- 检查目标服务器响应时间

## 安全建议

1. **使用防火墙**：只允许必要的IP访问
2. **使用TLS**：在生产环境中考虑添加TLS加密
3. **访问控制**：考虑添加认证机制
4. **限流**：可以添加基于IP的限流机制
5. **日志审计**：记录所有请求日志用于审计

## 扩展功能建议

1. **负载均衡**：多实例部署，使用负载均衡器分发请求
2. **缓存机制**：对相同请求添加缓存
3. **限流策略**：基于IP、用户等的限流
4. **健康检查**：HTTP健康检查端点
5. **指标导出**：Prometheus指标导出
6. **分布式追踪**：添加请求追踪ID

## 许可证

MIT License

