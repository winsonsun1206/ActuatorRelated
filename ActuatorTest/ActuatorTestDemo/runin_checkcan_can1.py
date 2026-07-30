import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import pika
import json
import time
import can
import queue
import threading
from utils.station_conf import read_station_conf
from utils.redis_handler import RedisHandler

class Can1ConnectivityService:
    def __init__(self, server_ip='192.168.2.66', port=5672):
        self.can_bus = "can1"
        self.station_name = read_station_conf().get("station_name", "unknown_station").strip()
        
        # 树莓派常驻监听的 RabbitMQ 任务下发队列
        self.queue_name = f"canconnect_queue_{self.station_name}_can1".strip()

        # 配置 RabbitMQ 连接属性
        self.credentials = pika.PlainCredentials('admin', 'ni50509800')
        self.mq_connection = pika.BlockingConnection(pika.ConnectionParameters(
            server_ip, port, '/', self.credentials, heartbeat=7200, blocked_connection_timeout=7201))
        self.mq_channel = self.mq_connection.channel()
        self.mq_channel.queue_declare(queue=self.queue_name, durable=True)
        
        # 初始化 Redis 结果处理器
        self.redis_handler = RedisHandler(host=server_ip, port=6379, db=0)
        
        # 历史心跳守护控制线程锁
        self.heartbeat_event = None
        self.heartbeat_thread = None

    def _run_heartbeat_loop(self, target_ids, stop_event):
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

    def process_tasks_callback(self, ch, method, properties, body):
        """🌟 终极强力兼容版：同时通杀并解析纯文本 JSON 以及 Python Pickle 二进制流"""
        try:
            if not body:
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            task = None

            # 🌟 核心兼容转换开始
            # 尝试一：如果数据以 0x80 (Pickle) 字符开头，或者常规 utf-8 失败，优先尝试 pickle 解包
            if body.startswith(b'\x80'):
                try:
                    import pickle
                    task = pickle.loads(body)
                    print(f"✨ [{self.can_bus}] 成功通过【Pickle 二进制通道】解密解析任务参数。")
                except Exception as p_err:
                    print(f"⚠️ 疑似 Pickle 数据但解包失败: {p_err}")

            # 尝试二：如果不是二进制或 pickle 失败，走常规 JSON 解析
            if task is None:
                try:
                    decoded_str = body.decode('utf-8') if isinstance(body, bytes) else str(body)
                    task = json.loads(decoded_str.strip())
                    print(f"✨ [{self.can_bus}] 成功通过【标准 JSON 通道】解析任务参数。")
                except Exception:
                    pass

            # 兜底判定
            if not task or not isinstance(task, dict):
                print(f"❌ [{self.can_bus}] 格式转换彻底失败！数据既无法按 JSON 解码也无法按 Pickle 解析。")
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            task_name = str(task.get('task_name', task.get('operation', ''))).strip()
            operation = str(task.get('operation', '')).strip()
            
            # 提取专属唯一 UID / task_id
            task_id = task.get('task_id') or task.get('id') or task.get('job_id') or f"{self.station_name}_{self.can_bus}_check_task"
            task_id = str(task_id).strip()
            redis_key = task_id

            # 收到 complete 重置指令：将结果写入 Redis，保存 2 小时
            if 'complete' in task_name or 'complete' in operation:
                self._stop_existing_heartbeat()
                try:
                    self.redis_handler.redis_client.setex(name=redis_key, time=7200, value="等待检测")
                    print(f"✨ [{self.can_bus}] 收到完结指令，Redis 键 [{redis_key}] 已拨回 -> [等待检测]")
                except Exception as e:
                    print(f"❌ [REDIS_ERROR] [{self.can_bus}] 重置状态失败: {e}")
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            # 收到实际检测或校验指令
            if 'check' in task_name or 'check' in operation or 'test' in task_name or 'connectivity' in task_name:
                self._stop_existing_heartbeat()
                print(f"📥 [{self.can_bus}] 开始进行物理 CAN 硬件对比。Task ID: {task_id}")
                
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
                        self.redis_handler.redis_client.setex(name=redis_key, time=7200, value=str(result_sentence))
                    except Exception as e:
                        print(f"❌ [REDIS_ERROR] 同步空任务状态失败: {e}")
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                    return

                try:
                    can_bus_interface = can.interface.Bus(channel=self.can_bus, interface='socketcan', receive_timeout=0.1)
                except Exception as e:
                    result_sentence = f"物理接口 [{self.can_bus}] 开启失败: {str(e)}"
                    try:
                        self.redis_handler.redis_client.setex(name=redis_key, time=7200, value=str(result_sentence))
                    except Exception:
                        pass
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                    return

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
                    hb_thread = threading.Thread(target=self._run_heartbeat_loop, args=(expected_ids, stop_event))
                    hb_thread.daemon = True
                    hb_thread.start()
                    self.heartbeat_event = stop_event
                    self.heartbeat_thread = hb_thread
                else:
                    missing_str = ", ".join(map(str, missing_ids))
                    result_sentence = f"检测到 CAN ID: [{missing_str}] 未识别到，请检测硬件连接或是否校准！"

                try:
                    self.redis_handler.redis_client.setex(
                        name=redis_key, 
                        time=7200, 
                        value=str(result_sentence)
                    )
                    print(f"✨ [{self.can_bus}] 对比完毕！纯提示信息已成功写回 Redis 键 [{redis_key}]")
                except Exception as e:
                    print(f"❌ [REDIS_ERROR] [{self.can_bus}] 同步最终结果到 Redis 失败: {e}")

                ch.basic_ack(delivery_tag=method.delivery_tag)

        except Exception as err:
            print(f"❌ [CONSUME_CRITICAL_ERROR] 处理任务回调中遭遇异常: {err}")
            try:
                ch.basic_ack(delivery_tag=method.delivery_tag)
            except Exception:
                pass

    def start_consuming_mq(self):
        """代替原先的轮询，将树莓派完全注册为基于 MQ 事件驱动的消费守护进程"""
        print(f"🚀 [全新架构：MQ 消费者模式已激活] 正在树莓派本地常驻监听 RabbitMQ 任务下发队列: [{self.queue_name}]...")
        
        # 限制每次只拿一条任务，多余的任务在 MQ 队列挂起排队，极为稳定安全
        self.mq_channel.basic_qos(prefetch_count=1)
        
        # 绑定接收回调
        self.mq_channel.basic_consume(queue=self.queue_name, on_message_callback=self.process_tasks_callback)
        
        try:
            self.mq_channel.start_consuming()
        except KeyboardInterrupt:
            print("🛑 正在优雅安全关闭常驻 MQ 链路...")
            self.mq_channel.stop_consuming()
            self.mq_connection.close()

if __name__ == "__main__":
    service = Can1ConnectivityService(server_ip='192.168.2.66', port=5672)
    service.start_consuming_mq()