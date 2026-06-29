import pika
import json
import time
import can
import pickle
import threading
from utils.station_conf import read_station_conf
from utils.redis_handler import RedisHandler
from utils.send_data import send_heartbeat  # 完美复刻原 check_can_connectivity 中的心跳函数

class CanConnectivityService:
    def __init__(self, server_ip='192.168.2.47', port=5672):
        self.station_name = read_station_conf().get("station_name", "unknown_station").strip()
        self.credentials = pika.PlainCredentials('admin', 'ni50509800')
        self.server_ip = server_ip
        self.port = port
        self.redis_handler = RedisHandler(host=server_ip, port=6379, db=0)
        
        # 用于管理异步心跳线程的控制字典
        # 格式: {"can0": {"event": threading.Event(), "thread": Thread}, "can1": ...}
        self.heartbeat_managers = {
            "can0": {"event": None, "thread": None},
            "can1": {"event": None, "thread": None}
        }

    def start_service(self):
        connection = pika.BlockingConnection(pika.ConnectionParameters(
            self.server_ip, self.port, '/', self.credentials, heartbeat=600))
        channel = connection.channel()

        for bus in ['can0', 'can1']:
            queue_name = f"canconnect_queue_{self.station_name}_can{bus}".strip()
            channel.queue_declare(queue=queue_name, durable=True)
            channel.basic_consume(
                queue=queue_name, 
                on_message_callback=lambda ch, method, properties, body, b=bus: self.callback(ch, method, properties, body, b),
                auto_ack=False
            )

        print(f"[{self.station_name}] 网页集成 CheckCAN 专属自动化检测服务（含自动心跳守护）已成功启动！")
        channel.start_consuming()

    def _run_heartbeat_loop(self, can_bus, target_ids, stop_event):
        """在后台死循环发送心跳的线程函数"""
        print(f"[{can_bus}] 后台心跳守护线程已开启，目标 ID: {target_ids}")
        while not stop_event.is_set():
            try:
                # 严格按照你原先 check_can_connectivity.py 中的逻辑定义
                send_heartbeat(can_bus, target_ids)
                # 每隔 1 秒发送一次
                time.sleep(1)
            except Exception as e:
                print(f"[{can_bus}] 发送心跳报文异常: {e}")
                time.sleep(1)
        print(f"[{can_bus}] 后台心跳守护线程已安全关闭。")

    def _stop_existing_heartbeat(self, can_bus):
        """安全停止某个通道现有的心跳线程，防止重复叠加"""
        manager = self.heartbeat_managers[can_bus]
        if manager["event"] is not None:
            print(f"[{can_bus}] 检测到正在运行的老心跳，正在复位清理...")
            manager["event"].set()  # 触发停止信号
            if manager["thread"] is not None:
                manager["thread"].join(timeout=2.0)  # 等待老线程结束
            manager["event"] = None
            manager["thread"] = None

    def callback(self, ch, method, properties, body, can_bus):
        ch.basic_ack(delivery_tag=method.delivery_tag)
        
        try:
            try:
                task = json.loads(body.decode('utf-8'))
            except Exception:
                task = pickle.loads(body)

            task_name = task.get('task_name', '').strip()
            redis_key = f"{self.station_name}_{can_bus}_check_result".strip()
            
            # 1. 处理连接性检测任务
            if task_name == 'connectivity_checkcan':
                # 只要重新发起检测，先安全停掉这个通道历史的老心跳，防止通道冲突
                self._stop_existing_heartbeat(can_bus)

                test_slots = task.get('parameters', {})
                expected_ids = [
                    int(slot['can_msg_id']) for slot in test_slots 
                    if slot.get('serial_number', '').strip()
                ]

                if not  expected_ids:
                    self.redis_handler.set_value(redis_key, {"status": "error", "message": "未检测到任何输入的电机序列号，请至少输入一个再检测！"})
                    return

                print(f"[{self.station_name} - {can_bus}] 开始高频探测目标 ID: {expected_ids}")
                
                # 开启 SocketCAN 物理通道做 5 秒探测
                try:
                    can_bus_interface = can.interface.Bus(channel=can_bus, interface='socketcan')
                except Exception as e:
                    self.redis_handler.set_value(redis_key, {"status": "error", "message": f"底层无法开启物理通道 {can_bus}: {str(e)}"})
                    return

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

                # 比对缺失 ID
                missing_ids = [idx for idx in expected_ids if idx not in found_devices]

                if not missing_ids:
                    result_data = {
                        "status": "success",
                        "message": "can全识别到了继续下一步"
                    }
                    self.redis_handler.set_value(redis_key, result_data)
                    print(f"[{can_bus}] 探测全通过！准备在后台为识别到的 ID 启动持续心跳机制...")
                    
                    # 【核心核心】：只有当全部精准匹配成功时，才为这几个识别到的 ID 启动独立线程发心跳！
                    stop_event = threading.Event()
                    hb_thread = threading.Thread(
                        target=self._run_heartbeat_loop, 
                        args=(can_bus, expected_ids, stop_event)
                    )
                    hb_thread.daemon = True
                    hb_thread.start()
                    
                    # 记录并挂载到管理器中，便于后续控制
                    self.heartbeat_managers[can_bus]["event"] = stop_event
                    self.heartbeat_managers[can_bus]["thread"] = hb_thread
                else:
                    missing_str = ", ".join(map(str, missing_ids))
                    result_data = {
                        "status": "missing",
                        "missing_ids": missing_ids,
                        "message": f"检测到 CANID: {missing_str} 缺失。请检查线缆连接或者是否正确执行 calibration。"
                    }
                    self.redis_handler.set_value(redis_key, result_data)
                    print(f"[{can_bus}] 检测判定失败，未激活心跳。结果: {result_data}")

            # 2. 处理清除状态或停止任务
            elif task_name == 'complete_test':
                # 网页下发完成、或者后续点击了 Execute 开始跑正式测试了，就应该主动把 CheckCAN 模块的心跳关闭，让路给主测试程序
                self._stop_existing_heartbeat(can_bus)
                
                self.redis_handler.set_value(redis_key, {"status": "idle", "message": "等待检测"})
                print(f"[{can_bus}] 检测状态已重置为 idle，心跳已释放。")

        except Exception as e:
            print(f"解析来自魏工专属检测队列的消息包失败: {e}")

if __name__ == "__main__":
    service = CanConnectivityService()
    service.start_service()