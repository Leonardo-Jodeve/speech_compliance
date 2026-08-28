import os
import httpx
from mimetypes import guess_type

# ---------- 上传音频文件 ----------
def upload_audio(file_path: str, user: str = "admin") -> str:
    """上传音频文件，返回 file_id"""
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")

    ext = os.path.splitext(file_path)[1][1:].lower()
    supported = ['mp3', 'wav', 'ogg', 'm4a', 'flac', 'aac']
    if ext not in supported:
        raise ValueError(f"不支持的音频格式: {ext}，支持: {', '.join(supported)}")

    url = "https://aiagent.telecomjs.com:30080/v1/files/upload"
    headers = {"Authorization": "Bearer app-Xd***********XS2",
               "Znt-Staff-Code":"v2.oCjO6ugWNfSMVhGQ3pyvMjJ1qcXUWgodC8jwdj-Kkv_VzY4SnHt1VMBhv4ljUatNRQ6CXfl7ymmaheq0KXO83KvltQ0tilaZtXorz8fRvOMaVmNPBf475i1wysHXvH83U3lXcTd3OHw2HvVySM9r2aRvifzN1Ghi_9DHNHU2F8niuyuov8C-tMtijYQUmAPbGjKpVjzVzZRSs_Y8DGOQJ02yh8-ejnkpuO8"}
    mime_type, _ = guess_type(file_path)

    with open(file_path, "rb") as f:
        files = {
            "file": (os.path.basename(file_path), f, mime_type or "audio/mpeg"),
            "user": (None, user)
        }
        resp = httpx.post(url, headers=headers, files=files, timeout=30.0)
        resp.raise_for_status()
        return resp.json()["id"]

# ---------- 智能体调用（blocking模式）----------
def recognize_audio(file_id: str, query: str = "请识别音频内容") -> str:
    """使用 file_id 调用智能体，返回识别结果"""
    url = "https://aiagent.telecomjs.com:30080/v1/chat-messages/be4824db-3f67-43bb-9d4e-4e9c213b275f"
    headers = {
        "Authorization": "Bearer app-Xd***********XS2",
        "Content-Type": "application/json",
        "Znt-Staff-Code":"v2.oCjO6ugWNfSMVhGQ3pyvMjJ1qcXUWgodC8jwdj-Kkv_VzY4SnHt1VMBhv4ljUatNRQ6CXfl7ymmaheq0KXO83KvltQ0tilaZtXorz8fRvOMaVmNPBf475i1wysHXvH83U3lXcTd3OHw2HvVySM9r2aRvifzN1Ghi_9DHNHU2F8niuyuov8C-tMtijYQUmAPbGjKpVjzVzZRSs_Y8DGOQJ02yh8-ejnkpuO8"
    }
    payload = {
        "input_data": {"audio_file": {
                "transfer_method": "local_file",
                "upload_file_id": file_id,
                "type": "audio"          # 关键：type 需与文件类型匹配
            }},   # 音频文件 ID 作为路径传入
        "query": query,
        "mode": "blocking",                      # 非流式模式
        "conversation_id": "",
        "user": "smart_data_query_agent",
        "files": []                              # 音频不使用 files 字段
    }
    resp = httpx.post(url, headers=headers, json=payload, timeout=60.0)
    resp.raise_for_status()
    data = resp.json()
    return data.get("answer", "")

# ---------- 完整流程 ----------
def main(audio_path: str, query: str = "请识别音频内容") -> str:
    """上传音频并调用智能体识别"""
    print("上传音频文件中...")
    file_id = upload_audio(audio_path)
    print(f"上传成功，file_id: {file_id}")

    print("调用智能体识别...")
    result = recognize_audio(file_id, query)
    print("识别完成")
    return result

# 使用示例
if __name__ == "__main__":
    res = main("D:/Documents/录音.m4a", query="请将音频转换为文字，只输出转写结果")
    print(f"识别结果: {res}")