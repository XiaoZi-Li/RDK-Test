import json
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class DecisionNode(Node):
    def __init__(self):
        super().__init__('decision_node')

        self.declare_parameter('image_width', 960.0)
        self.declare_parameter('image_height', 544.0)

        # 跟随距离阈值
        self.declare_parameter('follow_area_near_stop', 0.42)
        self.declare_parameter('follow_area_far_walk', 0.12)

        # 左右转阈值：放宽中间直行区，减少乱转
        self.declare_parameter('turn_left_ratio', 0.30)
        self.declare_parameter('turn_right_ratio', 0.70)

        self.declare_parameter('ghost_memory_time', 1.2)
        self.declare_parameter('publish_repeat_sec', 0.8)
        self.declare_parameter('log_interval_sec', 0.5)
        self.declare_parameter('gesture_hold_sec', 0.8)
        self.declare_parameter('follow_default_enabled', True)

        # 跟随动作保持
        self.declare_parameter('follow_min_hold_sec', 0.8)

        # 手势动作锁
        self.declare_parameter('gesture_action_lock_sec', 2.5)   # sit / stand
        self.declare_parameter('gesture_stop_lock_sec', 1.0)     # stop

        # stop 防抖
        self.declare_parameter('stop_confirm_sec', 0.45)

        self.image_width = float(self.get_parameter('image_width').value)
        self.image_height = float(self.get_parameter('image_height').value)

        self.follow_area_near_stop = float(self.get_parameter('follow_area_near_stop').value)
        self.follow_area_far_walk = float(self.get_parameter('follow_area_far_walk').value)

        self.turn_left_ratio = float(self.get_parameter('turn_left_ratio').value)
        self.turn_right_ratio = float(self.get_parameter('turn_right_ratio').value)

        self.ghost_memory_time = float(self.get_parameter('ghost_memory_time').value)
        self.publish_repeat_sec = float(self.get_parameter('publish_repeat_sec').value)
        self.log_interval_sec = float(self.get_parameter('log_interval_sec').value)
        self.gesture_hold_sec = float(self.get_parameter('gesture_hold_sec').value)
        self.follow_enabled = bool(self.get_parameter('follow_default_enabled').value)

        self.follow_min_hold_sec = float(self.get_parameter('follow_min_hold_sec').value)
        self.gesture_action_lock_sec = float(self.get_parameter('gesture_action_lock_sec').value)
        self.gesture_stop_lock_sec = float(self.get_parameter('gesture_stop_lock_sec').value)
        self.stop_confirm_sec = float(self.get_parameter('stop_confirm_sec').value)

        self.action_pub = self.create_publisher(String, '/puppy_action', 10)

        self.perception_sub = self.create_subscription(
            String,
            '/perception/result_json',
            self.perception_callback,
            10
        )

        self.gesture_sub = self.create_subscription(
            String,
            '/gesture/result_json',
            self.gesture_callback,
            10
        )

        self.last_action = 'none'
        self.last_source = 'none'
        self.last_send_time = 0.0
        self.last_log_time = 0.0

        self.last_person_time = 0.0
        self.last_person_area = 0.0

        self.current_gesture = None
        self.current_gesture_value = None
        self.gesture_expire_time = 0.0

        # 手势锁：锁期间 follow 不抢控制权
        self.gesture_lock_until = 0.0

        # follow 动作保持
        self.follow_action_hold_until = 0.0

        # stop 候选计时
        self.stop_candidate_since = 0.0

        self.get_logger().info(
            f'decision_node started. follow_enabled={self.follow_enabled}'
        )

    def perception_callback(self, msg: String):
        try:
            payload = json.loads(msg.data)
        except Exception as e:
            self.get_logger().error(f'Invalid perception JSON: {e}')
            return

        now = time.time()

        # 手势锁期间，不允许 follow 抢占
        if now < self.gesture_lock_until:
            return

        # follow 关闭时，不做跟随输出
        if not self.follow_enabled:
            return

        detections = payload.get('detections', [])
        desired_action = self.decide_follow_action(detections)
        final_action = self.apply_follow_action_smoothing(desired_action)

        self.publish_action(
            action=final_action,
            source='follow',
            extra={'follow_enabled': self.follow_enabled}
        )

    def gesture_callback(self, msg: String):
        try:
            payload = json.loads(msg.data)
        except Exception as e:
            self.get_logger().error(f'Invalid gesture JSON: {e}')
            return

        self.current_gesture = payload.get('gesture', None)
        self.current_gesture_value = payload.get('gesture_value', None)
        self.gesture_expire_time = time.time() + self.gesture_hold_sec

        gesture_action = self.map_gesture_to_action(self.current_gesture_value)
        if gesture_action is None:
            return

        now = time.time()

        if gesture_action == 'follow_on':
            self.follow_enabled = True
            self.gesture_lock_until = now + 0.5

        elif gesture_action == 'follow_off':
            self.follow_enabled = False
            self.gesture_lock_until = now + 0.5

        elif gesture_action == 'sit':
            self.follow_enabled = False
            self.gesture_lock_until = now + self.gesture_action_lock_sec

        elif gesture_action == 'stand':
            self.follow_enabled = True
            self.gesture_lock_until = now + self.gesture_action_lock_sec

        elif gesture_action == 'stop':
            self.follow_enabled = True
            self.gesture_lock_until = now + self.gesture_stop_lock_sec

        if now - self.last_log_time > self.log_interval_sec:
            self.get_logger().info(
                f'收到手势: gesture={self.current_gesture}, '
                f'value={self.current_gesture_value}, '
                f'mapped={gesture_action}, '
                f'follow_enabled={self.follow_enabled}'
            )
            self.last_log_time = now

        self.publish_action(
            action=gesture_action,
            source='gesture',
            extra={
                'follow_enabled': self.follow_enabled,
                'gesture': self.current_gesture,
                'gesture_value': self.current_gesture_value,
            }
        )

    def map_gesture_to_action(self, gesture_value):
        if gesture_value is None:
            return None

        try:
            value = float(gesture_value)
        except Exception:
            return None

        if value == 1.0:
            return 'follow_on'
        if value == 2.0:
            return 'follow_off'
        if value == 3.0:
            return 'stop'
        if value == 4.0:
            return 'sit'
        if value == 5.0:
            return 'stand'

        return None

    def decide_follow_action(self, detections):
        now = time.time()
        best_person = None
        best_area = 0.0

        for det in detections:
            if det.get('name') != 'person':
                continue

            bbox = det.get('bbox', None)
            if not bbox or len(bbox) != 4:
                continue

            x1, y1, x2, y2 = bbox
            box_w = max(0.0, x2 - x1)
            box_h = max(0.0, y2 - y1)
            if box_w <= 0 or box_h <= 0:
                continue

            area_ratio = (box_w * box_h) / (self.image_width * self.image_height)
            if area_ratio > best_area:
                best_area = area_ratio
                best_person = (x1, y1, x2, y2, area_ratio)

        # 没看到人
        if best_person is None:
            time_since_last_seen = now - self.last_person_time
            if time_since_last_seen < self.ghost_memory_time:
                return self.last_action if self.last_source == 'follow' else 'stop'
            return 'stop'

        x1, y1, x2, y2, area_ratio = best_person
        x_center = (x1 + x2) / 2.0
        cx_ratio = x_center / self.image_width

        self.last_person_time = now
        self.last_person_area = area_ratio

        # 先看距离，再看左右；中间区域优先 walk
        if area_ratio > self.follow_area_near_stop:
            action = 'stop'
        elif area_ratio < self.follow_area_far_walk:
            action = 'walk'
        else:
            if cx_ratio < self.turn_left_ratio:
                action = 'turn_left'
            elif cx_ratio > self.turn_right_ratio:
                action = 'turn_right'
            else:
                action = 'walk'

        if now - self.last_log_time > self.log_interval_sec:
            self.get_logger().info(
                f'目标锁定: cx={cx_ratio:.2f} | area={area_ratio:.2f} | desired={action}'
            )
            self.last_log_time = now

        return action

    def apply_follow_action_smoothing(self, desired_action: str):
        now = time.time()

        current_follow_action = self.last_action if self.last_source == 'follow' else 'stop'

        if self.last_source != 'follow':
            if desired_action in ['walk', 'turn_left', 'turn_right']:
                self.follow_action_hold_until = now + self.follow_min_hold_sec

            if desired_action == 'stop':
                self.stop_candidate_since = now
            else:
                self.stop_candidate_since = 0.0

            return desired_action

        # stop 需要确认，不允许单帧 stop 打断 walk/turn
        if desired_action == 'stop':
            if self.stop_candidate_since <= 0.0:
                self.stop_candidate_since = now

            stop_ready = (now - self.stop_candidate_since) >= self.stop_confirm_sec
            hold_expired = now >= self.follow_action_hold_until

            if current_follow_action in ['walk', 'turn_left', 'turn_right']:
                if (not stop_ready) or (not hold_expired):
                    return current_follow_action

            return 'stop'

        # 非 stop，清掉 stop 候选
        self.stop_candidate_since = 0.0

        if desired_action != current_follow_action:
            self.follow_action_hold_until = now + self.follow_min_hold_sec

        return desired_action

    def publish_action(self, action: str, source: str, extra=None):
        now = time.time()
        should_publish = (
            action != self.last_action
            or source != self.last_source
            or (now - self.last_send_time) > self.publish_repeat_sec
        )

        if not should_publish:
            return

        payload = {
            'action': action,
            'source': source,
            'timestamp': now,
        }
        if extra:
            payload.update(extra)

        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self.action_pub.publish(msg)

        self.last_action = action
        self.last_source = source
        self.last_send_time = now

        self.get_logger().info(f'发布动作: {msg.data}')


def main(args=None):
    rclpy.init(args=args)
    node = DecisionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            node.destroy_node()
        except Exception:
            pass
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:
            pass


if __name__ == '__main__':
    main()