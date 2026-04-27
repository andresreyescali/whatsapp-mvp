import asyncio
import time

async def say_after(delay, what):
    await asyncio.sleep(delay)
    print(what)

async def main():
    task1 = asyncio.create_task(
        say_after(5,'Hello task1'),
        )

    task2 = asyncio.create_task(
        say_after(3,'Hello task2')
    )
    print(f"Tareas inician a {time.strftime('%X')}")

    await task1
    await task2 

print(f"Tareas terminan a {time.strftime('%X')}")

asyncio.run(main())