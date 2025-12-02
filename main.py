"""
SixSixBot 插件 - 偶像互动与签到系统

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
import random
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
import astrbot.api.message_components as Comp
from astrbot.api import logger
from .data_manager import DataManager

class SixSixBot(Star):
    """SixSixBot 插件主类"""
    
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
        logger.info("SixSixBot 插件初始化完成。")
    
    def _build_reply_chain(self, event: AstrMessageEvent, user_id: str, text: str, img_path: str = None):
        """
        构建回复消息链：引用原消息 + @用户 + 换行 + 文字 + 图片
        
        Args:
            event: 消息事件对象
            user_id: 要@的用户ID
            text: 回复文字内容
            img_path: 图片路径（可选）
        
        Returns:
            消息链列表
        """
        chain = []
        
        # 尝试添加引用（Reply组件）
        try:
            if hasattr(event, 'message_obj') and hasattr(event.message_obj, 'message_id'):
                # 尝试导入Reply组件
                try:
                    Reply = getattr(Comp, 'Reply', None)
                    if Reply:
                        chain.append(Reply(message_id=event.message_obj.message_id))
                except:
                    pass
        except:
            pass
        
        # @用户
        chain.append(Comp.At(qq=user_id))
        # 换行 + 文字
        chain.append(Comp.Plain(f"\n{text}"))
        
        # 添加图片或提示
        if img_path and os.path.exists(img_path):
            chain.append(Comp.Image.fromFileSystem(img_path))
        else:
            no_image_msg = self.config.get("default_messages", {}).get("no_image", "暂时还没有解锁这位小偶像哦。")
            chain.append(Comp.Plain(f"\n{no_image_msg}"))
        
        return chain

    # ================= 核心消息监听 (用于处理口号触发) =================
    
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def passive_catchphrase_handler(self, event: AstrMessageEvent, *args, **kwargs):
        """检查非指令消息中是否包含应援口号触发句"""
        # 检查是否启用口号触发功能
        if not self.config.get("enable_catchphrase", True):
            return
        
        # 跳过指令消息（以 / 开头）
        msg_str = event.message_str.strip()
        if msg_str.startswith("/"):
            return

        user_id = str(event.get_sender_id())
        today = datetime.date.today().isoformat()
        user_record = self.db.data.get("users", {}).get(user_id, {})
        today_idol = user_record.get("today_idol") if user_record.get("last_checkin") == today else None

        # 处理"好想宝宝"的特殊情况（优先匹配，避免被"好想XXX"逻辑匹配）
        # 支持多种表达：好想宝宝、想宝宝、好想 宝宝、想 宝宝 等
        msg_normalized = msg_str.replace(" ", "").replace("，", "").replace(",", "")
        if "好想宝宝" in msg_normalized or "想宝宝" in msg_normalized:
            if today_idol:
                # 生成思念回复模板（5个随机选择）
                miss_templates = [
                    f"{today_idol}正在数着星星，每一颗都是对你的思念~！",
                    f"{today_idol}在月光下许愿，希望你能感受到她的想念~",
                    f"{today_idol}对着夜空轻声说：好想你呀，每一秒都在想你~",
                    f"{today_idol}在梦里遇见了你，醒来后更加思念~",
                    f"{today_idol}把对你的思念写成了诗，每一句都是爱意~"
                ]
                response_txt = random.choice(miss_templates)
                img_path = self.db.get_random_image_path(today_idol)
                chain = self._build_reply_chain(event, user_id, response_txt, img_path)
                yield event.chain_result(chain)
                return
            else:
                # 用户今天还没签到，提示先签到
                chain = self._build_reply_chain(event, user_id, "你还没有签到呢~先使用 /qd 签到领取今天的宝宝吧！")
                yield event.chain_result(chain)
                return

        # 处理"好想XXX"的情况（XXX不是"宝宝"）
        if (msg_str.startswith("好想") or msg_str.startswith("想")) and "宝宝" not in msg_str:
            # 提取想的人名
            target_name = msg_str.replace("好想", "").replace("想", "").strip()
            if target_name:
                # 检查目标名字是否存在于系统中（支持真实姓名和昵称）
                real_name = self.db.get_real_name(target_name)
                
                if real_name:
                    # 检查这个XXX是否今天已经被其他用户签到过
                    users_data = self.db.data.get("users", {})
                    today = datetime.date.today().isoformat()
                    is_taken_by_others = False
                    
                    # 遍历所有用户，检查是否有其他用户今天签到了这个XXX
                    for uid, user_record in users_data.items():
                        if uid != user_id:  # 排除当前用户
                            if user_record.get("last_checkin") == today:
                                if user_record.get("today_idol") == real_name:
                                    is_taken_by_others = True
                                    break
                    
                    # 如果XXX已经被其他用户签到过
                    if is_taken_by_others:
                        if today_idol:
                            # 用户今天已签到，提示关心自己的宝宝
                            response_txt = f"这不是你的宝宝哦，这是别人的宝宝。请多多关心{today_idol}吧！"
                            img_path = self.db.get_random_image_path(today_idol)
                            chain = self._build_reply_chain(event, user_id, response_txt, img_path)
                            yield event.chain_result(chain)
                            return
                        else:
                            # 用户今天还没签到，提示先签到
                            chain = self._build_reply_chain(event, user_id, "这不是你的宝宝哦，这是别人的宝宝。先使用 /qd 签到领取今天的宝宝吧！")
                            yield event.chain_result(chain)
                            return
                    # 如果XXX没有被任何人签到过，继续正常的应援口号处理流程（不return，让代码继续执行）
                # 如果找不到这个XXX，也继续正常的应援口号处理流程

        # 遍历所有偶像的应援口号
        idols = self.db.data.get("idols", {})
        catchphrase_matched = False
        for idol_name, idol_data in idols.items():
            catchphrases = idol_data.get("catchphrases", {})
            for trigger_txt, response_txt in catchphrases.items():
                if trigger_txt in msg_str:
                    catchphrase_matched = True
                    img_path = self.db.get_random_image_path(idol_name)
                    chain = self._build_reply_chain(event, user_id, response_txt, img_path)
                    yield event.chain_result(chain)
                    return
        
        # 如果"好想XXX"但没有匹配到应援口号，且XXX没有被签到过，提供默认回复
        if (msg_str.startswith("好想") or msg_str.startswith("想")) and "宝宝" not in msg_str and not catchphrase_matched:
            target_name = msg_str.replace("好想", "").replace("想", "").strip()
            if target_name:
                real_name = self.db.get_real_name(target_name)
                if real_name:
                    # 检查是否被签到过
                    users_data = self.db.data.get("users", {})
                    today = datetime.date.today().isoformat()
                    is_taken = False
                    for uid, user_record in users_data.items():
                        if user_record.get("last_checkin") == today:
                            if user_record.get("today_idol") == real_name:
                                is_taken = True
                                break
                    
                    # 如果没有被签到过，提供默认回复
                    if not is_taken:
                        miss_templates = [
                            f"{real_name}也很想你~",
                            f"{real_name}感受到了你的思念，也在想你哦~",
                            f"{real_name}听到你的呼唤，心里暖暖的~",
                            f"{real_name}也想和你见面呢~"
                        ]
                        response_txt = random.choice(miss_templates)
                        img_path = self.db.get_random_image_path(real_name)
                        chain = self._build_reply_chain(event, user_id, response_txt, img_path)
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
            # 重复签到：显示今天已分配的xox和图片
            today_idol = user_record.get("today_idol")
            if today_idol:
                already_msg = self.config.get("default_messages", {}).get("already_checkin", "你今天已经签到过了哦~")
                response_txt = f"{already_msg}\n你的宝宝是：{today_idol}"
                img_path = self.db.get_random_image_path(today_idol)
                chain = self._build_reply_chain(event, user_id, response_txt, img_path)
                yield event.chain_result(chain)
            else:
                # 如果没有保存今天分配的xox（可能是旧数据），只显示文字
                already_msg = self.config.get("default_messages", {}).get("already_checkin", "你今天已经签到过了哦~")
                chain = self._build_reply_chain(event, user_id, already_msg)
                yield event.chain_result(chain)
            return

        lucky_idol = self.db.get_random_idol()
        if not lucky_idol:
            no_idol_msg = self.config.get("default_messages", {}).get("no_idol", "还没有添加任何小偶像，无法签到！请先用 /add 添加。")
            yield event.plain_result(no_idol_msg)
            return

        img_path = self.db.get_random_image_path(lucky_idol)
        
        # 保存签到记录，包括今天分配的xox
        self.db.data.setdefault("users", {})[user_id] = {
            "last_checkin": today,
            "today_idol": lucky_idol
        }
        self.db.save("users")

        response_txt = f"签到成功！\n今天你的宝宝是：{lucky_idol}"
        chain = self._build_reply_chain(event, user_id, response_txt, img_path)
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
            idols[real_name] = {
                "nicknames": [],
                "info": "这个人很神秘，目前还没有公开资料，等待管理员补充。",
                "catchphrases": {}
            }
        
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

        # 确保偶像记录存在
        self.db.add_idol(real_name)
        idols = self.db.data.get("idols", {})
        if real_name not in idols:
            idols[real_name] = {
                "nicknames": [],
                "info": "这个人很神秘，目前还没有公开资料，等待管理员补充。",
                "catchphrases": {}
            }
        
        # 添加应援口号到对应偶像的 catchphrases 中
        idols[real_name].setdefault("catchphrases", {})[trigger] = resp
        self.db.save("idols")
        
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
        idols = self.db.data.get("idols", {})
        all_catchphrases = {}
        for idol_name, idol_data in idols.items():
            catchphrases = idol_data.get("catchphrases", {})
            for trigger, response in catchphrases.items():
                all_catchphrases[trigger] = {"idol": idol_name, "resp": response}
        
        if not all_catchphrases:
            yield event.plain_result("暂时没有应援口号。")
            return
        
        msg = "📜 应援口号列表：\n"
        for trig, data in all_catchphrases.items():
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
    @filter.command("reset_today")
    async def cmd_reset_today(self, event: AstrMessageEvent):
        """/reset_today - 重置今天所有用户的签到记录（仅管理员）"""
        today = datetime.date.today().isoformat()
        users_data = self.db.data.get("users", {})
        
        # 统计今天签到的用户数量，并收集需要删除的用户ID
        reset_count = 0
        users_to_delete = []
        
        # 先遍历收集需要处理的数据
        for user_id, user_record in users_data.items():
            if user_record.get("last_checkin") == today:
                reset_count += 1
                # 清除今天的签到记录
                user_record.pop("last_checkin", None)
                user_record.pop("today_idol", None)
                # 如果用户记录为空，标记为需要删除
                if not user_record:
                    users_to_delete.append(user_id)
        
        # 遍历完成后再删除空记录
        for user_id in users_to_delete:
            users_data.pop(user_id, None)
        
        # 保存数据
        self.db.save("users")
        
        if reset_count > 0:
            yield event.plain_result(f"✅ 已重置今天所有签到记录！\n共清除了 {reset_count} 位用户的签到记录。")
        else:
            yield event.plain_result("ℹ️ 今天还没有用户签到，无需重置。")
            
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
            "🤖 SixSixBot  命令列表：\n"
            "----------------------------\n"
            "1. 互动与查询：\n"
            "/qd - 每日签到，领取今日宝宝\n"
            "   重复签到会显示今天已分配的宝宝和图片\n"
            "/xox <名字/昵称> - 查询小偶像档案\n"
            "2. 专属互动（无需命令）：\n"
            "好想宝宝 - 对今天签到的宝宝说思念，会收到随机回复和图片\n"
            "好想XXX - 如果想其他人，会提示关心今天的宝宝\n"
            "3. 应援口号：\n"
            "在群聊中说出设置的口号，会触发对应回复和图片\n"
            "4. 数据管理：\n"
            "/add <姓名> <昵称> - 添加昵称\n"
            "/add catchphrase -i <名> -t <触发> -r <响应> - 添加口号\n"
            "/list <姓名> - 列出偶像昵称\n"
            "/list catchphrase - 列出所有口号\n"
            "5. 管理员命令 (仅限授权用户)：\n"
            "/auth <QQ ID> - 添加授权用户\n"
            "/rauth <QQ ID> - 移除授权用户\n"
            "/reset_today - 重置今天所有用户的签到记录\n"
            "/group <sub_cmd> - 群组管理\n"
        )
        yield event.plain_result(help_text)

    async def terminate(self):
        logger.info("SixSixBot 插件已销毁。")