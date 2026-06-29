import pika
import json
import time
import can
import pickle
import threading
from utils.station_conf import read_station_conf
from utils.redis_handler import RedisHandler

class CanConnectivityService:
    def __init__(self, server_ip='192.168.2.47', port=5672):
        self.station_name = read_station_conf().get("station_name", "unknown_station").strip()
        self.credentials = pika.PlainCredentials('admin', 'ni50509800')
        self.server_ip = server_ip
        self.port = port
        
        # 统一连向 192.168.2.47 服务器的 Redis
        self.redis_handler = RedisHandler(host=server_ip, port=6379, db=0)
        
        # 管理异步心跳守护线程
        self.heartbeat_managers = {
            "can0": {"event": None, "thread": None},
            "can1": {"event": None, "thread": None}
        }

    def start_service(self):
        connection = pika.BlockingConnection(pika.ConnectionParameters(
            host=self.server_ip, port=self.port, virtual_host='/', credentials=self.credentials, heartbeat=600))
        channel = connection.channel()

        for bus in ['can0', 'can1']:
            queue_name = f"canconnect_queue_{self.station_name}_can{bus}".strip()
            channel.queue_declare(queue=queue_name, durable=True)
            channel.basic_consume(
                queue=queue_name, 
                on_message_callback=lambda ch, method, properties, body, b=bus: self.callback(ch, method, properties, body, b),
                auto_ack=False
            )

        print(f"[{self.station_name}] 网页集成 CheckCAN 专属自动化检测服务（黑框完美对齐版）已成功启动！")
        channel.start_consuming()

    def _update_live_monitor(self, task_id, log_message):
        """🌟 专属黑框同步修正：跳过原 set_value 的序列化套娃，直接写入干净的纯文本"""
        try:
            # 使用原生客户端直接 set，设置 600 秒（10分钟）过期即可，防止脏数据一直卡着黑框
            self.redis_handler.redis_client.setex(task_id, 600, str(log_message))
        except Exception as e:
            print(f"向黑框日志写入数据异常: {e}")

    def _run_heartbeat_loop(self, can_bus, target_ids, stop_event, task_id):
        """在后台死循环高频发送心跳的线程函数"""
        print(f"[{can_bus}] 后台心跳守护线程已开启，目标 ID 列表: {target_ids}")
        
        while not stop_event.is_set():
            try:
                # 实时向黑框打字
                self._update_live_monitor(task_id, f"[{can_bus}] 检测成功。心跳持续激活中，正完美维持有效连接 ID: {target_ids} ...")
                send_heartbeat(can_bus, target_ids)
                time.sleep(1)
            except Exception as e:
                print(f"[{can_bus}] 发送心跳报文异常: {e}")
                time.sleep(1)
        print(f"[{can_bus}] 后台心跳守护线程已安全关闭。")

    def _stop_existing_heartbeat(self, can_bus):
        """安全停止某个通道现有的心跳线程"""
        manager = self.heartbeat_managers[can_bus]
        if manager["event"] is not None:
            manager["event"].set()
            if manager["thread"] is not None:
                manager["thread"].join(timeout=2.0)
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
            task_id = task.get('task_id', f'{self.station_name}_{can_bus}_check_task').strip()
            redis_key = f"{self.station_name}_{can_bus}_check_result".strip()
            
            # ============================== 任务 1：点击 CheckCAN ==============================
            if task_name == 'connectivity_checkcan':
                # 开启新检测，先把这个通道历史残留的老心跳全部强制杀掉
                self._stop_existing_heartbeat(can_bus)

                # 向黑框同步写一行纯净的开头文本：黑框绝不会再报错转圈
                self._update_live_monitor(task_id, f"正在高频自动检测 {can_bus} 的硬件连接状态，请稍候 5 秒...")

                test_slots = task.get('parameters', {})
                expected_ids = [
                    int(slot['can_msg_id']) for slot in test_slots 
                    if str(slot.get('serial_number', '')).strip() != ""
                ]

                if not expected_ids:
                    err_txt = "未检测到任何输入的电机序列号，请至少在一个槽位填入数据再执行 CheckCAN！"
                    self.redis_handler.set_value(redis_key, {"status": "error", "message": err_txt})
                    self._update_live_monitor(task_id, f"ERROR: {err_txt}")
                    return

                print(f"[{self.station_name} - {can_bus}] 收到任务 -> 目标检测 ID 列表: {expected_ids}")
                
                # 开启物理 SocketCAN 做 5 秒抓包探测
                try:
                    can_bus_interface = can.interface.Bus(channel=can_bus, interface='socketcan')
                except Exception as e:
                    err_txt = f"无法开启物理通道 {can_bus}: {str(e)}"
                    self.redis_handler.set_value(redis_key, {"status": "error", "message": err_txt})
                    self._update_live_monitor(task_id, f"ERROR: {err_txt}")
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

                # 精准计算缺失
                missing_ids = [idx for idx in expected_ids if idx not in found_devices]

                if not missing_ids:
                    # 1. 结果通知后台 API 判定
                    self.redis_handler.set_value(redis_key, {"status": "success", "message": "can全识别到了继续下一步"})
                    # 2. 纯净文字直接高亮打印在网页最下方的黑框里
                    self._update_live_monitor(task_id, "SUCCESS: can全识别到了，请点击 Execute 继续下一步。")
                    
                    # 3. 激活长连接异步心跳守护线程
                    stop_event = threading.Event()
                    hb_thread = threading.Thread(
                        target=self._run_heartbeat_loop, 
                        args=(can_bus, expected_ids, stop_event, task_id)
                    )
                    hb_thread.daemon = True
                    hb_thread.start()
                    
                    self.heartbeat_managers[can_bus]["event"] = stop_event
                    self.heartbeat_managers[can_bus]["thread"] = hb_thread
                else:
                    missing_str = ", ".join(map(str, missing_ids))
                    err_txt = f"检测到 CANID: {missing_str} 缺失。请检查线缆连接或者是否正确执行 calibration。"
                    
                    # 1. 通知判定键
                    self.redis_handler.set_value(redis_key, {"status": "missing", "missing_ids": missing_ids, "message": err_txt})
                    # 2. 红色警报字样直接喷在下方的黑框终端里
                    self._update_live_monitor(task_id, f"CRITICAL MISSING ERROR: {err_txt}")
                    print(f"[{can_bus}] 检测判定失败，未激活心跳。结果: {err_txt}")

            # ============================== 任务 2：点击 Complete ==============================
            elif task_name == 'complete_test':
                self._stop_existing_heartbeat(can_bus)
                
                self.redis_handler.set_value(redis_key, {"status": "idle", "message": "等待检测"})
                # 清除黑框历史
                self._update_live_monitor(task_id, "STATUS: 清理完毕。检测状态已复位，心跳守护已安全断开释放。")
                print(f"[{can_bus}] 收到清理指令，心跳守护线程已安全释放。")

        except Exception as e:
            print(f"解析检测队列的消息包失败: {e}")

if __name__ == "__main__":
    from utils.send_data import send_heartbeat  # 延迟导入确保上下文完整
    service = CanConnectivityService(server_ip='192.168.2.47', port=5672)
    service.start_service()