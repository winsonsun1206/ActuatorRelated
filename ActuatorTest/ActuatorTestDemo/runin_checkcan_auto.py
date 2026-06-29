import sys
import pika
import json
import time
import can
import queue
import pickle
import threading
from utils.station_conf import read_station_conf
from utils.redis_handler import RedisHandler

class CanConnectivityService:
    def __init__(self, server_ip='192.168.2.47', port=5672, redis_db=0):
        # 1. 实时读取台架名称 (e.g., rivr_test2)
        self.station_name = read_station_conf().get("station_name", "unknown_station").strip()
        
        # 2. 严格对齐原系统凭证与配置
        self.credentials = pika.PlainCredentials('admin', 'ni50509800')
        self.connection = pika.BlockingConnection(pika.ConnectionParameters(
            server_ip, port, '/', self.credentials, heartbeat=7200, blocked_connection_timeout=7201))
        self.channel = self.connection.channel()
        
        # 统一连向 192.168.2.47 的 Redis 控制器
        self.redis_handler = RedisHandler(host=server_ip, port=6379, db=redis_db)
        
        # 3. 仿照核心系统：建立内存任务排队管道与后台独立执行线程
        self.task_queue = queue.Queue()
        self.test_consumer_thread = threading.Thread(target=self.process_tasks)
        self.test_consumer_thread.daemon = True
        self.test_consumer_thread.start()
        
        # 异步心跳发送管理字典
        self.heartbeat_managers = {
            "can0": {"event": None, "thread": None},
            "can1": {"event": None, "thread": None}
        }

    def callback(self, ch, method, properties, body):
        """仿照原系统：收到 RabbitMQ 指令后，迅速回复 ACK 并塞入本地队列处理，严防通道阻塞"""
        ch.basic_ack(delivery_tag=method.delivery_tag)
        try:
            # 兼容处理：支持标准 json 与原有测试系统常用的 pickle 序列化
            try:
                task = json.loads(body.decode('utf-8'))
            except Exception:
                task = pickle.loads(body)
            
            # 将任务丢入线程安全的内部管道
            self.task_queue.put_nowait(task)
        except Exception as e:
            print(f"专属检测服务解析基础消息包失败: {e}")

    def _update_live_monitor(self, task_id, log_message):
        """黑框同步修正：绕过 set_value 底层的转义套娃，直接让原生客户端写入无污染纯文本"""
        try:
            self.redis_handler.redis_client.setex(task_id, 600, str(log_message))
        except Exception as e:
            print(f"向网页底端虚拟终端同步数据异常: {e}")

    def _run_heartbeat_loop(self, can_bus, target_ids, stop_event, task_id):
        """在后台死循环持续发送 CAN 心跳包"""
        print(f"[{can_bus}] 心跳守护线程已激活，维持设备 ID 列表: {target_ids}")
        # 延迟引入原系统的心跳发送函数，确保在树莓派运行时上下包完备
        from utils.send_data import send_heartbeat
        
        # 让网页底部的 Live Task Monitor 持续打印正在发心跳的状态
        self._update_live_monitor(task_id, f"SUCCESS: [{can_bus}] 链路连接通畅。心跳激活中，正在持续维持有效 ID {target_ids} 的连接状态...")
        
        while not stop_event.is_set():
            try:
                send_heartbeat(can_bus, target_ids)
                time.sleep(1)
            except Exception as e:
                print(f"[{can_bus}] 异步心跳报文发送中断: {e}")
                time.sleep(1)

    def _stop_existing_heartbeat(self, can_bus):
        """安全终止当前物理通道的心跳线程，并释放 SocketCAN 设备"""
        manager = self.heartbeat_managers[can_bus]
        if manager["event"] is not None:
            manager["event"].set()
            if manager["thread"] is not None:
                manager["thread"].join(timeout=2.0)
            manager["event"] = None
            manager["thread"] = None

    def process_tasks(self):
        """仿照原系统：在独立的消费线程中，无限循环提取任务进行物理硬件处理"""
        while True:
            try:
                task = self.task_queue.get_nowait()
                if task is None:
                    continue
                
                task_name = task.get('task_name', '').strip()
                operation = task.get('operation', '').strip()
                
                # 4. 自动确定本次网页端下发的是哪条物理通道 (从任务包中智能提取或采用队列推导)
                # 魏工设计的队列带有后缀 _can0 或 _can1，如果参数里有显式声明则优先读取
                can_bus = task.get('can_bus', 'can0').strip()
                
                # 提取黑框绑定的唯一单号
                task_id = task.get('task_id', f'{self.station_name}_{can_bus}_check_task').strip()
                redis_key = f"{self.station_name}_{can_bus}_check_result".strip()

                # ============================== 触发检测：connectivity_checkcan ==============================
                if task_name == 'connectivity_checkcan' or operation == 'check_can':
                    self._stop_existing_heartbeat(can_bus)
                    
                    # 瞬间让最下方的 Live Task Monitor 显色打字
                    self._update_live_monitor(task_id, f"正在高频自动扫描物理 {can_bus} 通道的硬件连接，请耐心等待 5 秒判定...")

                    test_slots = task.get('parameters', {})
                    
                    # 【核心槽位判定】：只要操作员填了序列号，就把槽位对应的 ID 扣出来做精准范围比对
                    expected_ids = [
                        int(slot['can_msg_id']) for slot in test_slots 
                        if str(slot.get('serial_number', '')).strip() != ""
                    ]

                    if not expected_ids:
                        err_txt = "未检测到任何有效的输入序列号！请至少在一个槽位填入条码再执行 CheckCAN。"
                        self.redis_handler.set_value(redis_key, {"status": "error", "message": err_txt})
                        self._update_live_monitor(task_id, f"ERROR: {err_txt}")
                        continue

                    print(f"[{can_bus}] 检测任务启动 -> 目标比对 ID 列表: {expected_ids}")
                    
                    # 开启物理 SocketCAN 5秒抓包
                    try:
                        can_bus_interface = can.interface.Bus(channel=can_bus, interface='socketcan')
                    except Exception as e:
                        err_txt = f"物理通道 {can_bus} 开启失败，请确认硬件接口状况: {str(e)}"
                        self.redis_handler.set_value(redis_key, {"status": "error", "message": err_txt})
                        self._update_live_monitor(task_id, f"ERROR: {err_txt}")
                        continue

                    found_devices = set()
                    start_time = time.time()
                    while time.time() - start_time < 5.0:
                        msg = can_bus_interface.recv(timeout=0.3)
                        if msg is None:
                            continue
                        if msg.arbitration_id in range(256, 512):
                            can_bus_id = msg.arbitration_id - 256
                            if can_bus_id in expected_ids:
                                found_devices.add(can_bus_id)
                        if all(idx in found_devices for idx in expected_ids):
                            break
                    
                    # 显式安全关闭底层 SocketCAN 连接，交还总线使用权
                    can_bus_interface.shutdown()

                    # 计算差集判定
                    missing_ids = [idx for idx in expected_ids if idx not in found_devices]

                    if not missing_ids:
                        # 成功分支：通知后端并向网页黑框打印绿字提示
                        self.redis_handler.set_value(redis_key, {"status": "success", "message": "can全识别到了继续下一步"})
                        self._update_live_monitor(task_id, "SUCCESS: can全识别到了继续下一步，心跳机制已就绪。")
                        
                        # 开启常驻后台异步发送心跳
                        stop_event = threading.Event()
                        hb_thread = threading.Thread(
                            target=self._run_heartbeat_loop, 
                            args=(can_bus, expected_ids, stop_event, task_id)
                        )
                        hb_thread.daemon = True
                        hb_thread.start()
                        
                        self.heartbeat_managers[can_bus]["event"] = stop_event
                        self.heartbeat_managers[can_bus]["thread"] = hb_thread
                    else:
                        missing_str = ", ".join(map(str, missing_ids))
                        err_txt = f"检测到 CANID: {missing_str} 缺失。请检查线缆连接或者是否正确执行 calibration。"
                        
                        self.redis_handler.set_value(redis_key, {"status": "missing", "missing_ids": missing_ids, "message": err_txt})
                        # 异常字样直喷网页下方黑框
                        self._update_live_monitor(task_id, f"CRITICAL ERROR: {err_txt}")

                # ============================== 触发复位：complete_test ==============================
                elif task_name == 'complete_test' or operation == 'complete':
                    self._stop_existing_heartbeat(can_bus)
                    self.redis_handler.set_value(redis_key, {"status": "idle", "message": "等待检测"})
                    self._update_live_monitor(task_id, "STATUS: 清理动作已完成。当前通道检测状态复位，心跳释放。")

            except queue.Empty:
                continue

    def start_consuming(self):
        """仿照原系统：动态宣告并消费魏工专门指派的 can0 与 can1 检测队列"""
        for bus in ['can0', 'can1']:
            q_name = f"canconnect_queue_{self.station_name}_can{bus}".strip()
            self.channel.queue_declare(queue=q_name, durable=True)
            self.channel.basic_consume(queue=q_name, on_message_callback=self.callback, auto_ack=False)
            
        print('CheckCAN 自动化常驻服务初始化完毕，正在死循环消费队列指令...')
        self.channel.start_consuming()

if __name__ == "__main__":
    service = CanConnectivityService(server_ip='192.168.2.47', port=5672)
    service.start_consuming()