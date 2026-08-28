from openai import OpenAI

client = OpenAI(
    base_url="http://132.254.211.161:30002/v1",
    api_key="sk-i3*************TR"
)

response = client.chat.completions.create(
    model="deepseek-v4-flash-0731",
    messages=[
        {"role": "system", "content": "你是一个友好的助手"},
        {"role": "user", "content": "你好，请介绍一下你自己"}
    ],
    temperature=0.7
)

print(response.choices[0].message.content)
print(f"Token使用: {response.usage.total_tokens}")
