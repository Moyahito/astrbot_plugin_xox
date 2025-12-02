"""
idol Bot 插件 - 偶像互动与签到系统

功能：
- 每日签到领取专属"宝宝"
- 应援口号触发回复
- 偶像信息查询与管理
- 管理员权限控制

数据存储：
- 所有持久化数据存储在 data 目录下，防止更新插件时数据丢失
- 图片资源存储在 plugin_data 目录下
"""
import os
import datetime
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
import astrbot.api.message_components as Comp
from astrbot.api import logger
from .data_manager import DataManager

class SixSixBot(Star):
    """idol Bot 插件主类"""
    
    def __init__(self, context: Context, config=None, **kwargs):
        """
        初始化插件
        
        Args:
            context: AstrBot 提供的上下文对象，包含配置等信息
        """
        super().__init__(context, config=config, **kwargs)
        self.plugin_dir = os.path.dirname(__file__)
        # 计算 plugin_data 目录路径：从 plugin 目录向上两级到 data，然后进入 plugin_data，再进入同名文件夹
        plugin_name = os.path.basename(self.plugin_dir)
        data_dir = os.path.dirname(os.path.dirname(self.plugin_dir))  # 向上两级到 data 目录
        self.plugin_data_dir = os.path.join(data_dir, "plugin_data", plugin_name)
        # 读取配置（从 _conf_schema.json 解析的配置）
        # 新版 AstrBot 会在实例化时通过 config 参数传入配置
        self.config = config or {}
        # 初始化数据管理器（数据存储在 data 目录下，防止更新插件时丢失）
        self.db = DataManager(self.plugin_dir, self.plugin_data_dir, self.config)

    async def initialize(self):
        logger.info("idol bot 插件初始化完成。")

    # ================= 核心消息监听 (用于处理口号触发) =================
    
    @filter.event_message_type("GROUP_MESSAGE")
    async def passive_catchphrase_handler(self, event: AstrMessageEvent):
        """检查非指令消息中是否包含应援口号触发句"""
        # 检查是否启用口号触发功能
        if not self.config.get("enable_catchphrase", True):
            return
            
        msg_str = event.message_str.strip()
        
        if msg_str.startswith("/"):
            return

        triggers = self.db.data.get("catchphrases", {})
        
        for trigger_txt, data in triggers.items():
            if trigger_txt in msg_str:
                user_id = event.get_sender_id()
                idol_name = data.get("idol")
                response_txt = data.get("resp", "")
                
                if not idol_name:
                    continue
                
                img_path = self.db.get_random_image_path(idol_name)
                
                chain = [
                    Comp.At(qq=user_id),
                    Comp.Plain(f"\n{response_txt}")
                ]
                
                if img_path and os.path.exists(img_path):
                    chain.append(Comp.Image.fromFileSystem(img_path))
                else:
                    no_image_msg = self.config.get("default_messages", {}).get("no_image", "暂时还没有解锁这位小偶像哦。")
                    chain.append(Comp.Plain(f"\n{no_image_msg}"))

                yield event.chain_result(chain)
                return 

    # ================= 签到系统 =================
    
    @filter.command("qd")
    async def cmd_checkin(self, event: AstrMessageEvent):
        """签到领取今天的宝宝"""
        user_id = str(event.get_sender_id())
        user_name = event.get_sender_name()
        today = datetime.date.today().isoformat()
        
        user_record = self.db.data.get("users", {}).get(user_id, {})
        if user_record.get("last_checkin") == today:
            already_msg = self.config.get("default_messages", {}).get("already_checkin", "你今天已经签到过了哦~")
            chain = [
                Comp.At(qq=user_id),
                Comp.Plain(f"\n{already_msg}")
            ]
            yield event.chain_result(chain)
            return

        lucky_idol = self.db.get_random_idol()
        if not lucky_idol:
            no_idol_msg = self.config.get("default_messages", {}).get("no_idol", "还没有添加任何小偶像，无法签到！请先用 /add 添加。")
            yield event.plain_result(no_idol_msg)
            return

        img_path = self.db.get_random_image_path(lucky_idol)
        
        self.db.data.setdefault("users", {})[user_id] = {"last_checkin": today}
        self.db.save("users")

        text_lines = [
            "签到成功！",
            f"今天你的宝宝是：{lucky_idol}"
        ]
        
        chain = [
            Comp.At(qq=user_id),
            Comp.Plain(f"\n{text_lines[0]}\n{text_lines[1]}")
        ]
        
        if img_path and os.path.exists(img_path):
            chain.append(Comp.Image.fromFileSystem(img_path))
        else:
            no_image_msg = self.config.get("default_messages", {}).get("no_image", "暂时还没有解锁这位小偶像哦。")
            chain.append(Comp.Plain(f"\n{no_image_msg}"))

        yield event.chain_result(chain)

    # ================= 小偶像信息查询与管理 =================
    
    @filter.command("xox")
    async def cmd_idol_info(self, event: AstrMessageEvent):
        """/xox <姓名或昵称> - 查询小偶像信息"""
        args = event.message_str.split()[1:]
        if not args:
            yield event.plain_result("格式：/xox <姓名或昵称>")
            return
            
        target = args[0].strip()
        if not target:
            yield event.plain_result("请输入要查询的姓名或昵称。")
            return
            
        real_name = self.db.get_real_name(target)
        
        if not real_name:
            yield event.plain_result(f"未找到关于 '{target}' 的信息。")
            return
            
        # XOX档案格式化
        info = self.db.data.get("idols", {}).get(real_name, {})
        nicks = info.get("nicknames", [])
        idol_info = info.get("info", "这个人很神秘，目前还没有公开资料，等待管理员补充。")
        
        msg = (
            f"🌟 {real_name} 档案 🌟\n"
            "-------------------------\n"
            f"昵称：{', '.join(nicks) if nicks else '无'}\n"
            f"简介：{idol_info}\n"
            "-------------------------"
        )
            
        yield event.plain_result(msg)


    @filter.command("add")
    async def cmd_add(self, event: AstrMessageEvent):
        """/add <姓名> <昵称> 或 /add catchphrase -i -t -r"""
        msg_parts = event.message_str.split()
        if len(msg_parts) > 1 and msg_parts[1].lower() == "catchphrase":
            # 处理 /add catchphrase ...
            args = msg_parts[2:]
            async for result in self._add_catchphrase_logic(event, args):
                yield result
        else:
            # 处理 /add <姓名> <昵称>
            args = msg_parts[1:]
            async for result in self._add_nickname_logic(event, args):
                yield result

    async def _add_nickname_logic(self, event: AstrMessageEvent, args):
        """/add <姓名> <昵称> 的内部实现"""
        if len(args) < 2:
            yield event.plain_result("格式：/add <姓名> <昵称>")
            return
            
        real_name = args[0].strip()
        nickname = args[1].strip()
        
        if not real_name or not nickname:
            yield event.plain_result("姓名和昵称不能为空。")
            return
        
        self.db.add_idol(real_name)  # 注册偶像并创建文件夹
        
        # add_idol 已经创建了记录，直接访问即可
        idols = self.db.data.get("idols", {})
        if real_name not in idols:
            # 如果 add_idol 失败，确保记录存在
            idols[real_name] = {"nicknames": [], "info": "这个人很神秘，目前还没有公开资料，等待管理员补充。"}
        
        nicknames = idols[real_name].get("nicknames", [])
        if nickname not in nicknames:
            nicknames.append(nickname)
            self.db.save("idols")
            yield event.plain_result(f"已为 {real_name} 添加昵称：{nickname}")
        else:
            yield event.plain_result(f"{nickname} 已经是 {real_name} 的昵称了。")

    async def _add_catchphrase_logic(self, event: AstrMessageEvent, args):
        """/add catchphrase -i <name> -t <trigger> -r <response> 的内部实现"""
        
        params = {"-i": "", "-t": "", "-r": ""}
        current_flag = None
        
        for word in args:
            if word in params:
                current_flag = word
            elif current_flag is not None:
                params[current_flag] += word + " "
        
        idol_input = params["-i"].strip()
        trigger = params["-t"].strip()
        resp = params["-r"].strip()

        if not idol_input or not trigger or not resp:
            yield event.plain_result("格式错误，请使用：/add catchphrase -i <姓名> -t <触发句> -r <响应句>")
            return

        real_name = self.db.get_real_name(idol_input)
        if not real_name:
            yield event.plain_result(f"找不到偶像 {idol_input}，请先使用 /add 注册。")
            return

        self.db.data.setdefault("catchphrases", {})[trigger] = {
            "idol": real_name,
            "resp": resp
        }
        self.db.save("catchphrases")
        
        yield event.plain_result(f"添加成功！\n触发：{trigger}\n回复：{resp}\n关联偶像：{real_name}")

    # ================= 列表查询 =================

    @filter.command("list")
    async def cmd_list(self, event: AstrMessageEvent):
        """/list <姓名> 或 /list catchphrase"""
        args = event.message_str.split()[1:]

        if len(args) > 0 and args[0].lower() == "catchphrase":
            async for result in self._list_catchphrase_logic(event):
                yield result
            return

        if not args:
            yield event.plain_result("格式：/list <姓名> (列出昵称) 或 /list catchphrase (列出口号)")
            return
            
        target = args[0].strip()
        if not target:
            yield event.plain_result("请输入要查询的姓名。")
            return
            
        real_name = self.db.get_real_name(target)
        if not real_name:
             yield event.plain_result("未找到该偶像。")
             return
             
        nicks = self.db.data.get("idols", {}).get(real_name, {}).get("nicknames", [])
        yield event.plain_result(f"{real_name} 的昵称：{', '.join(nicks)}")
        
    async def _list_catchphrase_logic(self, event: AstrMessageEvent):
        """/list catchphrase 的内部实现"""
        cps = self.db.data.get("catchphrases", {})
        if not cps:
            yield event.plain_result("暂时没有应援口号。")
            return
        
        msg = "📜 应援口号列表：\n"
        for trig, data in cps.items():
            idol = data.get("idol", "未知")
            msg += f"• '{trig}' -> {idol}\n"
        yield event.plain_result(msg)

    # ================= 管理命令 =================

    def _is_admin(self, user_id):
        """检查用户是否为管理员"""
        return str(user_id) in self.db.data.get("admins", [])

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("auth")
    async def cmd_auth(self, event: AstrMessageEvent):
        """/auth <QQ ID> - 添加授权用户"""
        user_id = str(event.get_sender_id())
        args = event.message_str.split()[1:]

        if not args:
            yield event.plain_result("格式：/auth <QQ ID>")
            return

        target_id = args[0].strip()
        if not target_id:
            yield event.plain_result("QQ ID 不能为空。")
            return
            
        admins = self.db.data.setdefault("admins", [])
        if target_id not in admins:
            admins.append(target_id)
            self.db.save("admins")
            yield event.plain_result(f"已授权用户：{target_id}")
        else:
            yield event.plain_result(f"用户 {target_id} 已经是管理员了。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("rauth")
    async def cmd_rauth(self, event: AstrMessageEvent):
        """/rauth <QQ ID> - 移除授权用户"""
        user_id = str(event.get_sender_id())
        args = event.message_str.split()[1:]

        if not args:
            yield event.plain_result("格式：/rauth <QQ ID>")
            return

        target_id = args[0].strip()
        if not target_id:
            yield event.plain_result("QQ ID 不能为空。")
            return
            
        admins = self.db.data.get("admins", [])
        if target_id in admins:
            admins.remove(target_id)
            self.db.save("admins")
            yield event.plain_result(f"已移除授权用户：{target_id}")
        else:
            yield event.plain_result(f"用户 {target_id} 不是管理员。")
            
    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("group")
    async def cmd_group_manage(self, event: AstrMessageEvent):
        """群组管理命令占位"""
        yield event.plain_result("群组管理功能已识别。请根据具体需求实现子命令逻辑（add/update/info/list）。")

    # ================= 基础帮助 =================
    
    @filter.command("help")
    async def cmd_help(self, event: AstrMessageEvent):
        """显示此帮助信息"""
        help_text = (
            "🤖 idol Bot  命令列表：\n"
            "----------------------------\n"
            "1. 互动与查询：\n"
            "/qd - 每日签到，领取今日宝宝\n"
            "/xox <名字/昵称> - 查询小偶像档案\n"
            "   (触发口号可回复对应图片)\n"
            "2. 数据管理：\n"
            "/add <姓名> <昵称> - 添加昵称\n"
            "/add catchphrase -i <名> -t <触发> -r <响应> - 添加口号\n"
            "/list <姓名> - 列出偶像昵称\n"
            "/list catchphrase - 列出所有口号\n"
            "3. 管理员命令 (仅限授权用户)：\n"
            "/auth <QQ ID> - 添加授权用户\n"
            "/rauth <QQ ID> - 移除授权用户\n"
            "/group <sub_cmd> - 群组管理\n"
        )
        yield event.plain_result(help_text)

    async def terminate(self):
        logger.info("idol bot 插件已销毁。")
