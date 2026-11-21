from dotenv import load_dotenv       # 1
import anthropic

load_dotenv()

client = anthropic.Anthropic()        # 3

response = client.messages.create(
    model="claude-haiku-5-5",                # 4
    max_tokens=100,
    messages=[
        {"role": "user", "content": "Say hello in 5 words"}
    ],
)

print(response.content[0].text)  # 5
print(response.usage)             # 6