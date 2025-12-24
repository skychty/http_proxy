#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTPS中转服务器 - 高并发生产版本
使用asyncio实现异步高并发，支持队列机制、超时控制、连接限制等生产环境特性
"""

import asyncio
import struct
import json
import requests
import logging
import time
import threading
from typing import Optional, Tuple, Dict
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from crypto_utils import decrypt_json, encrypt_json

# 配置日志
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s'
)
logger = logging.getLogger(__name__)

# 禁用SSL警告
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Magic number用于客户端有效性检查
# 使用8字节动态magic：前4字节随机，后4字节由前4字节通过算法计算得出
def calculate_magic_suffix(prefix: bytes) -> bytes:
    """
    根据前4字节计算后4字节magic
    使用简单的位运算算法，性能好且不易被识别
    
    Args:
        prefix: 前4字节（随机生成）
    
    Returns:
        后4字节（由算法计算得出）
    """
    if len(prefix) != 4:
        raise ValueError("prefix必须是4字节")
    
    # 算法：每个字节进行异或和位移运算
    # 使用多个异或和位移操作，使结果看起来随机但可重现
    result = bytearray(4)
    for i in range(4):
        byte_val = prefix[i]
        # 简单的位运算：异或、位移、加法
        result[i] = ((byte_val ^ 0x5A) + (i * 0x17)) & 0xFF
    
    return bytes(result)


class RequestTask:
    """请求任务"""
    def __init__(self, encrypted_packet: bytes, client_address: Tuple = None, 
                 request_id: str = None):
        """
        初始化请求任务
        
        Args:
            encrypted_packet: 加密的数据包（bytes）
            client_address: 客户端地址
            request_id: 请求ID
        """
        self.encrypted_packet = encrypted_packet
        self.client_address = client_address
        self.request_id = request_id or f"{int(time.time() * 1000000)}"
        self.created_at = time.time()
        self.future = asyncio.Future()  # 结果将是加密的响应数据（bytes）


class ServerStats:
    """服务器统计信息"""
    def __init__(self):
        self.lock = threading.Lock()
        self.total_requests = 0
        self.total_success = 0
        self.total_errors = 0
        self.total_timeout = 0
        self.total_rejected = 0
        self.total_connections = 0
        self.active_connections = 0
        self.active_workers = 0
        self.queue_size = 0
        self.request_times = []
        self.error_types = defaultdict(int)
        self.start_time = time.time()
    
    def increment_requests(self):
        with self.lock:
            self.total_requests += 1
    
    def increment_success(self, duration: float):
        with self.lock:
            self.total_success += 1
            self.request_times.append(duration)
            # 只保留最近1000次请求的时间
            if len(self.request_times) > 1000:
                self.request_times.pop(0)
    
    def increment_errors(self, error_type: str):
        with self.lock:
            self.total_errors += 1
            self.error_types[error_type] += 1
    
    def increment_timeout(self):
        with self.lock:
            self.total_timeout += 1
    
    def increment_rejected(self):
        with self.lock:
            self.total_rejected += 1
    
    def increment_connections(self):
        with self.lock:
            self.total_connections += 1
            self.active_connections += 1
    
    def decrement_connections(self):
        with self.lock:
            self.active_connections -= 1
    
    def set_queue_size(self, size: int):
        with self.lock:
            self.queue_size = size
    
    def set_active_workers(self, count: int):
        with self.lock:
            self.active_workers = count
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        with self.lock:
            uptime = time.time() - self.start_time
            avg_time = sum(self.request_times) / len(self.request_times) if self.request_times else 0
            # 计算空闲连接数（连接建立但未发送任何请求就断开）
            # 这些连接会被计入total_connections，但不会产生total_requests或total_rejected
            # 例如：客户端连接后立即断开、keepalive超时等
            idle_connections = self.total_connections - self.total_requests - self.total_rejected
            return {
                'uptime_seconds': int(uptime),
                'total_requests': self.total_requests,
                'total_success': self.total_success,
                'total_errors': self.total_errors,
                'total_timeout': self.total_timeout,
                'total_rejected': self.total_rejected,
                'total_connections': self.total_connections,
                'active_connections': self.active_connections,
                'idle_connections': max(0, idle_connections),  # 未发送请求的连接数（已断开）
                'active_workers': self.active_workers,
                'queue_size': self.queue_size,
                'requests_per_second': self.total_requests / uptime if uptime > 0 else 0,
                'avg_request_time_ms': avg_time * 1000,
                'error_types': dict(self.error_types)
            }


class HTTPSProxyServer:
    """HTTPS中转服务器 - 高并发版本"""
    
    def __init__(self, 
                 host: str = '0.0.0.0', 
                 port: int = 8888,
                 max_connections: int = 10000,  # 最大并发连接数
                 queue_size: int = 50000,  # 请求队列大小
                 worker_threads: int = 100,  # 工作线程数（处理真实HTTPS请求）
                 queue_timeout: float = 30.0,  # 队列等待超时（秒）
                 request_timeout: float = 30.0,  # HTTPS请求超时（秒）
                 keepalive_timeout: float = 60.0,  # Keepalive超时（秒），连接空闲时间超过此值则关闭
                 close_after_response: bool = True):  # 是否在每次响应后关闭连接（HTTP/1.0模式）
        """
        初始化服务器
        
        Args:
            host: 监听地址
            port: 监听端口
            max_connections: 最大并发连接数
            queue_size: 请求队列最大大小
            worker_threads: 工作线程数（处理真实HTTPS请求）
            queue_timeout: 队列等待超时时间（秒）
            request_timeout: HTTPS请求超时时间（秒）
        """
        self.host = host
        self.port = port
        self.max_connections = max_connections
        self.queue_size = queue_size
        self.worker_threads = worker_threads
        self.queue_timeout = queue_timeout
        self.request_timeout = request_timeout
        self.keepalive_timeout = keepalive_timeout
        self.close_after_response = close_after_response
        
        # 连接数限制信号量
        self.connection_semaphore = asyncio.Semaphore(max_connections)
        
        # 请求队列
        self.request_queue = asyncio.Queue(maxsize=queue_size)
        
        # 线程池（处理真实HTTPS请求）
        self.executor = ThreadPoolExecutor(max_workers=worker_threads, thread_name_prefix="HTTPSWorker")
        
        # 统计信息
        self.stats = ServerStats()
        
        # 服务器socket
        self.server = None
        
        # 工作线程任务
        self.worker_tasks = []

        # 测试超时计数
        self.test_timeout_cnt = 1
    
    async def receive_packet(self, reader: asyncio.StreamReader) -> Tuple[Optional[bytes], Optional[str]]:
        """
        接收一个完整的数据包
        数据包格式：8字节magic（前4字节随机+后4字节算法计算） + 4字节包长（大端） + 包数据
        
        Returns:
            (packet_data, error_type)
            - packet_data: 包数据，如果成功返回bytes，失败返回None
            - error_type: 错误类型，'magic_failed'表示magic验证失败，'normal_close'表示正常断开，None表示成功
        """
        try:
            # 接收8字节magic（前4字节随机，后4字节由算法计算）
            magic_data = await asyncio.wait_for(reader.readexactly(8), timeout=10.0)
            
            # 分离前4字节和后4字节
            magic_prefix = magic_data[:4]
            magic_suffix = magic_data[4:]
            
            # 验证后4字节是否等于根据前4字节计算出的值
            expected_suffix = calculate_magic_suffix(magic_prefix)
            if magic_suffix != expected_suffix:
                logger.warning(f"Magic验证失败: 前4字节={magic_prefix.hex()}, "
                             f"收到后4字节={magic_suffix.hex()}, 期望={expected_suffix.hex()}")
                return None, 'magic_failed'  # Magic验证失败
            
            # 接收4字节包长
            length_data = await asyncio.wait_for(reader.readexactly(4), timeout=10.0)
            
            # 解析包长（大端，无符号整数）
            packet_length = struct.unpack('!I', length_data)[0]
            
            if packet_length > 10 * 1024 * 1024:  # 限制最大10MB
                logger.error(f"包长度过大: {packet_length} 字节")
                return None, 'invalid_length'
            
            # 接收包数据
            packet_data = await asyncio.wait_for(reader.readexactly(packet_length), timeout=30.0)
            
            return packet_data, None  # 成功
        
        except asyncio.TimeoutError:
            logger.warning("接收数据包超时")
            return None, 'timeout'
        except asyncio.IncompleteReadError as e:
            # 客户端正常断开连接（EOF），这是正常情况，不应该记录为错误
            if e.partial:
                # 部分数据已接收，可能是异常断开
                logger.debug(f"客户端断开连接（接收数据时，已接收{e.partial}字节）")
                return None, 'incomplete'
            else:
                # 完全未接收数据，可能是正常关闭
                return None, 'normal_close'
        except Exception as e:
            logger.error(f"接收数据包时出错: {e}")
            return None, 'exception'
    
    async def send_packet(self, writer: asyncio.StreamWriter, packet_data: bytes) -> bool:
        """
        发送一个完整的数据包
        数据包格式：4字节包长（大端） + 包数据
        
        Returns:
            True表示发送成功，False表示发送失败（客户端可能已断开）
        """
        try:
            # 发送4字节包长（大端，无符号整数）
            packet_length = len(packet_data)
            length_data = struct.pack('!I', packet_length)
            
            writer.write(length_data)
            writer.write(packet_data)
            await writer.drain()
            
            return True
        
        except (ConnectionResetError, BrokenPipeError, OSError) as e:
            # 客户端已断开连接
            logger.debug(f"发送数据包时客户端已断开: {e}")
            return False
        except Exception as e:
            logger.error(f"发送数据包时出错: {e}")
            return False
    
    def process_request(self, encrypted_packet: bytes, client_address: Tuple = None) -> bytes:
        """
        处理完整请求（在线程池中执行）
        包括：解密 → HTTPS请求 → 加密
        
        Args:
            encrypted_packet: 加密的请求数据包（bytes）
            client_address: 客户端地址（用于日志记录）
        
        Returns:
            加密的响应数据包（bytes）
        """
        request_start_time = time.time()
        client_info = f"{client_address[0]}:{client_address[1]}" if client_address else "unknown"
        
        try:
            # 1. 解密数据包（CPU密集型操作）
            request_json = decrypt_json(encrypted_packet)
            url = request_json.get('url', '')
            headers = request_json.get('headers', {})
            post_data = request_json.get('post_data', None)
            
            # 确定请求方法
            method = 'POST' if post_data else 'GET'
            
            # 2. 验证URL
            if not url:
                logger.error(f"[{client_info}] 请求中缺少URL")
                response_json = {
                    'status_code': 400,
                    'headers': {},
                    'body': 'Missing URL in request'
                }
                encrypted_response = encrypt_json(response_json)
                return encrypted_response
            
            # 记录请求信息
            logger.info(f"[{client_info}] {method} {url}")
            
            # 3. 发送HTTPS请求（阻塞IO操作）
            response_json = self.make_https_request(url, headers, post_data, client_info)
            
            # 4. 加密响应数据（CPU密集型操作）
            encrypted_response = encrypt_json(response_json)
            
            # 记录请求完成信息
            total_duration = time.time() - request_start_time
            status_code = response_json.get('status_code', 0)
            logger.info(f"[{client_info}] {method} {url} -> {status_code} ({total_duration:.3f}s)")
            # if self.test_timeout_cnt > 0:
            #     self.test_timeout_cnt -= 1
            #     time.sleep(20)
            # else:
            #     self.test_timeout_cnt = 1
            return encrypted_response
        
        except json.JSONDecodeError as e:
            logger.error(f"[{client_info}] JSON解析错误: {e}")
            self.stats.increment_errors('json_decode')
            response_json = {
                'status_code': 400,
                'headers': {},
                'body': f'JSON decode error: {str(e)}'
            }
            encrypted_response = encrypt_json(response_json)
            total_duration = time.time() - request_start_time
            logger.info(f"[{client_info}] 请求处理失败 -> 400 ({total_duration:.3f}s)")
            return encrypted_response
        
        except Exception as e:
            logger.error(f"[{client_info}] 处理请求时出错: {e}")
            self.stats.increment_errors(type(e).__name__)
            response_json = {
                'status_code': 500,
                'headers': {},
                'body': f'Server error: {str(e)}'
            }
            encrypted_response = encrypt_json(response_json)
            total_duration = time.time() - request_start_time
            logger.info(f"[{client_info}] 请求处理失败 -> 500 ({total_duration:.3f}s)")
            return encrypted_response
    
    def make_https_request(self, url: str, headers: dict = None, post_data: str = None, client_info: str = None) -> dict:
        """
        发送HTTPS请求（在线程池中执行）
        
        Args:
            url: 请求URL
            headers: 请求头
            post_data: POST数据
            client_info: 客户端信息（用于日志记录）
        
        Returns:
            包含响应数据的字典
        """
        start_time = time.time()
        try:
            # 准备请求头
            request_headers = headers.copy() if headers else {}
            
            # 发送请求
            if post_data:
                response = requests.post(
                    url, 
                    headers=request_headers, 
                    data=post_data, 
                    timeout=self.request_timeout, 
                    verify=False
                )
            else:
                response = requests.get(
                    url, 
                    headers=request_headers, 
                    timeout=self.request_timeout, 
                    verify=False
                )
            
            # 构造响应数据
            duration = time.time() - start_time
            result = {
                'status_code': response.status_code,
                'headers': dict(response.headers),
                'body': response.text
            }
            
            logger.debug(f"HTTPS请求成功: {url} - 状态码: {response.status_code} - 耗时: {duration:.2f}s")
            self.stats.increment_success(duration)
            return result
        
        except requests.exceptions.Timeout:
            duration = time.time() - start_time
            logger.warning(f"HTTPS请求超时: {url} - 耗时: {duration:.2f}s")
            self.stats.increment_errors('timeout')
            return {
                'status_code': 504,
                'headers': {},
                'body': f'Request timeout: {url}'
            }
        except Exception as e:
            duration = time.time() - start_time
            error_type = type(e).__name__
            logger.error(f"HTTPS请求失败: {url} - 错误: {e} - 耗时: {duration:.2f}s")
            self.stats.increment_errors(error_type)
            return {
                'status_code': 500,
                'headers': {},
                'body': f'Request failed: {str(e)}'
            }
    
    async def worker_loop(self, worker_id: int):
        """
        工作线程循环 - 从队列中取出任务并处理
        """
        logger.info(f"工作线程 {worker_id} 启动")
        
        while True:
            try:
                # 从队列中获取任务（带超时）
                task = await asyncio.wait_for(self.request_queue.get(), timeout=1.0)
                
                # 更新统计
                self.stats.set_queue_size(self.request_queue.qsize())
                self.stats.set_active_workers(len([t for t in self.worker_tasks if not t.done()]))
                
                # 在线程池中执行完整请求处理（解密 + HTTPS + 加密）
                try:
                    encrypted_response = await asyncio.get_event_loop().run_in_executor(
                        self.executor,
                        self.process_request,
                        task.encrypted_packet,
                        task.client_address
                    )
                except Exception as e:
                    logger.error(f"处理请求时出错: {e}")
                    # 发生异常时，生成错误响应（小数据，直接在主线程加密，避免线程池切换开销）
                    try:
                        encrypted_response = encrypt_json({
                            'status_code': 500,
                            'headers': {},
                            'body': f'Server error: {str(e)}'
                        })
                    except Exception as encrypt_error:
                        logger.error(f"加密错误响应时出错: {encrypt_error}")
                        # 如果加密也失败，返回一个简单的错误消息
                        encrypted_response = b''
                
                # 设置任务结果（加密的响应数据）
                # 检查future是否已被取消（超时情况）
                if not task.future.done() and not task.future.cancelled():
                    task.future.set_result(encrypted_response)
                elif task.future.cancelled():
                    # 任务已超时被取消，忽略结果（避免冲突）
                    logger.debug(f"任务已超时被取消，忽略处理结果")
                
            except asyncio.TimeoutError:
                # 队列为空，继续等待
                continue
            except Exception as e:
                logger.error(f"工作线程 {worker_id} 出错: {e}")
                if not task.future.done():
                    task.future.set_exception(e)
    
    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """
        处理客户端连接
        """
        # 获取连接许可（如果连接数已满，这里会等待）
        try:
            await asyncio.wait_for(self.connection_semaphore.acquire(), timeout=0.1)
        except asyncio.TimeoutError:
            # 连接数已满，直接拒绝
            logger.warning("连接数已满，拒绝新连接")
            self.stats.increment_rejected()
            writer.close()
            await writer.wait_closed()
            return
        
        client_address = writer.get_extra_info('peername')
        self.stats.increment_connections()
        
        try:
            logger.info(f"客户端连接: {client_address}")
            
            while True:
                # 使用wait_for实现keepalive超时机制
                # 如果连接空闲时间超过keepalive_timeout，则关闭连接
                try:
                    # 接收数据包（带keepalive超时）
                    receive_task = asyncio.create_task(self.receive_packet(reader))
                    encrypted_packet, error_type = await asyncio.wait_for(
                        receive_task,
                        timeout=self.keepalive_timeout
                    )
                except asyncio.TimeoutError:
                    # Keepalive超时，连接空闲时间过长，主动关闭
                    logger.debug(f"连接空闲超时（{self.keepalive_timeout}秒），主动关闭: {client_address}")
                    receive_task.cancel()
                    try:
                        await receive_task
                    except asyncio.CancelledError:
                        pass
                    break
                
                # 检查接收结果
                if encrypted_packet is None:
                    # 根据错误类型决定是否记录日志
                    if error_type == 'magic_failed':
                        # Magic验证失败，这是真正的错误，统计为拒绝连接
                        logger.warning(f"Magic验证失败，断开客户端连接: {client_address}")
                        self.stats.increment_rejected()
                    elif error_type == 'normal_close':
                        # 客户端正常断开连接，不记录为错误
                        logger.debug(f"客户端正常断开连接: {client_address}")
                    elif error_type:
                        # 其他错误（超时、异常等）
                        logger.debug(f"客户端断开连接 ({error_type}): {client_address}")
                    break
                
                self.stats.increment_requests()
                
                try:
                    # 创建请求任务（包含加密的数据包）
                    task = RequestTask(encrypted_packet, client_address=client_address)
                    
                    # 检查队列是否已满
                    if self.request_queue.full():
                        # 队列已满，直接拒绝
                        logger.warning(f"[{client_address[0]}:{client_address[1]}] 请求队列已满，拒绝请求")
                        self.stats.increment_rejected()
                        # 生成错误响应（小数据，直接在主线程加密，避免线程池切换开销）
                        error_response = encrypt_json({
                            'status_code': 503,
                            'headers': {},
                            'body': 'Server busy, queue is full, please try again later'
                        })
                        if not await self.send_packet(writer, error_response):
                            break
                        if self.close_after_response:
                            break
                        continue
                    
                    # 尝试将任务放入队列（带超时）
                    try:
                        await asyncio.wait_for(
                            self.request_queue.put(task),
                            timeout=self.queue_timeout
                        )
                        # 获取加入后的队列大小（注意：由于worker同时取任务，这个值可能小于实际加入的数量）
                        # queue_size = self.request_queue.qsize()
                        # self.stats.set_queue_size(queue_size)
                        # logger.warning(f"[{client_address[0]}:{client_address[1]}] 任务已加入队列，当前排队数量: {queue_size}")
                    except asyncio.TimeoutError:
                        # 等待超时
                        logger.warning(f"[{client_address[0]}:{client_address[1]}] 请求队列等待超时")
                        self.stats.increment_timeout()
                        # 生成错误响应（小数据，直接在主线程加密，避免线程池切换开销）
                        error_response = encrypt_json({
                            'status_code': 503,
                            'headers': {},
                            'body': 'Server busy, please try again later'
                        })
                        if not await self.send_packet(writer, error_response):
                            break
                        if self.close_after_response:
                            break
                        continue
                    
                    # 等待任务完成（带超时）
                    # 任务结果已经是加密的响应数据
                    try:
                        encrypted_response = await asyncio.wait_for(
                            task.future,
                            timeout=self.queue_timeout + self.request_timeout
                        )
                    except asyncio.TimeoutError:
                        logger.warning(f"[{client_address[0]}:{client_address[1]}] 请求处理超时")
                        self.stats.increment_timeout()
                        # 标记任务为已超时（避免worker_loop设置结果时冲突）
                        if not task.future.done():
                            # 取消future，避免worker_loop稍后设置结果
                            task.future.cancel()
                        # 生成超时响应（小数据，直接在主线程加密，避免线程池切换开销）
                        encrypted_response = encrypt_json({
                            'status_code': 504,
                            'headers': {},
                            'body': 'Request processing timeout'
                        })
                    
                    # 发送响应数据包（已经是加密的）
                    send_success = await self.send_packet(writer, encrypted_response)
                    if not send_success:
                        # 发送失败，客户端可能已断开，退出循环
                        logger.debug(f"发送响应失败，客户端可能已断开: {client_address}")
                        break
                    
                    # 如果配置为每次响应后关闭连接（HTTP/1.0模式）
                    if self.close_after_response:
                        logger.debug(f"配置为响应后关闭连接，主动断开: {client_address}")
                        break
                
                except Exception as e:
                    logger.error(f"处理请求时出错: {e}")
                    self.stats.increment_errors(type(e).__name__)
                    # 生成错误响应（小数据，直接在主线程加密，避免线程池切换开销）
                    error_response = encrypt_json({
                        'status_code': 500,
                        'headers': {},
                        'body': f'Server error: {str(e)}'
                    })
                    if not await self.send_packet(writer, error_response):
                        break
                    if self.close_after_response:
                        break
        
        except Exception as e:
            logger.error(f"处理客户端连接时出错: {e}")
        
        finally:
            # 确保连接被正确关闭和统计
            try:
                writer.close()
                await writer.wait_closed()
            except Exception as e:
                logger.debug(f"关闭连接时出错: {e}")
            
            # 减少活跃连接数（必须在finally中确保执行）
            self.stats.decrement_connections()
            self.connection_semaphore.release()  # 释放连接许可
            
            # 安全地获取客户端地址用于日志
            try:
                client_addr = writer.get_extra_info('peername') if hasattr(writer, 'get_extra_info') else client_address
                logger.info(f"客户端断开连接: {client_addr}")
            except:
                logger.debug(f"客户端断开连接（地址获取失败）")
    
    
    async def start(self):
        """启动服务器"""
        # 启动工作线程
        for i in range(self.worker_threads):
            task = asyncio.create_task(self.worker_loop(i))
            self.worker_tasks.append(task)
        
        # 启动服务器
        self.server = await asyncio.start_server(
            self.handle_client,
            self.host,
            self.port
        )
        
        addr = self.server.sockets[0].getsockname()
        logger.info(f"服务器启动，监听 {addr[0]}:{addr[1]}")
        logger.info(f"配置: 最大连接数={self.max_connections}, 队列大小={self.queue_size}, "
                  f"工作线程={self.worker_threads}, 队列超时={self.queue_timeout}s, "
                  f"请求超时={self.request_timeout}s, Keepalive超时={self.keepalive_timeout}s, "
                  f"响应后关闭={self.close_after_response}")
        
        # 启动统计信息打印任务
        asyncio.create_task(self.print_stats_periodically())
        
        async with self.server:
            await self.server.serve_forever()
    
    async def print_stats_periodically(self):
        """定期打印统计信息"""
        while True:
            await asyncio.sleep(60)  # 每60秒打印一次
            stats = self.stats.get_stats()
            logger.info(f"统计信息: {json.dumps(stats, indent=2, ensure_ascii=False)}")
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return self.stats.get_stats()
    
    async def shutdown(self):
        """关闭服务器"""
        logger.info("正在关闭服务器...")
        
        # 关闭服务器socket
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        
        # 取消工作线程任务
        for task in self.worker_tasks:
            task.cancel()
        
        # 关闭线程池
        self.executor.shutdown(wait=True)
        
        logger.info("服务器已关闭")


def main():
    """主函数"""
    import sys
    
    # 解析命令行参数
    host = '0.0.0.0'
    port = 8888
    max_connections = 10000
    queue_size = 50000
    worker_threads = 100
    queue_timeout = 30.0
    request_timeout = 30.0
    keepalive_timeout = 60.0
    close_after_response = True
    
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    if len(sys.argv) > 2:
        host = sys.argv[2]
    if len(sys.argv) > 3:
        max_connections = int(sys.argv[3])
    if len(sys.argv) > 4:
        queue_size = int(sys.argv[4])
    if len(sys.argv) > 5:
        worker_threads = int(sys.argv[5])
    if len(sys.argv) > 6:
        queue_timeout = float(sys.argv[6])
    if len(sys.argv) > 7:
        request_timeout = float(sys.argv[7])
    if len(sys.argv) > 8:
        keepalive_timeout = float(sys.argv[8])
    if len(sys.argv) > 9:
        close_after_response = sys.argv[9].lower() in ('true', '1', 'yes', 'on')
    
    server = HTTPSProxyServer(
        host=host,
        port=port,
        max_connections=max_connections,
        queue_size=queue_size,
        worker_threads=worker_threads,
        queue_timeout=queue_timeout,
        request_timeout=request_timeout,
        keepalive_timeout=keepalive_timeout,
        close_after_response=close_after_response
    )
    
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("收到停止信号")
        asyncio.run(server.shutdown())
    except Exception as e:
        logger.error(f"服务器错误: {e}")
        asyncio.run(server.shutdown())


if __name__ == '__main__':
    main()
