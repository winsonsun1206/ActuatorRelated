import sys
import os
# 强行将当前脚本所在的目录加入系统路径，彻底根治相对路径导入丢失问题
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import pika
import json
import time
import can
import queue
import pickle
import threading
from utils.station_conf import read_station_conf
from utils.redis_handler import RedisHandler

class Can0ConnectivityService:
    def __init__(self, server_ip='192.168.2.47', port=5672):
        self.can_bus = "can0"
        self.station_name = read_station_conf().get("station_name", "unknown_station").strip()
        self.queue_name = f"canconnect_queue_{self.station_name}_can0".strip()
        
        self.credentials = pika.PlainCredentials('admin', 'ni50509800')
        self.connection = pika.BlockingConnection(pika.ConnectionParameters(
            server_ip, port, '/', self.credentials, heartbeat=7200, blocked_connection_timeout=7201))
        self.channel = self.connection.channel()
        
        # 显式向 RabbitMQ 宣告，100% 增加此队列
        self.channel.queue_declare(queue=self.queue_name, durable=True)
        
        self.redis_handler = RedisHandler(host=server_ip, port=6379, db=0)
        self.task_queue = queue.Queue()
        
        self.test_consumer_thread = threading.Thread(target=self.process_tasks)
        self.test_consumer_thread.daemon = True
        self.test_consumer_thread.start()
        
        self.heartbeat_event = None
        self.heartbeat_thread = None

    def callback(self, ch, method, properties, body):
        ch.basic_ack(delivery_tag=method.delivery_tag)
        print(f"\n======== [RAWMQ_PACK] 抓到网页包裹 ========\n{body.decode('utf-8', errors='ignore')}\n==========================================")
        try:
            try:
                task = json.loads(body.decode('utf-8'))
            except Exception:
                task = pickle.loads(body)
            self.task_queue.put_nowait(task)
        except Exception as e:
            print(f"[{self.can_bus}] 解析 RabbitMQ 包裹失败: {e}")

    def _update_live_monitor(self, task_id, log_message):
        try:
            self.redis_handler.redis_client.setex(task_id, 600, str(log_message))
        except Exception as e:
            print(f"[{self.can_bus}] 同步网页黑框终端异常: {e}")

    def _run_heartbeat_loop(self, target_ids, stop_event, task_id):
        from utils.send_data import send_heartbeat
        self._update_live_monitor(task_id, f"SUCCESS: [{self.can_bus}] 硬件链路通畅。检测心跳持续维持有效 ID {target_ids} 的长连接...")
        while not stop_event.is_set():
            try:
                send_heartbeat(self.can_bus, target_ids)
                time.sleep(1.0)
            except Exception:
                time.sleep(1.0)

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

                if task_name == 'connectivity_checkcan' or operation == 'check_can':
                    self._stop_existing_heartbeat()
                    self._update_live_monitor(task_id, f"正在自动高频扫描物理 {self.can_bus} 通道上的电机连接响应...")
                    
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

                    # 打开物理 SocketCAN
                    try:
                        # 核心修改：加入 recv_timeout 保险，确保资源能及时释放
                        can_bus_interface = can.interface.Bus(channel=self.can_bus, interface='socketcan', receive_timeout=0.1)
                    except Exception as e:
                        err_txt = f"接口 [{self.can_bus}] 开启失败: {str(e)}"
                        self.redis_handler.set_value(redis_key, {"status": "error", "message": err_txt})
                        self._update_live_monitor(task_id, f"ERROR: {err_txt}")
                        continue

                    found_devices = set()
                    start_time = time.time()
                    
                    while time.time() - start_time < 5.0:
                        msg = can_bus_interface.recv(timeout=0.1)
                        if msg is None:
                            # 🌟 绝杀优化：未抓到包时强制让出 CPU 片段，根治卡死 99% 顽疾
                            time.sleep(0.001)
                            continue
                        
                        if msg.arbitration_id in range(256, 512):
                            can_bus_id = msg.arbitration_id - 256
                            if can_bus_id in expected_ids:
                                found_devices.add(can_bus_id)
                                
                        if all(idx in found_devices for idx in expected_ids):
                            break
                        
                        # 🌟 绝杀优化：死循环内部让出 CPU 片段
                        time.sleep(0.001)
                    
                    can_bus_interface.shutdown()
                    missing_ids = [idx for idx in expected_ids if idx not in found_devices]

                    if not missing_ids:
                        self.redis_handler.set_value(redis_key, {"status": "success", "message": "can全识别到了继续下一步"})
                        self._update_live_monitor(task_id, f"SUCCESS: [{self.can_bus}] 通道硬件检测成功通过！请开始正式测试。")
                        
                        stop_event = threading.Event()
                        hb_thread = threading.Thread(target=self._run_heartbeat_loop, args=(expected_ids, stop_event, task_id))
                        hb_thread.daemon = True
                        hb_thread.start()
                        
                        self.heartbeat_event = stop_event
                        self.heartbeat_thread = hb_thread
                    else:
                        missing_str = ", ".join(map(str, missing_ids))
                        err_txt = f"检测到 CANID: {missing_str} 缺失。请检查硬件线缆连接。"
                        self.redis_handler.set_value(redis_key, {"status": "missing", "missing_ids": missing_ids, "message": err_txt})
                        self._update_live_monitor(task_id, f"CRITICAL ERROR: {err_txt}")

                elif task_name == 'complete_test' or operation == 'complete':
                    self._stop_existing_heartbeat()
                    self.redis_handler.set_value(redis_key, {"status": "idle", "message": "等待检测"})
                    self._update_live_monitor(task_id, "STATUS: 检测状态已重置，心跳线程已成功安全断开。")

            except queue.Empty:
                # 🌟 绝杀优化：队列为空时休眠，降低 CPU
                time.sleep(0.01)
                continue

    def start_consuming(self):
        self.channel.basic_consume(queue=self.queue_name, on_message_callback=self.callback, auto_ack=False)
        print(f"成功挂起！常驻监听并自动维护队列: [{self.queue_name}]")
        self.channel.start_consuming()

if __name__ == "__main__":
    service = Can0ConnectivityService(server_ip='192.168.2.47', port=5672)
    service.start_consuming()