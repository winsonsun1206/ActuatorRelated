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

class Can0ConnectivityService:
    def __init__(self, server_ip='192.168.2.47', port=5672):
        self.can_bus = "can0"
        self.station_name = read_station_conf().get("station_name", "unknown_station").strip()
        
        self.queue_name = f"canconnect_queue_{self.station_name}_can0".strip()
        self.credentials = pika.PlainCredentials('admin', 'ni50509800')
        
        self.connection = pika.BlockingConnection(pika.ConnectionParameters(
            server_ip, port, '/', self.credentials, heartbeat=7200, blocked_connection_timeout=7201))
        self.channel = self.connection.channel()
        self.channel.queue_declare(queue=self.queue_name, durable=True)
        
        self.send_connection = pika.BlockingConnection(pika.ConnectionParameters(
            server_ip, port, '/', self.credentials, heartbeat=7200, blocked_connection_timeout=7201))
        self.send_channel = self.send_connection.channel()
        self.send_channel.queue_declare(queue=self.queue_name, durable=True)
        
        self.redis_handler = RedisHandler(host=server_ip, port=6379, db=0)
        self.task_queue = queue.Queue()
        
        self.test_consumer_thread = threading.Thread(target=self.process_tasks)
        self.test_consumer_thread.daemon = True
        self.test_consumer_thread.start()
        
        self.heartbeat_event = None
        self.heartbeat_thread = None
        self.consumer_tag = None

    def callback(self, ch, method, properties, body):
        # 🌟 核心改进：通过 properties 里的 headers 标签，判断如果是自己刚才发出来的结果，直接 Ack 掉并退出，绝不进入检测流程，防止卡死 Unacked
        if properties.headers and properties.headers.get('msg_type') == 'check_result_package':
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

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
                    ch.basic_ack(delivery_tag=method.delivery_tag)
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
            
            # 双重过滤保障
            if not task.get('task_name') and not task.get('operation') and len(task) == 1:
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            ch.basic_ack(delivery_tag=method.delivery_tag)
            print(f"\n======== [RAWMQ_PACK] {self.can_bus} 抓到网页原始包裹 ========\n{body}")
            beautiful_json = json.dumps(task, indent=4, ensure_ascii=False)
            print(f"----------------------------------------\n还原后的标准 JSON 字典键值对:\n{beautiful_json}\n==========================================")
            
            self.task_queue.put_nowait(task)

    def _update_live_monitor(self, target_key, log_message):
        try:
            self.redis_handler.redis_client.setex(target_key, 600, str(log_message))
        except Exception:
            pass

    def _run_heartbeat_loop(self, target_ids, stop_event, task_id, redis_key):
        from utils.send_data import send_heartbeat
        print(f"🌟 [{self.can_bus}] 心跳线程已启动，正在持续维持有效电机 ID {target_ids} 的长连接...")
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
            print(f"🔒 [{self.can_bus}] 历史心跳守护线程已安全释放。")

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

                if 'complete' in task_name or 'complete' in operation:
                    self._stop_existing_heartbeat()
                    self.redis_handler.set_value(redis_key, {"status": "idle", "message": "等待检测"})
                    continue

                if 'check' in task_name or 'check' in operation or 'test' in task_name or 'connectivity' in task_name:
                    self._stop_existing_heartbeat()
                    
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
                        result_sentence = "未检测到输入任何序列号，请至少在一个槽位输入数据再检测！"
                        try:
                            self.send_channel.basic_publish(
                                exchange='', routing_key=self.queue_name,
                                body=json.dumps({task_id: result_sentence}, ensure_ascii=False).encode('utf-8'),
                                properties=pika.BasicProperties(content_type='application/json', delivery_mode=2, headers={'msg_type': 'check_result_package'})
                            )
                        except Exception:
                            pass
                        continue

                    try:
                        can_bus_interface = can.interface.Bus(channel=self.can_bus, interface='socketcan', receive_timeout=0.1)
                    except Exception as e:
                        result_sentence = f"物理接口 [{self.can_bus}] 开启失败: {str(e)}"
                        try:
                            self.send_channel.basic_publish(
                                exchange='', routing_key=self.queue_name,
                                body=json.dumps({task_id: result_sentence}, ensure_ascii=False).encode('utf-8'),
                                properties=pika.BasicProperties(content_type='application/json', delivery_mode=2, headers={'msg_type': 'check_result_package'})
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
                    
                    missing_ids = [idx for idx in expected_ids if idx not in found_devices]

                    if not missing_ids:
                        result_sentence = "所有电机均已检测到，请继续下一步！"
                        status_redis = "success"
                        
                        # 启动守护心跳
                        stop_event = threading.Event()
                        hb_thread = threading.Thread(target=self._run_heartbeat_loop, args=(expected_ids, stop_event, task_id, redis_key))
                        hb_thread.daemon = True
                        hb_thread.start()
                        self.heartbeat_event = stop_event
                        self.heartbeat_thread = hb_thread
                    else:
                        missing_str = ", ".join(map(str, missing_ids))
                        result_sentence = f"检测到 CAN ID: [{missing_str}] 未识别到，请检测硬件连接或是否校准！"
                        status_redis = "missing"

                    result_payload = {task_id: result_sentence}
                    try:
                        # 🌟 注入 headers 属性区分这个消息是‘结果包’
                        self.send_channel.basic_publish(
                            exchange='',
                            routing_key=self.queue_name,
                            body=json.dumps(result_payload, ensure_ascii=False).encode('utf-8'),
                            properties=pika.BasicProperties(
                                content_type='application/json',
                                delivery_mode=2,
                                headers={'msg_type': 'check_result_package'} # 🌟 打上特殊的电子标签
                            )
                        )
                        print(f"✨✨ [{self.can_bus}] 结果键值对已成功送回原始 MQ 队列中，且处于 Ready 留存状态!")
                    except Exception as mq_err:
                        print(f"[{self.can_bus}] 发送结果到 RabbitMQ 失败: {mq_err}")

                    self.redis_handler.set_value(redis_key, {"status": status_redis, "message": result_sentence})
                    self._update_live_monitor(task_id, result_sentence)
                    self._update_live_monitor(redis_key, result_sentence)

            except queue.Empty:
                time.sleep(0.01)
                continue

    def start_consuming(self):
        self.consumer_tag = self.channel.basic_consume(queue=self.queue_name, on_message_callback=self.callback, auto_ack=False)
        print(f"成功挂起专属独立检测服务: [{self.queue_name}]")
        self.channel.start_consuming()

if __name__ == "__main__":
    service = Can0ConnectivityService(server_ip='192.168.2.47', port=5672)
    service.start_consuming()