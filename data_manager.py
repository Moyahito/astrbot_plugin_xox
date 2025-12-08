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
        优先使用爬虫目录：从配置的 image_base_dir 回退到 apps 目录，找到 weibo-crawler-master/weibo，
        遍历该目录下的所有文件夹，匹配包含小偶像名字的目录。
        如果找不到，回退到默认 plugin_data 目录。
        """
        idols = self.data.get("idols", {})
        # 获取昵称列表（如果偶像在系统中）
        nicknames = idols.get(idol_name, {}).get("nicknames", [])
        
        # 构建匹配关键词列表：真名 + 昵称
        match_keywords = [idol_name] + nicknames
        # 如果名字包含前缀（如 "gnz48-刘欣媛"），也添加去掉前缀后的名字
        if "-" in idol_name:
            stripped = idol_name.split("-")[-1].strip()
            if stripped and stripped not in match_keywords:
                match_keywords.append(stripped)
        
        # 方法1：优先尝试爬虫目录（智能匹配）
        if self.img_dirs and len(self.img_dirs) > 0:
            crawler_root = self.img_dirs[0]  # 第一个是配置的爬虫目录
            logging.info(f"🔍 尝试爬虫目录，起始路径: {crawler_root}, 偶像: {idol_name}, 关键词: {match_keywords}")
            if crawler_root and os.path.exists(crawler_root):
                # 尝试回退到 apps 目录，找到 weibo-crawler-master/weibo
                crawler_path = self._find_crawler_weibo_dir(crawler_root)
                if crawler_path:
                    logging.info(f"✅ 找到爬虫 weibo 目录: {crawler_path}")
                    # 遍历爬虫目录下的所有文件夹，匹配包含关键词的目录
                    matched_folder = self._match_idol_folder(crawler_path, match_keywords)
                    if matched_folder:
                        logging.info(f"✅ 匹配到偶像文件夹: {matched_folder}")
                        # 尝试图片子目录格式（优先使用 img/原创微博图片）
                        img_subdirs = [
                            os.path.join(matched_folder, "img", "原创微博图片"),  # 优先：爬虫标准格式
                            os.path.join(matched_folder, "img", "原创微博图片文件夹"),  # 备用格式
                        ]
                        for img_dir in img_subdirs:
                            logging.info(f"🔍 尝试图片目录: {img_dir}, 存在: {os.path.exists(img_dir)}, 是目录: {os.path.isdir(img_dir) if os.path.exists(img_dir) else False}")
                            if os.path.exists(img_dir) and os.path.isdir(img_dir):
                                image_path = self._get_random_image_from_dir(img_dir)
                                if image_path:
                                    logging.info(f"✅ 从爬虫目录找到图片: {image_path}")
                                    return image_path
                                else:
                                    logging.warning(f"⚠️ 图片目录存在但无图片文件: {img_dir}")
                    else:
                        logging.warning(f"⚠️ 未在爬虫目录中找到匹配的文件夹，关键词: {match_keywords}, weibo目录: {crawler_path}")
                else:
                    logging.warning(f"⚠️ 未找到爬虫 weibo 目录，起始路径: {crawler_root}")
            else:
                logging.warning(f"⚠️ 爬虫根目录不存在: {crawler_root}")
        
        # 方法2：回退到默认目录（使用原来的逻辑）
        logging.info(f"🔍 回退到默认目录查找，根目录列表: {self.img_dirs}")
        # 定义多种路径格式（按优先级排序）
        path_patterns = [
            ("img", "原创微博图片"),  # 爬虫格式
        ]
        
        # 遍历所有图片根目录（包括备用目录）
        for root_dir in self.img_dirs:
            logging.info(f"🔍 检查根目录: {root_dir}")
            for keyword in match_keywords:
                for pattern in path_patterns:
                    if len(pattern) == 2:
                        folder_path = os.path.join(root_dir, keyword, pattern[0], pattern[1])
                    elif len(pattern) == 1:
                        folder_path = os.path.join(root_dir, keyword, pattern[0]) if pattern[0] else os.path.join(root_dir, keyword)
                    else:
                        continue
                    
                    logging.info(f"🔍 尝试路径: {folder_path}, 存在: {os.path.exists(folder_path)}, 是目录: {os.path.isdir(folder_path) if os.path.exists(folder_path) else False}")
                    if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
                        continue
                    
                    image_path = self._get_random_image_from_dir(folder_path)
                    if image_path:
                        logging.info(f"✅ 从默认目录找到图片: {image_path}")
                        return image_path
                    else:
                        logging.warning(f"⚠️ 路径存在但无图片文件: {folder_path}")
        
        logging.warning(f"❌ 未找到 {idol_name} 的图片，匹配关键词: {match_keywords}, 根目录: {self.img_dirs}")
        return None
    
    def _find_crawler_weibo_dir(self, start_path):
        """
        从给定路径回退到 apps 目录，找到 weibo-crawler-master/weibo 目录
        如果 start_path 本身已经是 weibo 目录，直接返回
        """
        if not start_path or not os.path.exists(start_path):
            return None
        
        current = os.path.abspath(start_path)
        
        # 先检查当前路径本身是否是 weibo 目录（路径名以 weibo 结尾）
        if os.path.basename(current) == "weibo" and os.path.isdir(current):
            logging.debug(f"当前路径就是 weibo 目录: {current}")
            return current
        
        # 检查当前路径是否是 weibo-crawler-master/weibo
        if os.path.basename(os.path.dirname(current)) == "weibo-crawler-master" and os.path.basename(current) == "weibo":
            logging.debug(f"当前路径就是 weibo-crawler-master/weibo: {current}")
            return current
        
        max_levels = 10  # 最多回退10级，防止无限循环
        
        for _ in range(max_levels):
            # 检查当前目录下是否有 weibo-crawler-master/weibo
            weibo_path = os.path.join(current, "weibo-crawler-master", "weibo")
            if os.path.exists(weibo_path) and os.path.isdir(weibo_path):
                logging.debug(f"找到爬虫目录: {weibo_path}")
                return weibo_path
            
            # 检查当前目录是否是 apps 目录
            if os.path.basename(current) == "apps":
                weibo_path = os.path.join(current, "weibo-crawler-master", "weibo")
                if os.path.exists(weibo_path) and os.path.isdir(weibo_path):
                    logging.debug(f"找到爬虫目录: {weibo_path}")
                    return weibo_path
            
            # 回退一级
            parent = os.path.dirname(current)
            if parent == current:  # 已经到根目录了
                break
            current = parent
        
        return None
    
    def _match_idol_folder(self, weibo_dir, keywords):
        """
        在爬虫目录下查找包含关键词的文件夹
        """
        if not os.path.exists(weibo_dir) or not os.path.isdir(weibo_dir):
            logging.warning(f"⚠️ weibo目录不存在或不是目录: {weibo_dir}")
            return None
        
        try:
            all_folders = []
            for folder_name in os.listdir(weibo_dir):
                folder_path = os.path.join(weibo_dir, folder_name)
                if os.path.isdir(folder_path):
                    all_folders.append(folder_name)
                    # 检查文件夹名是否包含任何一个关键词
                    for keyword in keywords:
                        if keyword and keyword in folder_name:
                            logging.info(f"✅ 匹配到文件夹: {folder_path} (关键词: {keyword})")
                            return folder_path
            
            logging.warning(f"⚠️ 未找到匹配文件夹，关键词: {keywords}, 可用文件夹: {all_folders[:10]}")  # 只显示前10个
        except (OSError, PermissionError) as e:
            logging.error(f"❌ 遍历爬虫目录失败: {e}")
        
        return None
    
    def _get_random_image_from_dir(self, img_dir):
        """
        从指定目录中随机获取一张图片
        """
        if not os.path.exists(img_dir) or not os.path.isdir(img_dir):
            return None
        
        try:
            images = [
                f for f in os.listdir(img_dir)
                if os.path.isfile(os.path.join(img_dir, f)) and
                any(f.lower().endswith(fmt.lower()) for fmt in self.image_formats)
            ]
            if images:
                return os.path.join(img_dir, random.choice(images))
        except (OSError, PermissionError) as e:
            logging.error(f"读取图片目录失败 {img_dir}: {e}")
        
        return None