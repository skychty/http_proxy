# HTTPS代理服务 - 负载均衡部署指南

## 架构概述

```
客户端
  ↓
[负载均衡器] (HAProxy/Nginx)
  ↓ (TCP转发)
[实例1:8888] [实例2:8888] [实例3:8888] ... [实例N:8888]
```

## 一、多实例部署

### 1.1 部署架构

建议在同一台服务器或不同服务器上部署多个实例，每个实例监听不同的端口或IP地址。

#### 方案A：单机多实例（不同端口）

```bash
# 实例1 - 端口 8888
python3 server.py 8888 0.0.0.0 10000 50000 100 30.0 30.0 60.0 true

# 实例2 - 端口 8889
python3 server.py 8889 0.0.0.0 10000 50000 100 30.0 30.0 60.0 true

# 实例3 - 端口 8890
python3 server.py 8890 0.0.0.0 10000 50000 100 30.0 30.0 60.0 true
```

#### 方案B：多机多实例（推荐）

```
服务器1: 192.168.1.10:8888
服务器2: 192.168.1.11:8888
服务器3: 192.168.1.12:8888
```

### 1.2 使用systemd管理多实例

创建多个service文件：

```bash
# /etc/systemd/system/https-proxy@.service
[Unit]
Description=HTTPS Proxy Server Instance %i
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/root/https_proxy
ExecStart=/usr/bin/python3 /root/https_proxy/server.py 888%i 0.0.0.0 10000 50000 100 30.0 30.0 60.0 true
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=https-proxy-%i

LimitNOFILE=65535
LimitNPROC=4096
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
```

启动多个实例：
```bash
systemctl enable https-proxy@1
systemctl enable https-proxy@2
systemctl enable https-proxy@3
systemctl start https-proxy@1
systemctl start https-proxy@2
systemctl start https-proxy@3
```

### 1.3 实例配置建议

每个实例的配置应该根据服务器资源分配：

```bash
# 假设服务器有32核CPU，64GB内存
# 可以部署4个实例，每个实例使用8核

# 实例1
python3 server.py 8888 0.0.0.0 10000 50000 200 30.0 30.0 60.0 true

# 实例2
python3 server.py 8889 0.0.0.0 10000 50000 200 30.0 30.0 60.0 true

# 实例3
python3 server.py 8890 0.0.0.0 10000 50000 200 30.0 30.0 60.0 true

# 实例4
python3 server.py 8891 0.0.0.0 10000 50000 200 30.0 30.0 60.0 true
```

## 二、负载均衡器选择

### 2.1 推荐方案对比

| 方案 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| **HAProxy** | 功能强大、性能优秀、配置灵活、支持健康检查 | 需要单独安装 | **推荐：生产环境首选** |
| **Nginx Stream** | 配置简单、与Web服务统一管理 | TCP性能略低于HAProxy | 已有Nginx环境 |
| **LVS** | 内核级转发、性能最高 | 配置复杂、需要内核模块 | 超大规模场景 |
| **云负载均衡器** | 无需维护、自动扩展 | 成本较高、依赖云服务商 | 云环境部署 |

### 2.2 方案一：HAProxy（强烈推荐）

HAProxy是专业的TCP/HTTP负载均衡器，性能优秀，功能完善。

#### 安装HAProxy

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install haproxy

# CentOS/RHEL
sudo yum install haproxy
# 或
sudo dnf install haproxy
```

#### HAProxy配置

编辑 `/etc/haproxy/haproxy.cfg`：

```haproxy
global
    log /dev/log local0
    log /dev/log local1 notice
    chroot /var/lib/haproxy
    stats socket /run/haproxy/admin.sock mode 660 level admin
    stats timeout 30s
    user haproxy
    group haproxy
    daemon
    maxconn 100000

defaults
    log global
    mode tcp
    option tcplog
    option dontlognull
    timeout connect 5000ms
    timeout client 50000ms
    timeout server 50000ms
    retries 3

# 统计页面（可选）
listen stats
    mode http          # 统计页面需要 HTTP 模式
    bind *:8404
    stats enable
    stats uri /stats
    stats refresh 30s
    stats admin if TRUE

# HTTPS代理服务负载均衡
frontend https_proxy_frontend
    bind *:8888
    mode tcp
    default_backend https_proxy_backend

backend https_proxy_backend
    mode tcp
    balance roundrobin  # 轮询算法
    # balance leastconn  # 最少连接算法（推荐）
    # balance source     # 源IP哈希算法（保持会话）
    
    # 健康检查配置
    option tcp-check
    
    # 后端服务器列表
    server instance1 127.0.0.1:8888 check inter 2000 fall 3 rise 2
    server instance2 127.0.0.1:8889 check inter 2000 fall 3 rise 2
    server instance3 127.0.0.1:8890 check inter 2000 fall 3 rise 2
    
    # 如果是多机部署，使用IP地址：
    # server instance1 192.168.1.10:8888 check inter 2000 fall 3 rise 2
    # server instance2 192.168.1.11:8888 check inter 2000 fall 2000 rise 2
    # server instance3 192.168.1.12:8888 check inter 2000 fall 3 rise 2
```

#### 负载均衡算法说明

- **roundrobin**：轮询，依次分配请求到各后端
- **leastconn**：最少连接，优先分配给连接数最少的后端（推荐）
- **source**：源IP哈希，相同IP的请求总是转发到同一后端（保持会话）

#### 启动HAProxy

```bash
# 检查配置
sudo haproxy -f /etc/haproxy/haproxy.cfg -c

# 启动服务
sudo systemctl start haproxy
sudo systemctl enable haproxy
sudo systemctl status haproxy
```

#### 查看统计信息

访问 `http://负载均衡器IP:8404/stats` 查看实时统计信息。

### 2.3 方案二：Nginx Stream模块

如果您的环境已有Nginx，可以使用Nginx的stream模块进行TCP负载均衡。

#### 安装Nginx（包含stream模块）

```bash
# Ubuntu/Debian
sudo apt-get install nginx

# CentOS/RHEL
sudo yum install nginx
```

#### Nginx配置

编辑 `/etc/nginx/nginx.conf`，在 `http {}` 块外添加：

```nginx
stream {
    # 定义上游服务器组
    upstream https_proxy_backend {
        least_conn;  # 最少连接算法
        # hash $remote_addr consistent;  # 源IP哈希（保持会话）
        
        server 127.0.0.1:8888 max_fails=3 fail_timeout=30s;
        server 127.0.0.1:8889 max_fails=3 fail_timeout=30s;
        server 127.0.0.1:8890 max_fails=3 fail_timeout=30s;
        
        # 多机部署示例：
        # server 192.168.1.10:8888 max_fails=3 fail_timeout=30s;
        # server 192.168.1.11:8888 max_fails=3 fail_timeout=30s;
        # server 192.168.1.12:8888 max_fails=3 fail_timeout=30s;
    }
    
    # TCP负载均衡服务器
    server {
        listen 8888;
        proxy_pass https_proxy_backend;
        proxy_timeout 60s;
        proxy_connect_timeout 5s;
        
        # 保持连接
        proxy_socket_keepalive on;
    }
}
```

#### 启动Nginx

```bash
# 检查配置
sudo nginx -t

# 启动/重载
sudo systemctl start nginx
sudo systemctl reload nginx
sudo systemctl enable nginx
```

### 2.4 方案三：LVS（Linux Virtual Server）

LVS是内核级的负载均衡，性能最高，适合超大规模场景。

#### 安装LVS

```bash
# Ubuntu/Debian
sudo apt-get install ipvsadm

# CentOS/RHEL
sudo yum install ipvsadm
```

#### LVS配置（DR模式示例）

```bash
# 在负载均衡器上配置VIP
sudo ip addr add 192.168.1.100/24 dev eth0

# 配置LVS规则
sudo ipvsadm -A -t 192.168.1.100:8888 -s rr  # 轮询
# sudo ipvsadm -A -t 192.168.1.100:8888 -s lc  # 最少连接

# 添加后端服务器
sudo ipvsadm -a -t 192.168.1.100:8888 -r 192.168.1.10:8888 -g
sudo ipvsadm -a -t 192.168.1.100:8888 -r 192.168.1.11:8888 -g
sudo ipvsadm -a -t 192.168.1.100:8888 -r 192.168.1.12:8888 -g

# 查看规则
sudo ipvsadm -ln
```

LVS配置较复杂，需要配置后端服务器的VIP和ARP抑制，建议参考LVS官方文档。

## 三、健康检查

### 3.1 HAProxy健康检查

HAProxy会自动进行TCP健康检查，配置中的 `check inter 2000 fall 3 rise 2` 表示：
- `inter 2000`：每2秒检查一次
- `fall 3`：连续3次失败后标记为down
- `rise 2`：连续2次成功后标记为up

### 3.2 自定义健康检查脚本（可选）

如果需要更复杂的健康检查，可以编写脚本：

```bash
#!/bin/bash
# /usr/local/bin/check_https_proxy.sh

PORT=$1
HOST=${2:-127.0.0.1}

# 简单的TCP连接检查
timeout 1 bash -c "echo > /dev/tcp/$HOST/$PORT" 2>/dev/null
exit $?
```

在HAProxy配置中使用：
```haproxy
server instance1 127.0.0.1:8888 check inter 2000 fall 3 rise 2 check-send-proxy
```

## 四、会话保持（Sticky Session）

如果需要在同一会话中保持连接到同一后端，可以使用源IP哈希：

### HAProxy配置
```haproxy
backend https_proxy_backend
    mode tcp
    balance source  # 源IP哈希
    server instance1 127.0.0.1:8888 check
    server instance2 127.0.0.1:8889 check
    server instance3 127.0.0.1:8890 check
```

### Nginx配置
```nginx
upstream https_proxy_backend {
    hash $remote_addr consistent;
    server 127.0.0.1:8888;
    server 127.0.0.1:8889;
    server 127.0.0.1:8890;
}
```

## 五、监控和日志

### 5.1 HAProxy统计页面

访问 `http://负载均衡器IP:8404/stats` 查看：
- 实时连接数
- 请求速率
- 后端服务器状态
- 错误统计

### 5.2 日志配置

HAProxy日志：
```bash
# 查看HAProxy日志
sudo tail -f /var/log/haproxy.log
```

Nginx日志：
```nginx
stream {
    log_format tcp_proxy '$remote_addr [$time_local] '
                         '$protocol $status $bytes_sent $bytes_received '
                         '$session_time';
    
    access_log /var/log/nginx/tcp-access.log tcp_proxy;
}
```

## 六、性能优化

### 6.1 系统参数优化

```bash
# 增加文件描述符限制
echo "* soft nofile 1000000" >> /etc/security/limits.conf
echo "* hard nofile 1000000" >> /etc/security/limits.conf

# TCP参数优化
cat >> /etc/sysctl.conf <<EOF
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 30
net.ipv4.ip_local_port_range = 1024 65535
EOF

sysctl -p
```

### 6.2 HAProxy性能优化

```haproxy
global
    maxconn 100000
    nbproc 4  # 多进程模式（根据CPU核心数）
    nbthread 4  # 多线程模式（新版本支持）

defaults
    maxconn 50000
```

## 七、部署检查清单

- [ ] 部署多个后端实例
- [ ] 配置负载均衡器（HAProxy/Nginx）
- [ ] 配置健康检查
- [ ] 测试负载均衡功能
- [ ] 配置监控和日志
- [ ] 优化系统参数
- [ ] 配置防火墙规则
- [ ] 设置自动启动（systemd）
- [ ] 准备故障转移方案

## 八、故障排查

### 8.1 连接被拒绝

```bash
# 检查后端服务是否运行
sudo systemctl status https-proxy@1

# 检查端口是否监听
sudo netstat -tlnp | grep 8888

# 检查防火墙
sudo iptables -L -n
```

### 8.2 负载不均衡

- 检查后端服务器状态（HAProxy统计页面）
- 检查负载均衡算法是否合适
- 检查是否有后端服务器被标记为down

### 8.3 性能问题

- 检查系统资源（CPU、内存、网络）
- 检查连接数是否达到上限
- 检查后端服务器响应时间
- 考虑增加后端实例数量

## 九、推荐配置示例

### 生产环境推荐配置

**架构：**
- 3台服务器，每台部署2个实例
- 1台负载均衡器（HAProxy）

**服务器配置：**
- 每台服务器：16核CPU，32GB内存
- 每个实例：最大连接数10000，工作线程200

**负载均衡器配置：**
- HAProxy：最少连接算法
- 健康检查：每2秒检查一次
- 超时：连接超时5秒，客户端/服务器超时50秒

这样可以支持：
- 总并发连接：3 × 2 × 10000 = 60,000
- 理论QPS：根据后端服务器性能，可达数万QPS

