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
        
        # 纯净化界面：仅打印包裹头部和基础数据
        print(f"\n======== [RAWMQ_PACK] {self.can_bus} 抓到网页原始包裹 ========\n{body}")
        
        task = None
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
            if not isinstance(task, dict):
                if hasattr(task, '__dict__'):
                    task = task.__dict__
                else:
                    try:
                        task = dict(task)
                    except Exception:
                        pass
            
            beautiful_json = json.dumps(task, indent=4, ensure_ascii=False)
            print(f"----------------------------------------\n还原后的标准 JSON 字典键值对:\n{beautiful_json}\n==========================================")
            
            # 判断如果是包含检测指令，将其推入本地任务队列进行物理硬件扫描检测
            task_name = str(task.get('task_name', task.get('operation', ''))).strip()
            operation = str(task.get('operation', '')).strip()
            if 'check' in task_name or 'check' in operation or 'test' in task_name or 'connectivity' in task_name:
                self.task_queue.put_nowait(task)

    def _update_live_monitor(self, target_key, log_message):
        try:
            self.redis_handler.redis_client.setex(target_key, 600, str(log_message))
        except Exception:
            pass

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

                task_id = task.get('task_id') or task.get('id') or task.get('job_id') or f"{self.station_name}_{self.can_bus}_check_task"
                task_id = str(task_id).strip()
                redis_key = f"{self.station_name}_{self.can_bus}_check_result".strip()

                self._stop_existing_heartbeat()
                
                # 1. 🌟 精准识别输入框：只有输了序列号的才加入预期的 expected_ids 列表
                test_slots = task.get('parameters', [])
                if isinstance(test_slots, dict):
                    test_slots = list(test_slots.values())
                    
                expected_ids = []
                if isinstance(test_slots, list):
                    for slot in test_slots:
                        if not isinstance(slot, dict) and hasattr(slot, '__dict__'):
                            slot = slot.__dict__
                            
                        if isinstance(slot, dict):
                            sn_val = str(slot.get('serial_number', '')).strip()
                            target_id_val = slot.get('can_msg_id') or slot.get('can_bus_id')
                            
                            # 🌟 核心判断：方框中输入了序列号才代表这个 ID 需要被检测
                            if sn_val != "" and target_id_val is not None:
                                try:
                                    expected_ids.append(int(target_id_val))
                                except (ValueError, TypeError):
                                    pass

                # 兜底：如果列表是空的，尝试获取外层可能的单个 ID（同样要求有输入）
                if not expected_ids:
                    fallback_id = task.get('can_msg_id') or task.get('can_bus_id')
                    if fallback_id is not None:
                        try:
                            expected_ids.append(int(fallback_id))
                        except Exception:
                            pass

                # 如果确实什么都没填，直接向 MQ 返回特定报错格式
                if not expected_ids:
                    result_sentence = "未检测到输入任何序列号，请至少在一个槽位输入数据再检测！"
                    result_payload = {task_id: result_sentence}
                    try:
                        self.channel.basic_publish(
                            exchange='',
                            routing_key=self.queue_name,
                            body=json.dumps(result_payload, ensure_ascii=False).encode('utf-8'),
                            properties=pika.BasicProperties(content_type='application/json', delivery_mode=2)
                        )
                    except Exception:
                        pass
                    continue

                # 2. 物理总线扫描 5.0 秒
                try:
                    can_bus_interface = can.interface.Bus(channel=self.can_bus, interface='socketcan', receive_timeout=0.1)
                except Exception as e:
                    result_sentence = f"物理接口 [{self.can_bus}] 开启失败: {str(e)}"
                    try:
                        self.channel.basic_publish(
                            exchange='',
                            routing_key=self.queue_name,
                            body=json.dumps({task_id: result_sentence}, ensure_ascii=False).encode('utf-8'),
                            properties=pika.BasicProperties(content_type='application/json', delivery_mode=2)
                        )
                    except Exception:
                        pass
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
                
                # 3. 🌟 根据物理扫描结果，精密匹配缺失的 ID
                missing_ids = [idx for idx in expected_ids if idx not in found_devices]

                # 4. 🌟 按工程师要求的逻辑生成指定键值对的一句话结果
                if not missing_ids:
                    result_sentence = "所有电机均已检测到，请继续下一步！"
                    status_redis = "success"
                else:
                    missing_str = ", ".join(map(str, missing_ids))
                    result_sentence = f"检测到 CAN ID: [{missing_str}] 未识别到，请检测硬件连接或是否校准！"
                    status_redis = "missing"

                # 5. 🌟 【核心发往RabbitMQ】封装为 { "task_id": "判断内容一句话" } 的键值对格式
                result_payload = {
                    task_id: result_sentence
                }
                
                try:
                    self.channel.basic_publish(
                        exchange='',
                        routing_key=self.queue_name, # 发送到方框对应的队列
                        body=json.dumps(result_payload, ensure_ascii=False).encode('utf-8'),
                        properties=pika.BasicProperties(
                            content_type='application/json',
                            delivery_mode=2
                        )
                    )
                    print(f"✨✨ [{self.can_bus}] 物理检测完成，结果键值对已成功发往 MQ 队列!")
                except Exception as mq_err:
                    print(f"[{self.can_bus}] 发送结果键值对到 RabbitMQ 失败: {mq_err}")

                # 同步更新 Redis 和 网页 Live 监视器面板
                self.redis_handler.set_value(redis_key, {"status": status_redis, "message": result_sentence})
                self._update_live_monitor(task_id, result_sentence)
                self._update_live_monitor(redis_key, result_sentence)

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