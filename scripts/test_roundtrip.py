"""Round-trip A2A de prueba: message/send contra el subagente vuln."""
import asyncio

from pentest_agent.a2a_client import call_agent_async


async def main():
    out = await call_agent_async("http://127.0.0.1:9102", "Correlaciona: Apache 2.4.49")
    print(out[:1500])


asyncio.run(main())
