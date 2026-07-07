import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import pika
import json
import time
import can
import queue
import threading
import pickle
from utils.station_conf import read_station_conf
from utils.redis_handler import RedisHandler

class Can0ConnectivityService:
    def __init__(self, server_ip='192.168.2.47', port=5672):
        self.can_bus = "can0"
        self.station_name = read_station_conf().get("station_name", "unknown_station").strip()
        
        self.queue_name = f"canconnect_queue_{self.station_name}_can0".strip()
        self.redis_task_key = f"{self.station_name}_{self.can_bus}_task_input".strip()

        self.credentials = pika.PlainCredentials('admin', 'ni50509800')
        
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

    def _update_live_monitor(self, target_key, log_message):
        try:
            self.redis_handler.redis_client.setex(target_key, 600, str(log_message))
        except Exception as e:
            print(f"\033[1;31m❌ [REDIS_ERROR] [{self.can_bus}] 写入 Live Monitor 失败: {e}\033[0m")

    def _run_heartbeat_loop(self, target_ids, stop_event, task_id, redis_key):
        from utils.send_data import send_heartbeat
        print(f"🌟 [{self.can_bus}] 心跳线程已启动，持续维持有效电机 ID {target_ids} 的长连接防止休眠...")
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
                
                # 获取任务专属唯一 UID / task_id
                task_id = task.get('task_id') or task.get('id') or task.get('job_id') or f"{self.station_name}_{self.can_bus}_check_task"
                task_id = str(task_id).strip()
                
                # 将 redis_key 直接映射为 task_id 字符串
                redis_key = task_id

                # 🌟 收到 complete 指令：重置为 "等待检测" 纯字符串，维持 2 小时生命期
                if 'complete' in task_name or 'complete' in operation:
                    self._stop_existing_heartbeat()
                    try:
                        self.redis_handler.redis_client.setex(
                            name=redis_key, 
                            time=7200, 
                            value="等待检测"
                        )
                        print(f"✨ [{self.can_bus}] 状态已重置为纯文本 [等待检测]，键为: {redis_key}")
                    except Exception as e:
                        print(f"\033[1;31m❌ [REDIS_ERROR] [{self.can_bus}] 重置任务状态到 Redis 失败: {e}\033[0m")
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
                                properties=pika.BasicProperties(content_type='application/json', delivery_mode=2)
                            )
                        except Exception:
                            pass
                        
                        # 🌟 未输入序列号：直接存入纯字符串，保存 2 小时
                        try:
                            self.redis_handler.redis_client.setex(
                                name=redis_key,
                                time=7200,
                                value=str(result_sentence)
                            )
                        except Exception as e:
                            print(f"\033[1;31m❌ [REDIS_ERROR] [{self.can_bus}] 同步空任务状态到 Redis 失败: {e}\033[0m")
                        continue

                    try:
                        can_bus_interface = can.interface.Bus(channel=self.can_bus, interface='socketcan', receive_timeout=0.1)
                    except Exception as e:
                        result_sentence = f"物理接口 [{self.can_bus}] 开启失败: {str(e)}"
                        try:
                            self.send_channel.basic_publish(
                                exchange='', routing_key=self.queue_name,
                                body=json.dumps({task_id: result_sentence}, ensure_ascii=False).encode('utf-8'),
                                properties=pika.BasicProperties(content_type='application/json', delivery_mode=2)
                            )
                        except Exception:
                            pass
                        
                        # 🌟 物理接口失败：直接存入纯字符串结果，保存 2 小时
                        try:
                            self.redis_handler.redis_client.setex(
                                name=redis_key,
                                time=7200,
                                value=str(result_sentence)
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
                        
                        stop_event = threading.Event()
                        hb_thread = threading.Thread(target=self._run_heartbeat_loop, args=(expected_ids, stop_event, task_id, redis_key))
                        hb_thread.daemon = True
                        hb_thread.start()
                        self.heartbeat_event = stop_event
                        self.heartbeat_thread = hb_thread
                    else:
                        missing_str = ", ".join(map(str, missing_ids))
                        result_sentence = f"检测到 CAN ID: [{missing_str}] 未识别到，请检测硬件连接或是否校准！"

                    result_payload = {task_id: result_sentence}
                    try:
                        self.send_channel.basic_publish(
                            exchange='',
                            routing_key=self.queue_name,
                            body=json.dumps(result_payload, ensure_ascii=False).encode('utf-8'),
                            properties=pika.BasicProperties(content_type='application/json', delivery_mode=2)
                        )
                        print(f"✨✨ [{self.can_bus}] 结果已推送至 MQ 队列。")
                    except Exception as mq_err:
                        print(f"[{self.can_bus}] 发送结果到 RabbitMQ 失败: {mq_err}")

                    # 🌟 核心修改点：强制采用原生 setex 存入纯文本字符串提示，并维持 2 小时有效寿命。
                    try:
                        self.redis_handler.redis_client.setex(
                            name=redis_key, 
                            time=7200, 
                            value=str(result_sentence)
                        )
                        print(f"✨ [{self.can_bus}] 纯字符串值已写入 Redis 键 [{redis_key}]，两小时后自动销毁。")
                    except Exception as e:
                        print(f"\033[1;31m❌ [REDIS_ERROR] [{self.can_bus}] 同步最终结果到 Redis 失败: {e}\033[0m")

            except queue.Empty:
                time.sleep(0.01)
                continue

    def start_polling_redis(self):
        print(f"成功挂起专属独立检测服务。正在实时轮询 Redis 任务指令 Key: [{self.redis_task_key}]...")
        while True:
            try:
                raw_data = self.redis_handler.redis_client.get(self.redis_task_key)
                if raw_data:
                    try:
                        self.redis_handler.redis_client.delete(self.redis_task_key)
                    except Exception as del_err:
                        print(f"\033[1;31m❌ [REDIS_ERROR] [{self.can_bus}] 清空消费标记失败: {del_err}\033[0m")
                    
                    task = None
                    try:
                        task = pickle.loads(raw_data)
                    except Exception:
                        try:
                            task = json.loads(raw_data.decode('utf-8') if isinstance(raw_data, bytes) else raw_data)
                        except Exception as p_err:
                            print(f"\033[1;31m❌ 数据反序列化失败，既不是原厂有效 Pickle 也不是通用 JSON\033[0m")
                        
                    if task:
                        self.task_queue.put_nowait(task)
            except Exception as e:
                print(f"\033[1;31m❌ [REDIS_CRITICAL_ERROR] [{self.can_bus}] 无法从服务器 192.168.2.47 读取数据: {e}\033[0m")
            time.sleep(0.5)

if __name__ == "__main__":
    service = Can0ConnectivityService(server_ip='192.168.2.47', port=5672)
    service.start_polling_redis()