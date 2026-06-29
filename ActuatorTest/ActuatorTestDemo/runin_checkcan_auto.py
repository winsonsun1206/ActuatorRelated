import pika
import json
import time
import can
import pickle
import threading
from utils.station_conf import read_station_conf
from utils.redis_handler import RedisHandler
from utils.send_data import send_heartbeat  # 复用系统自带的心跳函数

class CanConnectivityService:
    def __init__(self, server_ip='192.168.2.47', port=5672):
        # 1. 动态读取本地配置中的测试机台名称 (例如：rivr_test2)
        self.station_name = read_station_conf().get("station_name", "unknown_station").strip()
        
        # 2. 严格绑定魏工指定的中央 RabbitMQ 和 Redis 服务器 IP
        self.credentials = pika.PlainCredentials('admin', 'ni50509800')
        self.server_ip = server_ip
        self.port = port
        
        # 显式让 Redis 连向中央服务器 192.168.2.47 的 0号库
        self.redis_handler = RedisHandler(host=server_ip, port=6379, db=0)
        
        # 用于管理异步心跳线程的控制字典，防止重复叠加
        self.heartbeat_managers = {
            "can0": {"event": None, "thread": None},
            "can1": {"event": None, "thread": None}
        }

    def start_service(self):
        # 严格连接至指定的中央消息总线 192.168.2.47
        connection = pika.BlockingConnection(pika.ConnectionParameters(
            host=self.server_ip, 
            port=self.port, 
            virtual_host='/', 
            credentials=self.credentials, 
            heartbeat=600
        ))
        channel = connection.channel()

        # 3. 魏工规范：动态为当前测试机绑定 can0 和 can1 两条专属检测队列
        for bus in ['can0', 'can1']:
            queue_name = f"canconnect_queue_{self.station_name}_can{bus}".strip()
            channel.queue_declare(queue=queue_name, durable=True)
            
            # 使用 lambda 动态向下游回调函数传导当前触发的是哪条总线通道 (can0 或 can1)
            channel.basic_consume(
                queue=queue_name, 
                on_message_callback=lambda ch, method, properties, body, b=bus: self.callback(ch, method, properties, body, b),
                auto_ack=False
            )

        print(f"[{self.station_name}] 网页集成 CheckCAN 专属自动化检测服务（含异步黑框联动）已成功启动！")
        print(f"目前正连接至 RabbitMQ 中央服务器 [{self.server_ip}:{self.port}]，等待网页端信号...")
        channel.start_consuming()

    def _run_heartbeat_loop(self, can_bus, target_ids, stop_event, task_id):
        """在后台死循环发送心跳的线程函数"""
        print(f"[{can_bus}] 后台心跳守护线程已开启，精准维持 ID 列表: {target_ids}")
        # 心跳保持期间，让下方的 Live Task Monitor 持续打印心跳激活日志
        hb_log_msg = f"[{can_bus}] 检测成功。心跳机制运行中，正在持续维持有效 ID: {target_ids} 的连接状态..."
        self.redis_handler.set_value(task_id, hb_log_msg)
        
        while not stop_event.is_set():
            try:
                # 调用系统原本的心跳发送函数
                send_heartbeat(can_bus, target_ids)
                # 每隔 1 秒发送一次
                time.sleep(1)
            except Exception as e:
                print(f"[{can_bus}] 发送心跳报文异常: {e}")
                time.sleep(1)
        print(f"[{can_bus}] 后台心跳守护线程已安全关闭。")

    def _stop_existing_heartbeat(self, can_bus):
        """安全停止某个通道现有的心跳线程，释放总线控制权并防止重复叠加"""
        manager = self.heartbeat_managers[can_bus]
        if manager["event"] is not None:
            print(f"[{can_bus}] 检测到正在运行的历史心跳，正在执行释放与清理...")
            manager["event"].set()  # 触发停止信号
            if manager["thread"] is not None:
                manager["thread"].join(timeout=2.0)  # 等待老心跳线程彻底结束
            manager["event"] = None
            manager["thread"] = None

    def callback(self, ch, method, properties, body, can_bus):
        # 收到消息立刻回复 ACK
        ch.basic_ack(delivery_tag=method.delivery_tag)
        
        try:
            # 兼容处理：原系统使用 pickle 序列化，魏工可能发标准 JSON
            try:
                task = json.loads(body.decode('utf-8'))
            except Exception:
                task = pickle.loads(body)

            task_name = task.get('task_name', '').strip()
            
            # 【核心修改】：精准匹配并提取网页黑框专用的 task_id 键名
            task_id = task.get('task_id', f'{self.station_name}_{can_bus}_check_task').strip()
            redis_key = f"{self.station_name}_{can_bus}_check_result".strip()
            
            # ============================== 任务 1：点击 CheckCAN ==============================
            if task_name == 'connectivity_checkcan':
                # 只要重新发起检测，先安全停掉当前通道的老心跳，防止通道冲突
                self._stop_existing_heartbeat(can_bus)

                # 黑框同步提示：正在开始检测
                self.redis_handler.set_value(task_id, f"正在自动检测 {can_bus} 通道连接状态，请稍候...")

                test_slots = task.get('parameters', {})
                
                # 【槽位判定】：只要对应的输入框里填了东西（不论是数字 1 还是序列号），就将其对应的 can_msg_id 提取出来
                expected_ids = [
                    int(slot['can_msg_id']) for slot in test_slots 
                    if str(slot.get('serial_number', '')).strip() != ""
                ]

                if not expected_ids:
                    err_msg = "未检测到任何输入的电机序列号，请至少在一个槽位输入数据再检测！"
                    self.redis_handler.set_value(redis_key, {"status": "error", "message": err_msg})
                    self.redis_handler.set_value(task_id, f"ERROR: {err_msg}")
                    return

                print(f"[{self.station_name} - {can_bus}] 收到网页端专属 CheckCAN 请求 -> 目标检测 ID 列表: {expected_ids}")
                
                # 开启 SocketCAN 物理通道做 5 秒高频抓包探测
                try:
                    can_bus_interface = can.interface.Bus(channel=can_bus, interface='socketcan')
                except Exception as e:
                    err_msg = f"底层无法开启物理通道 {can_bus}: {str(e)}"
                    self.redis_handler.set_value(redis_key, {"status": "error", "message": err_msg})
                    self.redis_handler.set_value(task_id, f"ERROR: {err_msg}")
                    return

                found_devices = set()
                start_time = time.time()
                while time.time() - start_time < 5.0:
                    msg = can_bus_interface.recv(timeout=0.3)
                    if msg is None:
                        continue
                    
                    # 复用系统的 256~512 到 1~256 映射逻辑
                    if msg.arbitration_id in range(256, 512):
                        can_bus_id = msg.arbitration_id - 256
                        if can_bus_id in expected_ids:
                            found_devices.add(can_bus_id)
                    
                    # 网页填了的槽位 ID 全部抓到了，提前闪人
                    if all(idx in found_devices for idx in expected_ids):
                        break
                
                # 显式关闭物理通道，释放总线
                can_bus_interface.shutdown()

                # 精准计算差集：找出哪些填了内容的槽位 ID 实际上没有回包
                missing_ids = [idx for idx in expected_ids if idx not in found_devices]

                if not missing_ids:
                    result_data = {
                        "status": "success",
                        "message": "can全识别到了继续下一步"
                    }
                    self.redis_handler.set_value(redis_key, result_data)
                    # 🌟 同步向黑框写入成功的文本提示！让黑框完美渲染出内容
                    self.redis_handler.set_value(task_id, "SUCCESS: can全识别到了继续下一步")
                    
                    print(f"[{can_bus}] 检测全通过！正在为有效 ID {expected_ids} 开启后台持续心跳守护...")
                    
                    # 识别全通过，为当前填写的有效 ID 启动独立线程常驻发送心跳报文
                    stop_event = threading.Event()
                    hb_thread = threading.Thread(
                        target=self._run_heartbeat_loop, 
                        args=(can_bus, expected_ids, stop_event, task_id)
                    )
                    hb_thread.daemon = True
                    hb_thread.start()
                    
                    # 记录并挂载到管理器中，便于后续控制
                    self.heartbeat_managers[can_bus]["event"] = stop_event
                    self.heartbeat_managers[can_bus]["thread"] = hb_thread
                else:
                    # 精准计算出缺失的槽位 ID
                    missing_str = ", ".join(map(str, missing_ids))
                    log_err = f"检测到 CANID: {missing_str} 缺失。请检查线缆连接或者是否正确执行 calibration。"
                    result_data = {
                        "status": "missing",
                        "missing_ids": missing_ids,
                        "message": log_err
                    }
                    self.redis_handler.set_value(redis_key, result_data)
                    # 🌟 同步向黑框写入缺失的报错红字！
                    self.redis_handler.set_value(task_id, f"MISSING ERROR: {log_err}")
                    print(f"[{can_bus}] 检测判定失败，未激活心跳。报告结果: {result_data}")

            # ============================== 任务 2：点击 Complete ==============================
            elif task_name == 'complete_test':
                # 操作员按下 Complete 按钮，或者点击 Execute 开始测试时，调用此逻辑彻底释放并杀掉心跳线程
                self._stop_existing_heartbeat(can_bus)
                
                # 同步更新 Redis 状态为 idle
                self.redis_handler.set_value(redis_key, {"status": "idle", "message": "等待检测"})
                # 同步更新黑框提示
                self.redis_handler.set_value(task_id, "STATUS: 检测状态已重置，心跳守护线程已安全释放。")
                print(f"[{can_bus}] 收到清理指令，检测状态已重置为 idle，心跳守护线程已安全释放。")

        except Exception as e:
            print(f"解析来自魏工专属检测队列的消息包失败: {e}")

if __name__ == "__main__":
    service = CanConnectivityService(server_ip='192.168.2.47', port=5672)
    service.start_service()