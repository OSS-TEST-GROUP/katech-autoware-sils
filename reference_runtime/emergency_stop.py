"""Request native STOP only; never enables or resumes autonomous control."""
import rclpy
from autoware_adapi_v1_msgs.srv import ChangeOperationMode
rclpy.init();n=rclpy.create_node('ctrack_fault_stop')
c=n.create_client(ChangeOperationMode,'/api/operation_mode/change_to_stop')
assert c.wait_for_service(timeout_sec=3),'STOP service unavailable'
f=c.call_async(ChangeOperationMode.Request())
rclpy.spin_until_future_complete(n,f,timeout_sec=3)
assert f.done() and f.result().status.success,str(f.result())
print('CTRACK native STOP acknowledged',flush=True)
n.destroy_node();rclpy.shutdown()
