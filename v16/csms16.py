import asyncio
import logging
from datetime import datetime, timezone
import websockets
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.logging import RichHandler
from ocpp.routing import on
from ocpp.v16 import ChargePoint as BaseChargePoint, call_result
from ocpp.v16.enums import Action, RegistrationStatus

# Setup rich logging
logging.basicConfig(
    level=logging.INFO, handlers=[RichHandler()],
    format="%(message)s"
)
logger = logging.getLogger("csms")
console = Console()

VALID_TOKENS = ["RFID_123", "RFID_456"]  # Could be loaded from file

class ChargePoint(BaseChargePoint):
    def __init__(self, id, connection):
        super().__init__(id, connection)
        # Store transactions as dictionaries with meter_start and meter_current
        self.transactions = {}  # transaction_id -> {"meter_start": int, "meter_current": int}

    def _print_direction(self, msg: str, direction: str):
        arrow = "[bold green]←[/]" if direction == "cp→csms" else "[bold blue]→[/]"
        console.print(f"{arrow} {msg}")

    @on(Action.boot_notification)
    def on_boot_notification(self, charge_point_vendor, charge_point_model, **kwargs):
        self._print_direction(f"BootNotification from CP (vendor={charge_point_vendor}, model={charge_point_model})", "cp→csms")
        return call_result.BootNotification(
            current_time=datetime.now(timezone.utc).isoformat(),
            interval=10,
            status=RegistrationStatus.accepted,
        )

    @on(Action.heartbeat)
    def on_heartbeat(self):
        self._print_direction("Heartbeat received", "cp→csms")
        return call_result.Heartbeat(current_time=datetime.now(timezone.utc).isoformat())

    @on(Action.authorize)
    def on_authorize(self, id_tag: str):
        self._print_direction(f"Authorize request id_tag={id_tag}", "cp→csms")
        status = "Accepted" if id_tag in VALID_TOKENS else "Invalid"
        logger.info(f"Authorization status: {status}")
        return call_result.Authorize(id_tag_info={"status": status})

    @on(Action.start_transaction)
    def on_start_transaction(self, connector_id: int, id_tag: str, meter_start: int, timestamp: str):
        self._print_direction(f"StartTransaction connector={connector_id}, id_tag={id_tag}", "cp→csms")
        tx_id = len(self.transactions) + 1
        # Initialize transaction with a dictionary
        self.transactions[tx_id] = {"meter_start": meter_start, "meter_current": meter_start}
        return call_result.StartTransaction(transaction_id=tx_id, id_tag_info={"status": "Accepted"})

    @on(Action.meter_values)
    def on_meter_values(self, connector_id: int, meter_value: list, transaction_id: int = None):
        energy = int(meter_value[0]["sampled_value"][0]["value"])
        self._print_direction(f"MeterValues {energy} Wh at connector {connector_id}", "cp→csms")
        console.print(Panel(f"[bold yellow]Billing:[/] {energy} Wh used", title="CSMS"))
        # Update meter_current if transaction_id exists
        if transaction_id and transaction_id in self.transactions:
            self.transactions[transaction_id]["meter_current"] = energy
            logger.info(f"Updated meter_current for transaction {transaction_id} to {energy} Wh")
        return call_result.MeterValues()

    @on(Action.stop_transaction)
    def on_stop_transaction(self, transaction_id: int, meter_stop: int, timestamp: str, id_tag: str):
        self._print_direction(f"StopTransaction id={transaction_id}, meter_stop={meter_stop}, id_tag={id_tag}", "cp→csms")
        if transaction_id not in self.transactions:
            logger.warning(f"Unknown transaction ID: {transaction_id}")
            return call_result.StopTransaction(id_tag_info={"status": "Invalid"})
        tx_data = self.transactions[transaction_id]
        # Use meter_current if available, otherwise meter_stop
        total = (tx_data.get("meter_current", meter_stop) - tx_data["meter_start"])
        console.print(Panel(f"[bold yellow]Transaction {transaction_id} ended. Total: {total} Wh (User: {id_tag})", title="CSMS"))
        del self.transactions[transaction_id]
        return call_result.StopTransaction(id_tag_info={"status": "Accepted"})
    
    @on(Action.update_firmware)
    async def on_update_firmware(self, location: str, retrieve_date: str = None):
        self._print_direction(f"UpdateFirmware at {location}", "cp→csms")
        logger.info("Downloading firmware... 30s simulated delay")
        await asyncio.sleep(30)
        logger.info("Firmware update completed")
        return call_result.UpdateFirmware()

async def handle_connection(ws):
    if ws.subprotocol != "ocpp1.6":
        await ws.close()
        return
    cp_id = ws.request.path.strip("/")
    csms_cp = ChargePoint(cp_id, ws)
    logger.info(f"[CSMS] Connected to ChargePoint: {cp_id}")
    try:
        await csms_cp.start()
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"[CSMS] Connection closed for ChargePoint: {cp_id}")

async def main():
    server = await websockets.serve(
        handle_connection, "0.0.0.0", 9000, subprotocols=["ocpp1.6"]
    )
    logger.info("[CSMS] OCPP 1.6 Central System Ready on ws://0.0.0.0:9000")
    await server.wait_closed()

if __name__ == "__main__":
    asyncio.run(main())