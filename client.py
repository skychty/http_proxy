#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTPS中转客户端
通过TCP socket连接服务器，发送HTTPS请求并接收响应
"""

import socket
import struct
import json
import logging
from typing import Optional, Tuple
from crypto_utils import encrypt_json, decrypt_json

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Magic number用于客户端有效性检查
# 使用8字节动态magic：前4字节随机，后4字节由前4字节通过算法计算得出
import secrets

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


class HTTPSProxyClient:
    """HTTPS中转客户端"""
    
    def __init__(self, server_host: str = 'localhost', server_port: int = 8888):
        """
        初始化客户端
        
        Args:
            server_host: 服务器地址
            server_port: 服务器端口
        """
        self.server_host = server_host
        self.server_port = server_port
        self.socket = None
    
    def connect(self) -> bool:
        """
        连接到服务器
        
        Returns:
            是否连接成功
        """
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.server_host, self.server_port))
            logger.info(f"已连接到服务器 {self.server_host}:{self.server_port}")
            return True
        except Exception as e:
            logger.error(f"连接服务器失败: {e}")
            return False
    
    def disconnect(self):
        """断开连接"""
        if self.socket:
            try:
                self.socket.close()
                logger.info("已断开连接")
            except:
                pass
            self.socket = None
    
    def send_packet(self, packet_data: bytes) -> bool:
        """
        发送一个完整的数据包
        数据包格式：8字节magic（前4字节随机+后4字节算法计算） + 4字节包长（大端） + 包数据
        
        Args:
            packet_data: 包数据（bytes）
        
        Returns:
            是否发送成功
        """
        if not self.socket:
            logger.error("未连接到服务器")
            return False
        
        try:
            # 生成随机4字节作为magic前缀
            magic_prefix = secrets.token_bytes(4)
            # 根据前缀计算后4字节
            magic_suffix = calculate_magic_suffix(magic_prefix)
            # 组合成8字节magic
            magic_data = magic_prefix + magic_suffix
            # 发送8字节magic
            self.socket.sendall(magic_data)
            
            # 发送4字节包长（大端，无符号整数）
            packet_length = len(packet_data)
            length_data = struct.pack('!I', packet_length)
            self.socket.sendall(length_data)
            
            # 发送包数据
            self.socket.sendall(packet_data)
            logger.debug(f"发送包长度: {packet_length} 字节")
            return True
        
        except Exception as e:
            logger.error(f"发送数据包时出错: {e}")
            return False
    
    def receive_packet(self) -> Optional[bytes]:
        """
        接收一个完整的数据包
        数据包格式：4字节包长（大端） + 包数据
        
        Returns:
            包数据（bytes），如果出错返回None
        """
        if not self.socket:
            logger.error("未连接到服务器")
            return None
        
        try:
            # 接收4字节包长
            length_data = b''
            while len(length_data) < 4:
                chunk = self.socket.recv(4 - len(length_data))
                if not chunk:
                    logger.warning("服务器断开连接（接收长度时）")
                    return None
                length_data += chunk
            
            # 解析包长（大端，无符号整数）
            packet_length = struct.unpack('!I', length_data)[0]
            logger.debug(f"接收包长度: {packet_length} 字节")
            
            if packet_length > 10 * 1024 * 1024:  # 限制最大10MB
                logger.error(f"包长度过大: {packet_length} 字节")
                return None
            
            # 接收包数据
            packet_data = b''
            while len(packet_data) < packet_length:
                chunk = self.socket.recv(packet_length - len(packet_data))
                if not chunk:
                    logger.warning("服务器断开连接（接收数据时）")
                    return None
                packet_data += chunk
            
            return packet_data
        
        except Exception as e:
            logger.error(f"接收数据包时出错: {e}")
            return None
    
    def request(self, url: str, headers: dict = None, post_data: str = None) -> Optional[dict]:
        """
        发送HTTPS请求
        
        Args:
            url: 请求URL
            headers: 请求头（字典）
            post_data: POST数据（字符串），如果为None则发送GET请求
        
        Returns:
            包含响应数据的字典
            {
                'status_code': int,
                'headers': dict,
                'body': str
            }
            如果出错返回None
        """
        if not self.socket:
            if not self.connect():
                return None
        
        try:
            # 构造请求JSON
            request_json = {
                'url': url,
                'headers': headers or {},
            }
            if post_data:
                request_json['post_data'] = post_data
            
            # 加密请求数据
            encrypted_request = encrypt_json(request_json)
            
            # 发送请求数据包
            if not self.send_packet(encrypted_request):
                return None
            
            # 接收响应数据包
            encrypted_response = self.receive_packet()
            if encrypted_response is None:
                return None
            
            # 解密响应数据
            response_json = decrypt_json(encrypted_response)
            
            logger.info(f"请求成功: {url} - 状态码: {response_json.get('status_code', 'N/A')}")
            return response_json
        
        except Exception as e:
            logger.error(f"请求失败: {url} - 错误: {e}")
            return None
    
    def __enter__(self):
        """上下文管理器入口"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.disconnect()


def main():
    """主函数 - 示例用法"""
    import sys
    
    # 解析命令行参数
    server_host = 'localhost'
    server_port = 8888
    url = 'https://www.example.com'
    method = 'GET'
    post_data = None
    
    if len(sys.argv) > 1:
        url = sys.argv[1]
    if len(sys.argv) > 2:
        method = sys.argv[2].upper()
    if len(sys.argv) > 3:
        server_host = sys.argv[3]
    if len(sys.argv) > 4:
        server_port = int(sys.argv[4])
    if len(sys.argv) > 5 and method == 'POST':
        post_data = sys.argv[5]
    
    # 使用上下文管理器
    with HTTPSProxyClient(server_host=server_host, server_port=server_port) as client:
        # 发送请求
        if method == 'POST':
            response = client.request(url, headers={'Content-Type': 'application/json'}, post_data=post_data)
        else:
            response = client.request(url)
        
        if response:
            print(f"\n状态码: {response.get('status_code')}")
            print(f"响应头: {json.dumps(response.get('headers', {}), indent=2, ensure_ascii=False)}")
            print(f"\n响应体 (前500字符):")
            body = response.get('body', '')
            print(body[:500])
            if len(body) > 500:
                print(f"... (总共 {len(body)} 字符)")
        else:
            print("请求失败")


if __name__ == '__main__':
    main()
