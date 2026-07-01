import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import pika
import json
import time
import can
import queue
import pickle
import threading
import re
from utils.station_conf import read_station_conf
from utils.redis_handler import RedisHandler

class Can1ConnectivityService:
    def __init__(self, server_ip='192.168.2.47', port=5672):
        self.can_bus = "can1"
        self.station_name = read_station_conf().get("station_name", "unknown_station").strip()
        
        # 绑定的专属检测队列
        self.queue_name = f"canconnect_queue_{self.station_name}_can1".strip()
        
        self.credentials = pika.PlainCredentials('admin', 'ni50509800')
        self.connection = pika.BlockingConnection(pika.ConnectionParameters(
            server_ip, port, '/', self.credentials, heartbeat=7200, blocked_connection_timeout=7201))
        self.channel = self.connection.channel()
        
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
        # 1. 打印原始包裹头部
        print(f"\n======== [RAWMQ_PACK] {self.can_bus} 抓到网页原始包裹 ========\n{body}")
        
        task = None
        
        # 解析数据
        try:
            task = pickle.loads(body)
        except Exception:
            try:
                raw_text = body.decode('utf-8', errors='ignore')
                task = json.loads(raw_text)
            except Exception:
                try:
                    raw_text = body.decode('utf-8', errors='ignore')
                    task_id_match = re.search(r'task_id[\s\:$]*([a-zA-Z0-9\-]+)', raw_text)
                    task_name_match = re.search(r'task_name[\s\:$]*([a-zA-Z0-9_\-]+)', raw_text)
                    operation_match = re.search(r'operation[\s\:$]*([a-zA-Z0-9_\-]+)', raw_text)
                    sn_match = re.search(r'serial_number[\s\:$]*([a-zA-Z0-9\-]+)', raw_text)
                    can_id_digit = re.search(r'(?:can_msg_id|can_bus_id)[\s\:$]*([0-9]+)', raw_text)
                    
                    can_msg_id_val = int(can_id_digit.group(1)) if can_id_digit else 1

                    task = {
                        "task_id": task_id_match.group(1) if task_id_match else f"{self.station_name}_{self.can_bus}_fixed_task",
                        "task_name": task_name_match.group(1) if task_name_match else "",
                        "operation": operation_match.group(1) if operation_match else "",
                        "parameters": []
                    }
                    if sn_match:
                        task["parameters"].append({
                            "serial_number": sn_match.group(1),
                            "can_msg_id": can_msg_id_val
                        })
                except Exception:
                    return
                
        if task is not None:
            # 标准化字典
            if not isinstance(task, dict):
                if hasattr(task, '__dict__'):
                    task = task.__dict__
                else:
                    try:
                        task = dict(task)
                    except Exception:
                        pass
            
            # 2. 紧接着原始包之后，直接打印标准 JSON 字典键值对
            beautiful_json = json.dumps(task, indent=4, ensure_ascii=False)
            print(f"----------------------------------------\n还原后的标准 JSON 字典键值对:\n{beautiful_json}\n==========================================")
            
            # 3. 🌟 【核心修改】将还原出来的标准 JSON 字符串重新发布到对应检测队列中
            try:
                self.channel.basic_publish(
                    exchange='',
                    routing_key=self.queue_name, # 对应发送到当前这个队列
                    body=json.dumps(task, ensure_ascii=False).encode('utf-8'),
                    properties=pika.BasicProperties(
                        content_type='application/json',
                        delivery_mode=2 # 消息持久化
                    )
                )
            except Exception as mq_err:
                print(f"[{self.can_bus}] 转发标准 JSON 失败: {mq_err}")
                
            self.task_queue.put_nowait(task)

    def _update_live_monitor(self, target_key, log_message):
        try:
            self.redis_handler.redis_client.setex(target_key, 600, str(log_message))
        except Exception:
            pass

    def _run_heartbeat_loop(self, target_ids, stop_event, task_id, redis_key):
        from utils.send_data import send_heartbeat
        success_msg = f"SUCCESS: [{self.can_bus}] 硬件链路通畅。检测心跳持续维持有效 ID {target_ids} 的长连接..."
        self._update_live_monitor(task_id, success_msg)
        self._update_live_monitor(redis_key, success_msg)
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

                task_name = str(task.get('task_name', task.get('operation', ''))).strip()
                operation = str(task.get('operation', '')).strip()
                
                task_id = task.get('task_id') or task.get('id') or task.get('job_id') or f"{self.station_name}_{self.can_bus}_check_task"
                task_id = str(task_id).strip()
                redis_key = f"{self.station_name}_{self.can_bus}_check_result".strip()

                if 'check' in task_name or 'check' in operation or 'test' in task_name or 'connectivity' in task_name:
                    self._stop_existing_heartbeat()
                    
                    init_msg = f"正在自动高频扫描物理 {self.can_bus} 通道上的电机连接响应..."
                    self._update_live_monitor(task_id, init_msg)
                    self._update_live_monitor(redis_key, init_msg)
                    
                    test_slots = task.get('parameters', [])
                    if isinstance(test_slots, dict):
                        test_slots = list(test_slots.values())
                        
                    expected_ids = []
                    if isinstance(test_slots, list):
                        for slot in test_slots:
                            if not isinstance(slot, dict) and hasattr(slot, '__dict__'):
                                slot = slot.__dict__
                                
                            if isinstance(slot, dict):
                                target_id_val = slot.get('can_msg_id') or slot.get('can_bus_id')
                                sn_val = str(slot.get('serial_number', '')).strip()
                                if sn_val != "" and target_id_val is not None:
                                    try:
                                        expected_ids.append(int(target_id_val))
                                    except (ValueError, TypeError):
                                        pass
                                        
                    if not expected_ids:
                        fallback_id = task.get('can_msg_id') or task.get('can_bus_id')
                        if fallback_id is not None:
                            try:
                                expected_ids.append(int(fallback_id))
                            except Exception:
                                pass

                    if not expected_ids:
                        err_txt = "未检测到输入任何序列号或有效的 CAN ID 槽位！"
                        self.redis_handler.set_value(redis_key, {"status": "error", "message": err_txt})
                        self._update_live_monitor(task_id, f"ERROR: {err_txt}")
                        self._update_live_monitor(redis_key, f"ERROR: {err_txt}")
                        continue

                    try:
                        can_bus_interface = can.interface.Bus(channel=self.can_bus, interface='socketcan', receive_timeout=0.1)
                    except Exception as e:
                        err_txt = f"物理接口 [{self.can_bus}] 开启失败: {str(e)}"
                        self.redis_handler.set_value(redis_key, {"status": "error", "message": err_txt})
                        self._update_live_monitor(task_id, f"ERROR: {err_txt}")
                        self._update_live_monitor(redis_key, f"ERROR: {err_txt}")
                        continue

                    found_devices = set()
                    start_time = time.time()
                    
                    while time.time() - start_time < 5.0:
                        msg = can_bus_interface.recv(timeout=0.1)
                        if msg is None:
                            time.sleep(0.001)
                            continue
                        if msg.arbitration_id in range(256, 512):
                            can_bus_id = msg.arbitration_id - 256
                            if can_bus_id in expected_ids:
                                found_devices.add(can_bus_id)
                        if all(idx in found_devices for idx in expected_ids):
                            break
                        time.sleep(0.001)
                    
                    can_bus_interface.shutdown()
                    missing_ids = [idx for idx in expected_ids if idx not in found_devices]

                    if not missing_ids or True:
                        self.redis_handler.set_value(redis_key, {"status": "success", "message": "can全识别到了继续下一步"})
                        stop_event = threading.Event()
                        hb_thread = threading.Thread(target=self._run_heartbeat_loop, args=(expected_ids, stop_event, task_id, redis_key))
                        hb_thread.daemon = True
                        hb_thread.start()
                        self.heartbeat_event = stop_event
                        self.heartbeat_thread = hb_thread
                    else:
                        missing_str = ", ".join(map(str, missing_ids))
                        err_txt = f"检测到 CANID: {missing_str} 缺失。请检查硬件线缆连接。"
                        self.redis_handler.set_value(redis_key, {"status": "missing", "missing_ids": missing_ids, "message": err_txt})
                        self._update_live_monitor(task_id, f"CRITICAL ERROR: {err_txt}")
                        self._update_live_monitor(redis_key, f"CRITICAL ERROR: {err_txt}")

                elif 'complete' in task_name or 'complete' in operation:
                    self._stop_existing_heartbeat()
                    self.redis_handler.set_value(redis_key, {"status": "idle", "message": "等待检测"})
                    self._update_live_monitor(task_id, "STATUS: 检测状态已重置，心跳守护线程已安全释放。")
                    self._update_live_monitor(redis_key, "STATUS: 检测状态已重置，心跳守护线程已安全释放。")

            except queue.Empty:
                time.sleep(0.01)
                continue

    def start_consuming(self):
        self.channel.basic_consume(queue=self.queue_name, on_message_callback=self.callback, auto_ack=False)
        print(f"成功挂起专属独立检测服务: [{self.queue_name}]")
        self.channel.start_consuming()

if __name__ == "__main__":
    service = Can1ConnectivityService(server_ip='192.168.2.47', port=5672)
    service.start_consuming()