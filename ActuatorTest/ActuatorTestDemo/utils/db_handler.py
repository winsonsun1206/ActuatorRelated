import mysql.connector
import json
from datetime import datetime

# 服务器配置
DB_CONFIG = {
    'host': '192.168.2.47',
    'user': 'root',
    'password': 'finisar38559200', 
    'database': 'actuator_test_system_wzy'
}

def upload_test_record(main_data, perf_dict):
    """
    main_data: 包含固定的16个基础字段的字典
    perf_dict: 包含 13, 14, 15 项等动态参数的字典 (会自动转为 JSON)
    """
    conn = None
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()

        sql = """
        INSERT INTO product_test_records (
            trace_sn, joint_name, joint_no, can_id, 
            production_date, hw_version, sw_version, 
            tester_id, tester_name, test_duration_sec,
            calibration_result, error_code, final_status,
            start_current_a, voltage_v, max_temp_c,
            performance_details
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        # 将动态的性能数据精准转换为 JSON 字符串
        perf_json = json.dumps(perf_dict)

        values = (
            main_data.get('sn'), main_data.get('name'), main_data.get('no'), 
            main_data.get('can_id'), main_data.get('date'), main_data.get('hw_v'), 
            main_data.get('sw_v'), main_data.get('t_id'), main_data.get('t_name'),
            main_data.get('duration'), main_data.get('cali'), main_data.get('err'), 
            main_data.get('status'), main_data.get('curr'), main_data.get('volt'), 
            main_data.get('temp'), perf_json
        )

        cursor.execute(sql, values)
        conn.commit()
        print(f"成功上传记录！SN: {main_data.get('sn')}")
        return True
    except Exception as e:
        print(f"上传失败: {e}")
        return False
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()