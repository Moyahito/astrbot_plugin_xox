"""
数据管理器模块

负责：
- 偶像信息、昵称、简介的存储
- 应援口号的存储
- 用户签到记录的存储
- 管理员列表的存储
- 图片文件的随机获取

所有数据文件存储在 data 目录下，确保插件更新时数据不丢失
"""
import os
import json
import random
import logging

class DataManager:
    """数据管理器，负责所有持久化数据的读写"""
    def __init__(self, plugin_dir, plugin_data_dir=None, config=None):
        # 设置数据和图片目录
        self.data_dir = os.path.join(plugin_dir, "data")
        # 如果指定了 plugin_data_dir，使用它作为图片目录；否则使用插件目录下的 img
        if plugin_data_dir:
            self.img_dir = plugin_data_dir
        else:
            self.img_dir = os.path.join(plugin_dir, "img")
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.img_dir, exist_ok=True)
        
        # 读取配置
        self.config = config or {}
        # 获取图片格式配置，默认为常见格式
        self.image_formats = self.config.get("image_formats", [".png", ".jpg", ".jpeg", ".gif", ".bmp"])

        # 文件路径
        self.files = {
            "idols": os.path.join(self.data_dir, "idols.json"),         # 偶像名单、昵称、简介
            "catchphrases": os.path.join(self.data_dir, "catchphrases.json"), # 应援口号
            "users": os.path.join(self.data_dir, "users.json"),         # 签到记录
            "groups": os.path.join(self.data_dir, "groups.json"),       # 群组信息 (占位)
            "admins": os.path.join(self.data_dir, "admins.json")        # 授权管理员
        }

        self.data = {}
        self.load_all()

    def load_all(self):
        for key, path in self.files.items():
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        self.data[key] = json.load(f)
                except json.JSONDecodeError:
                    # 如果文件损坏，重置为空
                    self.data[key] = {} if key not in ["admins"] else []
                    self.save(key)
            else:
                # 初始化空结构
                self.data[key] = {} if key not in ["admins"] else []
                self.save(key)

    def save(self, key):
        """保存数据到文件，带异常处理"""
        try:
            os.makedirs(os.path.dirname(self.files[key]), exist_ok=True)
            with open(self.files[key], 'w', encoding='utf-8') as f:
                json.dump(self.data[key], f, ensure_ascii=False, indent=2)
        except (IOError, OSError) as e:
            # 记录错误但不抛出异常，避免影响主流程
            logging.error(f"保存文件 {self.files[key]} 失败: {e}")

    # --- 小偶像相关 ---
    
    def get_real_name(self, name_or_nick):
        """通过昵称查找真名"""
        idols = self.data.get("idols", {})
        if name_or_nick in idols:
            return name_or_nick
        for name, info in idols.items():
            if name_or_nick in info.get("nicknames", []):
                return name
        return None

    def add_idol(self, name):
        """注册一个小偶像并创建图片文件夹"""
        if not name or not name.strip():
            return  # 忽略空名称
        name = name.strip()
        idols = self.data.setdefault("idols", {})
        if name not in idols:
            # 默认信息字段，供 /xox 使用
            idols[name] = {
                "nicknames": [],
                "info": "这个人很神秘，目前还没有公开资料，等待管理员补充。"
            }
            self.save("idols")
            # 自动创建图片文件夹
            os.makedirs(os.path.join(self.img_dir, name), exist_ok=True)

    def get_random_idol(self):
        """随机获取一个已注册的小偶像名字"""
        idols = list(self.data.get("idols", {}).keys())
        return random.choice(idols) if idols else None

    # --- 图片相关 ---

    def get_random_image_path(self, idol_name):
        """从 plugin_data/插件名/idol_name/ 目录下随机获取一张图片路径"""
        folder_path = os.path.join(self.img_dir, idol_name)
        
        if not os.path.exists(folder_path):
            return None
        
        try:
            # 筛选图片文件，使用配置的图片格式
            images = [f for f in os.listdir(folder_path) 
                     if any(f.lower().endswith(fmt.lower()) for fmt in self.image_formats)]
            
            if not images:
                return None
                
            return os.path.join(folder_path, random.choice(images))
        except (OSError, PermissionError) as e:
            # 处理权限错误或目录访问错误
            logging.error(f"访问图片目录 {folder_path} 失败: {e}")
            return None