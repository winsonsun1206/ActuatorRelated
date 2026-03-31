from utils.db_handler import upload_test_record
from datetime import datetime

# 1. 模拟基础参数 (16项)
main_info = {
    "sn": "1566-1A0001-251203-001",    # 追溯号
    "name": "XA4.2 joint actuator",           # 关节名称
    "no": "J-001",             # 关节编号
    "can_id": 103,              # CAN ID
    "date": "2025-12-03",      # 生产日期
    "hw_v": "UNKNOWN",            # 硬件版本
    "sw_v": "XA4_0XBE_RIVR_V1_42_0.hex",          # 软件版本
    "t_id": "OP01",            # 测试员ID
    "t_name": "WAN",           # 测试员姓名
    "duration": 45.2,          # 测试耗时(秒)
    "cali": "Done",            # 校准结果
    "err": "0x00",             # 错误码
    "status": "PASS",          # 结论
    "curr": 0.02,              # 启动电流
    "volt": 48.0,              # 电压
    "temp": 55.5               # 最大温度
}

# 2. 模拟性能参数 (JSON 内部的动态数据：13, 14, 15项)
# 这里你可以精准地定义任何你想要的 Key
performance_info = {
    "viscous_cw": 0.92,        # 13. 顺时针粘性
    "viscous_ccw": 0.91,       # 14. 逆时针粘性
    "can_packet_loss": "0.00%",# 15. 丢包率
    "stability": "Stable",      # 15. 稳定性指标
    "notes": "Raspberry Pi Initial Test" # 额外想加的备注
}

# 执行上传
upload_test_record(main_info, performance_info)