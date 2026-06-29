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
    def __init__(self, queue_name, server_ip='192.168.2.47', port=5672, redis_db=0):
        # 1. 严格使用从外部传进来的确切队列名字，确保和网页端完全一致
        self.queue_name = queue_name.strip()
        self.station_name = read_station_conf().get("station_name", "unknown_station").strip()
        
        # 2. 从队列名字中自动反推当前是 can0 还是 can1 (例如从 canconnect_queue_rivr_test2_can0 中切出 can0)
        if "can1" in self.queue_name:
            self.can_bus = "can1"
        else:
            self.can_bus = "can0"
            
        self.credentials = pika.PlainCredentials('admin', 'ni50509800')
        self.connection = pika.BlockingConnection(pika.ConnectionParameters(
            server_ip, port, '/', self.credentials, heartbeat=7200, blocked_connection_timeout=7201))
        self.channel = self.connection.channel()
        
        # 显式向 RabbitMQ 宣告并创建这个队列，如果不存在会自动在服务器里增加！
        self.channel.queue_declare(queue=self.queue_name, durable=True)
        
        # 连向前台大屏幕 Redis
        self.redis_handler = RedisHandler(host=server_ip, port=6379, db=redis_db)
        
        # 3. 异步解耦任务内部管道与常驻消费线程
        self.task_queue = queue.Queue()
        self.test_consumer_thread = threading.Thread(target=self.process_tasks)
        self.test_consumer_thread.daemon = True
        self.test_consumer_thread.start()
        
        # 心跳线程控制挂载点
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
            print(f"[{self.can_bus}] 专属解析 RabbitMQ 原始包裹失败: {e}")

    def _update_live_monitor(self, task_id, log_message):
        """黑框打字修正：绕过底层 dumps 限制，直接喷射无污染的纯文本行"""
        try:
            self.redis_handler.redis_client.setex(task_id, 600, str(log_message))
        except Exception as e:
            print(f"向网页最下端虚拟终端同步状态异常: {e}")

    def _run_heartbeat_loop(self, target_ids, stop_event, task_id):
        from utils.send_data import send_heartbeat
        self._update_live_monitor(task_id, f"SUCCESS: [{self.can_bus}] 通道硬件链路完全正常。心跳发送中，正持续维持有效 ID {target_ids} 的连接...")
        
        while not stop_event.is_set():
            try:
                send_heartbeat(self.can_bus, target_ids)
                time.sleep(1)
            except Exception as e:
                print(f"[{self.can_bus}] 异步心跳发送异常中断: {e}")
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
                
                # 动态提取网页端单号
                task_id = task.get('task_id', f'{self.station_name}_{self.can_bus}_check_task').strip()
                redis_key = f"{self.station_name}_{self.can_bus}_check_result".strip()

                # ============================== 任务 1：点击 CheckCAN ==============================
                if task_name == 'connectivity_checkcan' or operation == 'check_can':
                    self._stop_existing_heartbeat()
                    
                    self._update_live_monitor(task_id, f"正在自动扫描物理 {self.can_bus} 通道上的电机响应，请稍候...")

                    test_slots = task.get('parameters', {})
                    expected_ids = [
                        int(slot['can_msg_id']) for slot in test_slots 
                        if str(slot.get('serial_number', '')).strip() != ""
                    ]

                    if not expected_ids:
                        err_txt = "未检测到操作员输入任何序列号，请至少在一个槽位输入数据再检测！"
                        self.redis_handler.set_value(redis_key, {"status": "error", "message": err_txt})
                        self._update_live_monitor(task_id, f"ERROR: {err_txt}")
                        continue

                    print(f"[{self.can_bus}] 检测判定启动 -> 目标 ID 范围: {expected_ids}")
                    
                    try:
                        can_bus_interface = can.interface.Bus(channel=self.can_bus, interface='socketcan')
                    except Exception as e:
                        err_txt = f"物理 SocketCAN 接口 [{self.can_bus}] 开启失败: {str(e)}"
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
                    
                    can_bus_interface.shutdown()

                    missing_ids = [idx for idx in expected_ids if idx not in found_devices]

                    if not missing_ids:
                        self.redis_handler.set_value(redis_key, {"status": "success", "message": "can全识别到了继续下一步"})
                        self._update_live_monitor(task_id, "SUCCESS: can全识别到了继续下一步")
                        
                        # 检测成功，拉起长连接发心跳线程
                        stop_event = threading.Event()
                        hb_thread = threading.Thread(
                            target=self._run_heartbeat_loop, 
                            args=(expected_ids, stop_event, task_id)
                        )
                        hb_thread.daemon = True
                        hb_thread.start()
                        
                        self.heartbeat_event = stop_event
                        self.heartbeat_thread = hb_thread
                    else:
                        missing_str = ", ".join(map(str, missing_ids))
                        err_txt = f"检测到 CANID: {missing_str} 缺失。请检查线缆连接或者是否正确执行 calibration。"
                        self.redis_handler.set_value(redis_key, {"status": "missing", "missing_ids": missing_ids, "message": err_txt})
                        self._update_live_monitor(task_id, f"CRITICAL ERROR: {err_txt}")

                # ============================== 任务 2：点击 Complete ==============================
                elif task_name == 'complete_test' or operation == 'complete':
                    self._stop_existing_heartbeat()
                    self.redis_handler.set_value(redis_key, {"status": "idle", "message": "等待检测"})
                    self._update_live_monitor(task_id, "STATUS: 清理重置动作已完成。")

            except queue.Empty:
                continue

    def start_consuming(self):
        # 监听指定的单个专属队列
        self.channel.basic_consume(queue=self.queue_name, on_message_callback=self.callback, auto_ack=False)
        print(f"成功在后台挂起！监听并向 RabbitMQ 自动维护队列: [{self.queue_name}]")
        self.channel.start_consuming()

if __name__ == "__main__":
    # 🌟 仿照主系统逻辑：如果启动时没传队列名参数，自动去读取本地配置进行拼接兜底
    if len(sys.argv) < 2:
        station_name = read_station_conf().get("station_name", "unknown_station").strip()
        # 默认监听 can0 专属连接队列
        target_queue = f"canconnect_queue_{station_name}_can0"
    else:
        target_queue = sys.argv[1]

    service = CanConnectivityService(queue_name=target_queue, server_ip='192.168.2.47', port=5672)
    service.start_consuming()