from hobot_dnn import pyeasy_dnn as dnn

model_path = "/opt/tros/humble/lib/mono2d_body_detection/config/multitask_body_head_face_hand_kps_960x544.hbm"

print(f"🚀 正在尝试加载 BPU 模型: {model_path} ...")
try:
    models = dnn.load(model_path)
    print("✅ 加载成功！")
    
    print("\n[📥 输入 Tensor 详情]")
    for i, input_tensor in enumerate(models[0].inputs):
        # 抓取属性对象
        props = input_tensor.properties
        # 只打印 shape，绝不报错
        print(f"  - Input [{i}] shape: {props.shape}")
        
    print("\n[📤 输出 Tensor 详情]")
    for i, output_tensor in enumerate(models[0].outputs):
        props = output_tensor.properties
        print(f"  - Output [{i}] shape: {props.shape}")

    print("\n[🛠️ 极客探针：该对象到底有哪些隐藏属性？]")
    print(dir(models[0].outputs[0].properties))

except Exception as e:
    print(f"❌ 加载失败，原因: {e}")