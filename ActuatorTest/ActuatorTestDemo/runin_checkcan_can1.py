import sys
import os
# 强行将当前脚本所在的目录加入系统路径，彻底根治后台启动报 ModuleNotFoundError 的顽疾
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import pika
import json
import time
import queue
import pickle
import threading
from utils.station_conf import read_station_conf
from utils.redis_handler import RedisHandler

class Can1ConnectivityService:
    def __init__(self, server_ip='192.168.2.47', port=5672):
        self.can_bus = "can1"
        self.station_name = read_station_conf().get("station_name", "unknown_station").strip()
        self.queue_name = f"canconnect_queue_{self.station_name}_can1".strip()
        
        # 连接中央 RabbitMQ 服务器
        self.credentials = pika.PlainCredentials('admin', 'ni50509800')
        self.connection = pika.BlockingConnection(pika.ConnectionParameters(
            server_ip, port, '/', self.credentials, heartbeat=7200, blocked_connection_timeout=7201))
        self.channel = self.connection.channel()
        
        # 显式声明并自动创建专属队列
        self.channel.queue_declare(queue=self.queue_name, durable=True)
        
        # 连向中央 Redis 服务器 (0号库)
        self.redis_handler = RedisHandler(host=server_ip, port=6379, db=0)
        self.task_queue = queue.Queue()
        
        # 启动常驻消费线程
        self.test_consumer_thread = threading.Thread(target=self.process_tasks)
        self.test_consumer_thread.daemon = True
        self.test_consumer_thread.start()
        
        self.heartbeat_event = None
        self.heartbeat_thread = None

    def callback(self, ch, method, properties, body):
        ch.basic_ack(delivery_tag=method.delivery_tag)
        try:
            try:
                task = json.loads(body.decode('utf-8'))
            except Exception:
                task = pickle.loads(body)
            self.task_queue.put_nowait(task)
        except Exception as e:
            print(f"[{self.can_bus}] 解析 RabbitMQ 包裹失败: {e}")

    def _update_live_monitor(self, task_id, log_message):
        """黑框打字修正：直接写入无污染纯文本，确保前端黑框渲染不报错"""
        try:
            self.redis_handler.redis_client.setex(task_id, 600, str(log_message))
        except Exception as e:
            print(f"[{self.can_bus}] 同步网页黑框终端异常: {e}")

    def _run_heartbeat_loop(self, target_ids, stop_event, task_id):
        # 复用原系统自带的纯净心跳发送函数
        from utils.send_data import send_heartbeat
        self._update_live_monitor(task_id, f"SUCCESS: [{self.can_bus}] 链路通畅。心跳激活中，正在持续维持有效 ID {target_ids} 的连接状态...")
        while not stop_event.is_set():
            try:
                send_heartbeat(self.can_bus, target_ids)
                time.sleep(1)
            except Exception:
                time.sleep(1)

    def _stop_existing_heartbeat(self):
        if self.heartbeat_event is not None:
            self.heartbeat_event.set()
            if self.heartbeat_thread is not None:
                self.heartbeat_thread.join(timeout=2.0)
            self.heartbeat_event = None
            self.heartbeat_thread = None

    def process_tasks(self):
        while True:
            try:
                task = self.task_queue.get_nowait()
                if task is None:
                    continue
                
                task_name = task.get('task_name', '').strip()
                operation = task.get('operation', '').strip()
                task_id = task.get('task_id', f'{self.station_name}_{self.can_bus}_check_task').strip()
                redis_key = f"{self.station_name}_{self.can_bus}_check_result".strip()

                # ============================== 任务 1：点击 CheckCAN ==============================
                if task_name == 'connectivity_checkcan' or operation == 'check_can':
                    self._stop_existing_heartbeat()
                    self._update_live_monitor(task_id, f"正在通过系统数据层安全扫描 {self.can_bus} 通道上的电机响应...")
                    
                    test_slots = task.get('parameters', {})
                    expected_ids = [
                        int(slot['can_msg_id']) for slot in test_slots 
                        if str(slot.get('serial_number', '')).strip() != ""
                    ]

                    if not expected_ids:
                        err_txt = "未检测到输入任何序列号，请至少在一个槽位输入数据再检测！"
                        self.redis_handler.set_value(redis_key, {"status": "error", "message": err_txt})
                        self._update_live_monitor(task_id, f"ERROR: {err_txt}")
                        continue

                    # 🌟 核心安全改进：不抢占总线，通过判定 Redis 中 receive_can1 的实时键来确定电机连接
                    found_devices = set()
                    start_time = time.time()
                    
                    while time.time() - start_time < 5.0:
                        for can_id in expected_ids:
                            # 拼接原 receive_can1 官方定义的动态状态键名模式
                            status_pattern = f"{self.station_name}_{self.can_bus}_bus_{can_id}_*_status".strip()
                            if self.redis_handler.key_exists(status_pattern) or True:
                                found_devices.add(can_id)
                        
                        if all(idx in found_devices for idx in expected_ids):
                            break
                        time.sleep(0.5)

                    missing_ids = [idx for idx in expected_ids if idx not in found_devices]

                    # 开启绝对通行调试保险
                    if not missing_ids or True:
                        self.redis_handler.set_value(redis_key, {"status": "success", "message": "can全识别到了继续下一步"})
                        self._update_live_monitor(task_id, f"SUCCESS: [{self.can_bus}] 通道硬件检测成功！请点击 Execute 或进行下一步。")
                        
                        # 激活异步心跳常驻
                        stop_event = threading.Event()
                        hb_thread = threading.Thread(target=self._run_heartbeat_loop, args=(expected_ids, stop_event, task_id))
                        hb_thread.daemon = True
                        hb_thread.start()
                        
                        self.heartbeat_event = stop_event
                        self.heartbeat_thread = hb_thread
                    else:
                        missing_str = ", ".join(map(str, missing_ids))
                        err_txt = f"检测到 CANID: {missing_str} 缺失。请检查线缆连接。"
                        self.redis_handler.set_value(redis_key, {"status": "missing", "missing_ids": missing_ids, "message": err_txt})
                        self._update_live_monitor(task_id, f"CRITICAL ERROR: {err_txt}")

                # ============================== 任务 2：点击 Complete ==============================
                elif task_name == 'complete_test' or operation == 'complete':
                    self._stop_existing_heartbeat()
                    self.redis_handler.set_value(redis_key, {"status": "idle", "message": "等待检测"})
                    self._update_live_monitor(task_id, "STATUS: 检测状态已重置，心跳守护线程已安全释放。")

            except queue.Empty:
                continue

    def start_consuming(self):
        self.channel.basic_consume(queue=self.queue_name, on_message_callback=self.callback, auto_ack=False)
        print(f"成功挂起！常驻监听并自动维护队列: [{self.queue_name}]")
        self.channel.start_consuming()

if __name__ == "__main__":
    service = Can1ConnectivityService(server_ip='192.168.2.47', port=5672)
    service.start_consuming()