import asyncio
import httpx

async def main():
    async with httpx.AsyncClient() as client:
        # Check if v1/chat/completions accepts slot_id
        res = await client.post("http://localhost:8080/v1/chat/completions", params={"slot_id": 0}, json={
            "messages": [{"role": "user", "content": "hello"}],
            "n_predict": 10,
            "stream": False
        })
        print(res.status_code)
        print(res.text)

asyncio.run(main())
