import asyncio
import logging
import websockets
import ssl
from datetime import datetime, timezone
from rich.console import Console
from rich.panel import Panel
from rich.logging import RichHandler
from ocpp.routing import on
from ocpp.v201 import ChargePoint as cp, call_result
from ocpp.v201.enums import (
    Action, RegistrationStatusEnumType, AuthorizationStatusEnumType, FirmwareStatusEnumType
)

# Setup rich logging
logging.basicConfig(
    level=logging.INFO,
    handlers=[RichHandler()],
    format="%(message)s"
)
logger = logging.getLogger("csms201")
console = Console()

# Create SSL context for server
# Note: For TLS, ensure that 'csmscert.pem' and 'csmskey.pem' are present.
# You can generate self-signed certificates using:
# openssl req -x509 -newkey rsa:4096 -keyout csmskey.pem -out csmscert.pem -days 365 -nodes -config san.cnf
ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ssl_context.load_cert_chain('csmscert.pem', 'csmskey.pem')

class ChargePoint(cp):
    def __init__(self, id, connection):
        super().__init__(id, connection)
        self.pricing = 0.15  # $0.15/kWh

    def _print_direction(self, msg: str, direction: str):
        arrow = "[bold green]←[/]" if direction == "cp→csms" else "[bold blue]→[/]"
        console.print(f"{arrow} {msg}")

    @on(Action.boot_notification)
    def on_boot_notification(self, charging_station, reason):
        self._print_direction(
            f"BootNotification (model={charging_station['model']}, vendor={charging_station['vendor_name']})",
            "cp→csms"
        )
        return call_result.BootNotification(
            current_time=datetime.now(timezone.utc).isoformat(),
            interval=3600,
            status=RegistrationStatusEnumType.accepted
        )

    @on(Action.authorize)
    def on_authorize(self, id_token: dict):
        self._print_direction(f"Authorize (type={id_token['type']})", "cp→csms")
        logger.info(f"Received id_token: {id_token}")
        try:
            if id_token["type"] == "eMAID" and "VALID_CERT" in id_token["id_token"]:
                logger.info("Plug & Charge accepted")
                return call_result.Authorize(id_token_info={"status": AuthorizationStatusEnumType.accepted})
        except KeyError:
            pass
        
        logger.warning("Plug & Charge rejected")
        return call_result.Authorize(id_token_info={"status": AuthorizationStatusEnumType.invalid})
    
    @on(Action.transaction_event)
    def on_transaction_event(self, event_type: str, seq_no: int, trigger_reason: str, transaction_info: dict, meter_value: list, **kwargs):
        self._print_direction(f"TransactionEvent: {event_type}", "cp→csms")
        if event_type == "Updated":
            energy_used = meter_value[-1]["sampled_value"][0]["value"] / 1000  # kWh
            cost = energy_used * self.pricing
            console.print(Panel(
                f"[bold yellow]Energy:[/] {energy_used:.1f} kWh\n[bold yellow]Cost:[/] ${cost:.2f}",
                title="Billing Update"
            ))
        return call_result.TransactionEvent()

    @on(Action.firmware_status_notification)
    def on_firmware_status(self, status: FirmwareStatusEnumType):
        self._print_direction(f"FirmwareStatus: {status}", "cp→csms")
        logger.info(f"Firmware update status: {status}")
        return call_result.FirmwareStatusNotification()

async def on_connect(websocket):
    try:
        if websocket.subprotocol != "ocpp2.0.1":
            logger.warning("Invalid subprotocol, closing connection")
            await websocket.close()
            return

        charge_point_id = websocket.request.path.strip("/")
        cp = ChargePoint(charge_point_id, websocket)
        logger.info(f"[CSMS] Connected to ChargePoint: {charge_point_id}")
        await cp.start()
    except ssl.SSLError as e:
        logger.error(f"SSL error during connection: {e}")
    except Exception as e:
        logger.error(f"Connection error: {e}")

async def main():
    try:
        server = await websockets.serve(
            on_connect,
            "0.0.0.0",
            9000,
            subprotocols=["ocpp2.0.1"],
            ssl=ssl_context
        )
        logger.info("[bold]OCPP 2.0.1 Central System Ready on wss://0.0.0.0:9000[/]")
        await server.wait_closed()
    except ssl.SSLError as e:
        logger.error(f"SSL error starting server: {e}")
    except Exception as e:
        logger.error(f"Server startup failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())