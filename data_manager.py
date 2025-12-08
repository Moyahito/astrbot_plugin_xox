"""
数据管理器模块

负责：
- 小偶像信息、昵称、简介的存储
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
        # 设置数据目录
        self.data_dir = os.path.join(plugin_dir, "data")
        os.makedirs(self.data_dir, exist_ok=True)

        # 图片目录：primary 优先（可配置为爬虫目录），fallback 其次（默认 plugin_data）
        self.config = config or {}
        fallback_img_dir = self.config.get("fallback_img_dir")
        self.img_dirs = []
        if plugin_data_dir:
            self.img_dirs.append(plugin_data_dir)
        else:
            self.img_dirs.append(os.path.join(plugin_dir, "img"))
        if fallback_img_dir and fallback_img_dir not in self.img_dirs:
            self.img_dirs.append(fallback_img_dir)

        # 确保默认存储目录存在（只对可写路径执行）
        for d in self.img_dirs:
            try:
                os.makedirs(d, exist_ok=True)
            except (OSError, PermissionError):
                # 可能是只读或外部挂载，忽略创建错误
                pass
        
        # 获取图片格式配置，默认为常见格式
        self.image_formats = self.config.get("image_formats", [".png", ".jpg", ".jpeg", ".gif", ".bmp"])

        # 文件路径
        self.files = {
            "idols": os.path.join(self.data_dir, "idols.json"),         # 小偶像名单、昵称、简介、应援口号
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
        """通过昵称查找真名，并对微博常见前缀做兜底匹配"""
        idols = self.data.get("idols", {})
        if name_or_nick in idols:
            return name_or_nick
        for name, info in idols.items():
            if name_or_nick in info.get("nicknames", []):
                return name
        # 兜底：去掉可能的团队前缀（如 "gnz48-刘欣媛" -> "刘欣媛"）
        if "-" in name_or_nick:
            stripped = name_or_nick.split("-")[-1].strip()
            if stripped in idols:
                return stripped
            for name, info in idols.items():
                if stripped in info.get("nicknames", []):
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
                "info": "这个人很神秘，目前还没有公开资料，等待管理员补充。",
                "catchphrases": {}  # 应援口号：{"触发句": "响应内容"}
            }
            self.save("idols")
            # 自动创建图片文件夹（在可写的目录中创建，优先使用备用目录）
            for img_dir in reversed(self.img_dirs):  # 从后往前，优先在备用目录创建
                try:
                    folder_path = os.path.join(img_dir, name, "img", "原创微博图片文件夹")
                    os.makedirs(folder_path, exist_ok=True)
                    break  # 成功创建一个即可
                except (OSError, PermissionError):
                    continue  # 如果无法创建，尝试下一个目录

    def get_random_idol(self):
        """随机获取一个已注册的小偶像名字"""
        idols = list(self.data.get("idols", {}).keys())
        return random.choice(idols) if idols else None

    # --- 图片相关 ---

    def get_random_image_path(self, idol_name):
        """
        从图片目录中随机获取一张图片路径。
        仅使用"真名/昵称"目录，并在其中查找 <name>/img/原创微博图片文件夹/。
        如果偶像不在系统中，也会尝试用原始名字查找图片目录。
        """
        idols = self.data.get("idols", {})
        # 获取昵称列表（如果偶像在系统中）
        nicknames = idols.get(idol_name, {}).get("nicknames", [])

        # 以真名 + 昵称列表作为目录名候选
        seen = set()
        folder_names = []
        for name in [idol_name] + nicknames:
            if name and name not in seen:
                seen.add(name)
                folder_names.append(name)
        
        # 如果偶像不在系统中，尝试去掉前缀后的名字（如 "gnz48-刘欣媛" -> "刘欣媛"）
        if idol_name not in idols and "-" in idol_name:
            stripped = idol_name.split("-")[-1].strip()
            if stripped and stripped not in seen:
                folder_names.append(stripped)

        # 遍历主/辅图片根目录，在其中查找 <name>/img/原创微博图片文件夹/
        for root_dir in self.img_dirs:
            for name in folder_names:
                folder_path = os.path.join(root_dir, name, "img", "原创微博图片文件夹")
                if not os.path.exists(folder_path):
                    continue
                try:
                    images = [
                        f for f in os.listdir(folder_path)
                        if any(f.lower().endswith(fmt.lower()) for fmt in self.image_formats)
                    ]
                    if images:
                        return os.path.join(folder_path, random.choice(images))
                except (OSError, PermissionError) as e:
                    logging.error(f"访问图片目录 {folder_path} 失败: {e}")
                    continue
        return None