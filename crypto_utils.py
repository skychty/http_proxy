#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
加密解密工具模块
用于客户端和服务端之间的数据加密解密
所有数据在socket层以二进制形式传输，无需base64编码
"""

import secrets
import json

# 密钥长度范围：33-200字节
MIN_KEY_LENGTH = 33
MAX_KEY_LENGTH = 200


def encrypt_data(data: bytes) -> bytes:
    """
    加密数据
    1. 随机生成33-200字节长度的密钥
    2. 用密钥的每个字节循环异或数据的每个字节
    3. 将1字节密钥长度 + 密钥 + 异或后的数据组合（直接返回二进制数据）
    
    Args:
        data: 要加密的原始数据（bytes）
    
    Returns:
        加密后的二进制数据（bytes）：1字节密钥长度 + 密钥 + 加密后的数据
    """
    # 随机生成33-200之间的密钥长度
    key_length = secrets.randbelow(MAX_KEY_LENGTH - MIN_KEY_LENGTH + 1) + MIN_KEY_LENGTH
    
    # 随机生成指定长度的密钥
    key = secrets.token_bytes(key_length)
    
    # 用密钥的每个字节循环异或数据的每个字节
    encrypted_data = bytearray()
    for i in range(len(data)):
        key_index = i % key_length
        encrypted_byte = data[i] ^ key[key_index]
        encrypted_data.append(encrypted_byte)
    
    # 组合：1字节密钥长度 + 密钥 + 加密后的数据
    combined_data = bytes([key_length]) + key + bytes(encrypted_data)
    
    return combined_data


def decrypt_data(encrypted_data: bytes) -> bytes:
    """
    解密数据
    1. 读取第一个字节获取密钥长度
    2. 提取对应长度的密钥
    3. 用密钥循环异或剩余数据
    
    Args:
        encrypted_data: 加密后的二进制数据（bytes）：1字节密钥长度 + 密钥 + 加密后的数据
    
    Returns:
        解密后的原始数据（bytes）
    
    Raises:
        ValueError: 如果密钥长度不在有效范围内或数据格式不正确
    """
    if len(encrypted_data) < 1:
        raise ValueError("加密数据太短，无法读取密钥长度")
    
    # 读取第一个字节获取密钥长度
    key_length = encrypted_data[0]
    
    # 验证密钥长度是否在有效范围内
    if key_length < MIN_KEY_LENGTH or key_length > MAX_KEY_LENGTH:
        raise ValueError(f"无效的密钥长度: {key_length}，应在 {MIN_KEY_LENGTH}-{MAX_KEY_LENGTH} 之间")
    
    # 验证数据长度是否足够
    if len(encrypted_data) < 1 + key_length:
        raise ValueError(f"加密数据太短，无法提取 {key_length} 字节的密钥")
    
    # 提取密钥（跳过第一个字节的长度标识）
    key = encrypted_data[1:1 + key_length]
    
    # 提取剩余部分作为加密数据
    encrypted_part = encrypted_data[1 + key_length:]
    
    # 用密钥循环异或解密
    decrypted_data = bytearray()
    for i in range(len(encrypted_part)):
        key_index = i % key_length
        decrypted_byte = encrypted_part[i] ^ key[key_index]
        decrypted_data.append(decrypted_byte)
    
    return bytes(decrypted_data)


def encrypt_json(json_data: dict) -> bytes:
    """
    将JSON字典加密为bytes
    
    Args:
        json_data: 要加密的JSON字典
    
    Returns:
        加密后的二进制数据（bytes）
    """
    json_str = json.dumps(json_data, ensure_ascii=False)
    json_bytes = json_str.encode('utf-8')
    return encrypt_data(json_bytes)


def decrypt_json(encrypted_data: bytes) -> dict:
    """
    将加密的bytes解密为JSON字典
    
    Args:
        encrypted_data: 加密后的二进制数据（bytes）
    
    Returns:
        解密后的JSON字典
    """
    decrypted_bytes = decrypt_data(encrypted_data)
    json_str = decrypted_bytes.decode('utf-8')
    return json.loads(json_str)
