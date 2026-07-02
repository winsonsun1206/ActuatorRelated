import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import pika
import json
import time
import can
import queue
import threading
import re
from utils.station_conf import read_station_conf
from utils.redis_handler import RedisHandler

class Can1ConnectivityService:
    def __init__(self, server_ip='192.168.2.47', port=5672):
        self.can_bus = "can1"
        self.station_name = read_station_conf().get("station_name", "unknown_station").strip()
        
        # 🌟 统一向工程师制定的这一个原始队列发送结果包
        self.queue_name = f"canconnect_queue_{self.station_name}_can1".strip()
        # 🌟 工程师新定义的 Redis 任务接收 Key
        self.redis_task_key = f"{self.station_name}_{self.can_bus}_task_input".strip()

        self.credentials = pika.PlainCredentials('admin', 'ni50509800')
        
        # 建立专属发送连接与通道
        self.send_connection = pika.BlockingConnection(pika.ConnectionParameters(
            server_ip, port, '/', self.credentials, heartbeat=7200, blocked_connection_timeout=7201))
        self.send_channel = self.send_connection.channel()
        self.send_channel.queue_declare(queue=self.queue_name, durable=True)
        
        self.redis_handler = RedisHandler(host=server_ip, port=6379, db=0)
        self.task_queue = queue.Queue()
        
        # 启动常驻任务处理线程
        self.test_consumer_thread = threading.Thread(target=self.process_tasks)
        self.test_consumer_thread.daemon = True
        self.test_consumer_thread.start()
        
        self.heartbeat_event = None
        self.heartbeat_thread = None

    def _update_live_monitor(self, target_key, log_message):
        try:
            self.redis_handler.redis_client.setex(target_key, 600, str(log_message))
        except Exception as e:
            # 🌟 核心改进：向 Redis 写入网页终端状态失败时报错
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
                
                task_id = task.get('task_id') or task.get('id') or task.get('job_id') or f"{self.station_name}_{self.can_bus}_check_task"
                task_id = str(task_id).strip()
                redis_key = f"{self.station_name}_{self.can_bus}_check_result".strip()

                if 'complete' in task_name or 'complete' in operation:
                    self._stop_existing_heartbeat()
                    try:
                        self.redis_handler.set_value(redis_key, {"status": "idle", "message": "等待检测"})
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
                        self.send_channel.basic_publish(
                            exchange='',
                            routing_key=self.queue_name,
                            body=json.dumps(result_payload, ensure_ascii=False).encode('utf-8'),
                            properties=pika.BasicProperties(content_type='application/json', delivery_mode=2)
                        )
                        print(f"✨✨ [{self.can_bus}] 结果已推送至原始 MQ 队列, 且树莓派不占用此通道，Ready 成功置 1!")
                    except Exception as mq_err:
                        print(f"[{self.can_bus}] 发送结果到 RabbitMQ 失败: {mq_err}")

                    try:
                        self.redis_handler.set_value(redis_key, {"status": status_redis, "message": result_sentence})
                    except Exception as e:
                        print(f"\033[1;31m❌ [REDIS_ERROR] [{self.can_bus}] 同步最终结果到 Redis 失败: {e}\033[0m")
                    self._update_live_monitor(task_id, result_sentence)
                    self._update_live_monitor(redis_key, result_sentence)

            except queue.Empty:
                time.sleep(0.01)
                continue

    def start_polling_redis(self):
        print(f"成功挂起专属独立检测服务。正在实时轮询 Redis 任务指令 Key: [{self.redis_task_key}]...")
        while True:
            try:
                # 从 Redis 提取网页端塞入的任务数据
                raw_data = self.redis_handler.redis_client.get(self.redis_task_key)
                if raw_data:
                    try:
                        # 🌟 核心改进：提取成功后立刻尝试清空 Redis 标识
                        self.redis_handler.redis_client.delete(self.redis_task_key)
                    except Exception as del_err:
                        print(f"\033[1;31m❌ [REDIS_ERROR] [{self.can_bus}] 清空消费标记失败 (任务可能重复消费): {del_err}\033[0m")
                    
                    try:
                        task = json.loads(raw_data.decode('utf-8') if isinstance(raw_data, bytes) else raw_data)
                    except Exception:
                        import pickle
                        task = pickle.loads(raw_data)
                        
                    if task:
                        self.task_queue.put_nowait(task)
            except Exception as e:
                # 🌟 核心改进：Redis 网络异常断联、读取失败直接爆红高亮提示
                print(f"\033[1;31m❌ [REDIS_CRITICAL_ERROR] [{self.can_bus}] 无法从服务器 192.168.2.47 读取数据，请检查网线连接: {e}\033[0m")
            time.sleep(0.5)

if __name__ == "__main__":
    service = Can1ConnectivityService(server_ip='192.168.2.47', port=5672)
    service.start_polling_redis()